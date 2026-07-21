package service

import (
	"bug-agent/internal/config"
	"bug-agent/internal/model"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"time"

	"gorm.io/gorm"
)

var ErrInviteCodeNotFound = errors.New("invite code not found")
var ErrInviteCodeExpired = errors.New("invite code expired")
var ErrInviteCodeExhausted = errors.New("invite code max uses reached")

type InviteService struct {
	db         *gorm.DB
	signKey    []byte
	signKeyErr error
}

func NewInviteService(db *gorm.DB) *InviteService {
	signKey, err := loadInviteSignKey()
	return &InviteService{
		db:         db,
		signKey:    signKey,
		signKeyErr: err,
	}
}

func (s *InviteService) GenerateCode(inviterID uint, maxUses int, expiresAt *time.Time) (*model.InviteCode, error) {
	if s.signKeyErr != nil {
		return nil, s.signKeyErr
	}

	entropy := make([]byte, 32) // PRD v2.0: 32-byte random
	if _, err := rand.Read(entropy); err != nil {
		return nil, err
	}
	signature := s.signEntropy(entropy)[:16] // 128-bit truncated MAC

	payload := make([]byte, 0, 48)
	payload = append(payload, entropy...)
	payload = append(payload, signature...)
	code := base64.RawURLEncoding.EncodeToString(payload) // fixed-length 64 chars

	invite := model.InviteCode{
		Code:      code,
		InviterID: inviterID,
		MaxUses:   maxUses,
		ExpiresAt: expiresAt,
	}
	if err := s.db.Create(&invite).Error; err != nil {
		return nil, err
	}
	return &invite, nil
}

func (s *InviteService) ListCodes(inviterID uint) ([]model.InviteCode, error) {
	var codes []model.InviteCode
	err := s.db.Where("inviter_id = ?", inviterID).Order("created_at desc").Find(&codes).Error
	return codes, err
}

func (s *InviteService) GetByCode(code string) (*model.InviteCode, error) {
	if s.signKeyErr != nil {
		return nil, s.signKeyErr
	}

	if !s.verifyCodeSignature(code) {
		return nil, ErrInviteCodeNotFound
	}

	var invite model.InviteCode
	err := s.db.Where("code = ?", code).First(&invite).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrInviteCodeNotFound
		}
		return nil, err
	}
	return &invite, nil
}

func (s *InviteService) AcceptCode(code string, userID uint) error {
	if s.signKeyErr != nil {
		return s.signKeyErr
	}

	if !s.verifyCodeSignature(code) {
		return ErrInviteCodeNotFound
	}

	return s.db.Transaction(func(tx *gorm.DB) error {
		var invite model.InviteCode
		if err := tx.Set("gorm:query_option", "FOR UPDATE").Where("code = ?", code).First(&invite).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return ErrInviteCodeNotFound
			}
			return err
		}
		if invite.ExpiresAt != nil && invite.ExpiresAt.Before(time.Now()) {
			return ErrInviteCodeExpired
		}
		if invite.MaxUses > 0 && invite.UsedCount >= invite.MaxUses {
			return ErrInviteCodeExhausted
		}
		if err := tx.Model(&invite).UpdateColumn("used_count", gorm.Expr("used_count + 1")).Error; err != nil {
			return err
		}
		if err := tx.Model(&model.User{}).Where("id = ?", userID).Update("invited_by", invite.InviterID).Error; err != nil {
			return fmt.Errorf("更新邀请人信息失败: %w", err)
		}
		return nil
	})
}

func (s *InviteService) ValidateCode(code string) (*model.InviteCode, error) {
	invite, err := s.GetByCode(code)
	if err != nil {
		return nil, err
	}
	if invite.ExpiresAt != nil && invite.ExpiresAt.Before(time.Now()) {
		return nil, ErrInviteCodeExpired
	}
	if invite.MaxUses > 0 && invite.UsedCount >= invite.MaxUses {
		return nil, ErrInviteCodeExhausted
	}
	return invite, nil
}

func loadInviteSignKey() ([]byte, error) {
	v := config.C.Secrets.InviteCodeSignKey
	if v == "" {
		return nil, errors.New("secrets.invite_code_sign_key is required in config")
	}
	if len(v) < 32 {
		return nil, errors.New("secrets.invite_code_sign_key must be at least 32 characters")
	}
	return []byte(v), nil
}

func (s *InviteService) signEntropy(entropy []byte) []byte {
	mac := hmac.New(sha256.New, s.signKey)
	mac.Write(entropy)
	return mac.Sum(nil)
}

func (s *InviteService) verifyCodeSignature(code string) bool {
	decoded, err := base64.RawURLEncoding.DecodeString(code)
	if err != nil || len(decoded) != 48 {
		return false
	}

	entropy := decoded[:32]
	gotSignature := decoded[32:]
	expectedSignature := s.signEntropy(entropy)[:16]
	return hmac.Equal(gotSignature, expectedSignature)
}

// RegisterWithInvite 使用邀请码完成注册并绑定邀请关系
func (s *InviteService) RegisterWithInvite(code, username, email, password, nickname string) (*model.User, error) {
	invite, err := s.ValidateCode(code)
	if err != nil {
		return nil, err
	}

	hashed, err := model.HashPassword(password)
	if err != nil {
		return nil, err
	}

	inviterID := invite.InviterID
	user := model.User{
		Username:  username,
		Email:     email,
		Password:  hashed,
		Nickname:  nickname,
		InvitedBy: &inviterID,
	}

	err = s.db.Transaction(func(tx *gorm.DB) error {
		var inviteLocked model.InviteCode
		if err := tx.Set("gorm:query_option", "FOR UPDATE").First(&inviteLocked, invite.ID).Error; err != nil {
			return fmt.Errorf("邀请码锁定失败: %w", err)
		}
		if inviteLocked.MaxUses > 0 && inviteLocked.UsedCount >= inviteLocked.MaxUses {
			return ErrInviteCodeExhausted
		}

		if err := tx.Create(&user).Error; err != nil {
			return err
		}

		return tx.Model(&model.InviteCode{}).
			Where("id = ?", invite.ID).
			UpdateColumn("used_count", gorm.Expr("used_count + 1")).Error
	})
	if err != nil {
		return nil, err
	}

	return &user, nil
}
