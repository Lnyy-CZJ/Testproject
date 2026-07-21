package service

import (
	"bug-agent/internal/model"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"gorm.io/gorm"
)

const PlatformSettingKeyNotificationEmail = "notification_email"

type PlatformEmailSettingsInput struct {
	SMTPHost     string
	SMTPPort     int
	SMTPUser     string
	SMTPPassword string
	SMTPFrom     string
}

type PlatformEmailSettingsView struct {
	SMTPHost           string `json:"smtpHost"`
	SMTPPort           int    `json:"smtpPort"`
	SMTPUser           string `json:"smtpUser"`
	SMTPFrom           string `json:"smtpFrom"`
	PasswordConfigured bool   `json:"passwordConfigured"`
}

type platformEmailSettingsStored struct {
	SMTPHost     string `json:"smtpHost"`
	SMTPPort     int    `json:"smtpPort"`
	SMTPUser     string `json:"smtpUser"`
	SMTPPassword string `json:"smtpPassword"`
	SMTPFrom     string `json:"smtpFrom"`
}

type PlatformSettingsService struct {
	db     *gorm.DB
	crypto *CredentialService
}

func NewPlatformSettingsService(db *gorm.DB) *PlatformSettingsService {
	return &PlatformSettingsService{
		db:     db,
		crypto: NewCredentialService(db),
	}
}

func (s *PlatformSettingsService) GetEmailSettings() (*PlatformEmailSettingsView, error) {
	stored, found, err := s.getStoredEmailSettings()
	if err != nil {
		return nil, err
	}
	if !found {
		return &PlatformEmailSettingsView{SMTPPort: 587}, nil
	}
	return s.toEmailSettingsView(stored), nil
}

func (s *PlatformSettingsService) SaveEmailSettings(updatedBy uint, input PlatformEmailSettingsInput) (*PlatformEmailSettingsView, error) {
	existing, _, err := s.getStoredEmailSettings()
	if err != nil {
		return nil, err
	}

	stored := platformEmailSettingsStored{
		SMTPHost: strings.TrimSpace(input.SMTPHost),
		SMTPPort: normalizeSMTPPort(input.SMTPPort),
		SMTPUser: strings.TrimSpace(input.SMTPUser),
		SMTPFrom: strings.TrimSpace(input.SMTPFrom),
	}

	if existing != nil && strings.TrimSpace(input.SMTPPassword) == "" {
		stored.SMTPPassword = existing.SMTPPassword
	} else if strings.TrimSpace(input.SMTPPassword) != "" {
		encrypted, encErr := s.crypto.encrypt(strings.TrimSpace(input.SMTPPassword))
		if encErr != nil {
			return nil, encErr
		}
		stored.SMTPPassword = encrypted
	}

	payload, err := json.Marshal(stored)
	if err != nil {
		return nil, err
	}

	var setting model.PlatformSetting
	result := s.db.Where("setting_key = ?", PlatformSettingKeyNotificationEmail).First(&setting)
	switch {
	case result.Error == nil:
		setting.Value = string(payload)
		setting.UpdatedBy = updatedBy
		if err := s.db.Save(&setting).Error; err != nil {
			return nil, err
		}
	case errors.Is(result.Error, gorm.ErrRecordNotFound):
		setting = model.PlatformSetting{
			SettingKey: PlatformSettingKeyNotificationEmail,
			Value:      string(payload),
			UpdatedBy:  updatedBy,
		}
		if err := s.db.Create(&setting).Error; err != nil {
			return nil, err
		}
	default:
		return nil, result.Error
	}

	return s.toEmailSettingsView(&stored), nil
}

func (s *PlatformSettingsService) GetEmailNotificationConfig() (*model.NotificationConfig, bool, error) {
	stored, found, err := s.getStoredEmailSettings()
	if err != nil || !found {
		return nil, found, err
	}

	password := ""
	if strings.TrimSpace(stored.SMTPPassword) != "" {
		decrypted, decErr := s.crypto.decrypt(stored.SMTPPassword)
		if decErr != nil {
			return nil, false, decErr
		}
		password = decrypted
	}

	return &model.NotificationConfig{
		SMTPHost:     stored.SMTPHost,
		SMTPPort:     normalizeSMTPPort(stored.SMTPPort),
		SMTPUser:     stored.SMTPUser,
		SMTPPassword: password,
		SMTPFrom:     stored.SMTPFrom,
	}, true, nil
}

func (s *PlatformSettingsService) TestEmailSettings(input PlatformEmailSettingsInput, to string) error {
	if strings.TrimSpace(to) == "" {
		return errors.New("test receiver email is required")
	}

	cfg := &model.NotificationConfig{
		SMTPHost:     strings.TrimSpace(input.SMTPHost),
		SMTPPort:     normalizeSMTPPort(input.SMTPPort),
		SMTPUser:     strings.TrimSpace(input.SMTPUser),
		SMTPPassword: strings.TrimSpace(input.SMTPPassword),
		SMTPFrom:     strings.TrimSpace(input.SMTPFrom),
	}
	return sendSMTPEmail(cfg, strings.TrimSpace(to), "BugAgent 平台邮件配置测试", "这是一封来自 BugAgent 平台配置的测试邮件。")
}

func (s *PlatformSettingsService) getStoredEmailSettings() (*platformEmailSettingsStored, bool, error) {
	var setting model.PlatformSetting
	if err := s.db.Where("setting_key = ?", PlatformSettingKeyNotificationEmail).First(&setting).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, false, nil
		}
		return nil, false, err
	}

	var stored platformEmailSettingsStored
	if err := json.Unmarshal([]byte(setting.Value), &stored); err != nil {
		return nil, false, fmt.Errorf("decode platform email settings failed: %w", err)
	}
	return &stored, true, nil
}

func (s *PlatformSettingsService) toEmailSettingsView(stored *platformEmailSettingsStored) *PlatformEmailSettingsView {
	if stored == nil {
		return &PlatformEmailSettingsView{SMTPPort: 587}
	}
	return &PlatformEmailSettingsView{
		SMTPHost:           stored.SMTPHost,
		SMTPPort:           normalizeSMTPPort(stored.SMTPPort),
		SMTPUser:           stored.SMTPUser,
		SMTPFrom:           stored.SMTPFrom,
		PasswordConfigured: strings.TrimSpace(stored.SMTPPassword) != "",
	}
}

func normalizeSMTPPort(port int) int {
	if port <= 0 {
		return 587
	}
	return port
}
