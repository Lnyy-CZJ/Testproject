package service

import (
	"bug-agent/internal/model"
	"errors"
	"fmt"
	"strings"
	"time"

	"gorm.io/gorm"
)

var ErrUserWebhookURLRequired = errors.New("webhook url is required")
var ErrUserWebhookDispatchFailed = errors.New("user webhook dispatch failed")

type UserWebhookSettingsInput struct {
	URL     string
	Secret  *string
	Enabled bool
}

type UserWebhookSettingsView struct {
	URL              string `json:"url"`
	Enabled          bool   `json:"enabled"`
	SecretConfigured bool   `json:"secretConfigured"`
}

type resolvedUserWebhook struct {
	URL     string
	Secret  string
	Enabled bool
}

type UserWebhookService struct {
	db     *gorm.DB
	crypto *CredentialService
}

func NewUserWebhookService(db *gorm.DB) *UserWebhookService {
	return &UserWebhookService{
		db:     db,
		crypto: NewCredentialService(db),
	}
}

func (s *UserWebhookService) Get(userID uint) (*UserWebhookSettingsView, error) {
	setting, found, err := s.getSetting(userID)
	if err != nil {
		return nil, err
	}
	if !found {
		return &UserWebhookSettingsView{}, nil
	}
	return toUserWebhookView(setting), nil
}

func (s *UserWebhookService) Save(userID uint, input UserWebhookSettingsInput) (*UserWebhookSettingsView, error) {
	existing, found, err := s.getSetting(userID)
	if err != nil {
		return nil, err
	}

	url := strings.TrimSpace(input.URL)
	var encryptedSecret string
	if found {
		encryptedSecret = existing.Secret
	}
	if input.Secret != nil {
		secret := strings.TrimSpace(*input.Secret)
		if secret == "" {
			encryptedSecret = ""
		} else {
			encryptedSecret, err = s.crypto.encrypt(secret)
			if err != nil {
				return nil, err
			}
		}
	}

	if !found {
		if url == "" && encryptedSecret == "" && !input.Enabled {
			return &UserWebhookSettingsView{}, nil
		}
		existing = &model.UserWebhookSetting{
			UserID:  userID,
			URL:     url,
			Secret:  encryptedSecret,
			Enabled: input.Enabled,
		}
		if err := s.db.Create(existing).Error; err != nil {
			return nil, err
		}
		return toUserWebhookView(existing), nil
	}

	existing.URL = url
	existing.Secret = encryptedSecret
	existing.Enabled = input.Enabled
	if err := s.db.Save(existing).Error; err != nil {
		return nil, err
	}
	return toUserWebhookView(existing), nil
}

func (s *UserWebhookService) Resolve(userID uint) (*resolvedUserWebhook, bool, error) {
	setting, found, err := s.getSetting(userID)
	if err != nil || !found {
		return nil, found, err
	}
	if !setting.Enabled || strings.TrimSpace(setting.URL) == "" {
		return nil, false, nil
	}

	secret := ""
	if strings.TrimSpace(setting.Secret) != "" {
		secret, err = s.crypto.decrypt(setting.Secret)
		if err != nil {
			return nil, false, err
		}
	}

	return &resolvedUserWebhook{
		URL:     strings.TrimSpace(setting.URL),
		Secret:  secret,
		Enabled: setting.Enabled,
	}, true, nil
}

func (s *UserWebhookService) Test(userID uint, input UserWebhookSettingsInput) error {
	url := strings.TrimSpace(input.URL)
	secret := ""
	if input.Secret != nil {
		secret = strings.TrimSpace(*input.Secret)
	}

	if url == "" || (input.Secret == nil && secret == "") {
		resolved, found, err := s.Resolve(userID)
		if err != nil {
			return err
		}
		if found {
			if url == "" {
				url = resolved.URL
			}
			if input.Secret == nil {
				secret = resolved.Secret
			}
		}
	}

	if url == "" {
		return ErrUserWebhookURLRequired
	}

	if err := dispatchWebhookRequest(url, secret, map[string]interface{}{
		"event":     "personal_notification_test",
		"title":     "BugAgent 个人Webhook测试",
		"content":   "这是一条来自 BugAgent 的个人通知 Webhook 测试消息。",
		"user_id":   userID,
		"timestamp": time.Now().Unix(),
	}); err != nil {
		return fmt.Errorf("%w: %v", ErrUserWebhookDispatchFailed, err)
	}
	return nil
}

func (s *UserWebhookService) getSetting(userID uint) (*model.UserWebhookSetting, bool, error) {
	var setting model.UserWebhookSetting
	if err := s.db.Where("user_id = ?", userID).First(&setting).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, false, nil
		}
		return nil, false, err
	}
	return &setting, true, nil
}

func toUserWebhookView(setting *model.UserWebhookSetting) *UserWebhookSettingsView {
	if setting == nil {
		return &UserWebhookSettingsView{}
	}
	return &UserWebhookSettingsView{
		URL:              setting.URL,
		Enabled:          setting.Enabled,
		SecretConfigured: strings.TrimSpace(setting.Secret) != "",
	}
}
