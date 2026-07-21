package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestPlatformSettingsService_SaveAndGetEmailSettings(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewPlatformSettingsService(db)

	view, err := svc.SaveEmailSettings(1, PlatformEmailSettingsInput{
		SMTPHost:     "smtp.example.com",
		SMTPPort:     465,
		SMTPUser:     "robot@example.com",
		SMTPPassword: "smtp-secret",
		SMTPFrom:     "BugAgent <noreply@example.com>",
	})

	assert.NoError(t, err)
	if assert.NotNil(t, view) {
		assert.Equal(t, "smtp.example.com", view.SMTPHost)
		assert.Equal(t, 465, view.SMTPPort)
		assert.Equal(t, "robot@example.com", view.SMTPUser)
		assert.True(t, view.PasswordConfigured)
	}

	var setting model.PlatformSetting
	if err := db.Where("setting_key = ?", PlatformSettingKeyNotificationEmail).First(&setting).Error; err != nil {
		t.Fatalf("query platform setting failed: %v", err)
	}
	if strings.Contains(setting.Value, "smtp-secret") {
		t.Fatalf("smtp password should not be stored in plaintext")
	}

	cfg, found, err := svc.GetEmailNotificationConfig()
	assert.NoError(t, err)
	assert.True(t, found)
	if assert.NotNil(t, cfg) {
		assert.Equal(t, "smtp.example.com", cfg.SMTPHost)
		assert.Equal(t, 465, cfg.SMTPPort)
		assert.Equal(t, "robot@example.com", cfg.SMTPUser)
		assert.Equal(t, "smtp-secret", cfg.SMTPPassword)
		assert.Equal(t, "BugAgent <noreply@example.com>", cfg.SMTPFrom)
	}
}

func TestNotificationService_ResolveNotificationConfigPrefersPlatformSettings(t *testing.T) {
	db := testutil.SetupTestDB(t)
	settingsSvc := NewPlatformSettingsService(db)
	_, err := settingsSvc.SaveEmailSettings(1, PlatformEmailSettingsInput{
		SMTPHost:     "smtp.db.example.com",
		SMTPPort:     2525,
		SMTPUser:     "db-user@example.com",
		SMTPPassword: "db-secret",
		SMTPFrom:     "DB <db@example.com>",
	})
	if err != nil {
		t.Fatalf("save email settings failed: %v", err)
	}

	notifySvc := NewNotificationService(db, &model.NotificationConfig{
		SMTPHost:     "smtp.env.example.com",
		SMTPPort:     587,
		SMTPUser:     "env-user@example.com",
		SMTPPassword: "env-secret",
		SMTPFrom:     "ENV <env@example.com>",
	})

	cfg := notifySvc.resolveNotificationConfig()
	if assert.NotNil(t, cfg) {
		assert.Equal(t, "smtp.db.example.com", cfg.SMTPHost)
		assert.Equal(t, 2525, cfg.SMTPPort)
		assert.Equal(t, "db-user@example.com", cfg.SMTPUser)
		assert.Equal(t, "db-secret", cfg.SMTPPassword)
		assert.Equal(t, "DB <db@example.com>", cfg.SMTPFrom)
	}
}
