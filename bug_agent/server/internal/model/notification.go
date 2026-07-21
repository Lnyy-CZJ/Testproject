package model

import "time"

type Notification struct {
	ID        uint      `gorm:"primaryKey" json:"id"`
	UserID    uint      `json:"userId" gorm:"index"`
	Title     string    `json:"title" gorm:"size:200"`
	Content   string    `json:"content" gorm:"type:text"`
	Type      string    `json:"type" gorm:"size:50"`
	Category  string    `json:"category" gorm:"size:50"`
	Read       bool       `json:"read" gorm:"default:false"`
	RelatedID  uint       `json:"relatedId" gorm:"index"`
	Metadata   string     `json:"metadata" gorm:"type:json"`
	EmailSentAt *time.Time `json:"emailSentAt" gorm:"index"`
	CreatedAt  time.Time  `json:"createdAt"`
}

func (Notification) TableName() string { return "notifications" }

type NotificationTemplate struct {
	ID       uint   `gorm:"primaryKey" json:"id"`
	Name     string `json:"name" gorm:"size:100;uniqueIndex"`
	Subject  string `json:"subject" gorm:"size:200"`
	Body     string `json:"body" gorm:"type:text"`
	Channel  string `json:"channel" gorm:"size:20"` // email, webhook, in_app
	Category string `json:"category" gorm:"size:50"`
	IsActive bool   `json:"isActive" gorm:"default:true"`
}

func (NotificationTemplate) TableName() string { return "notification_templates" }

type NotificationConfig struct {
	SMTPHost      string `mapstructure:"smtp_host"`
	SMTPPort      int    `mapstructure:"smtp_port"`
	SMTPUser      string `mapstructure:"smtp_user"`
	SMTPPassword  string `mapstructure:"smtp_password"`
	SMTPFrom      string `mapstructure:"smtp_from"`
	WebhookURL    string `mapstructure:"webhook_url"`
	WebhookSecret string `mapstructure:"webhook_secret"`
}
