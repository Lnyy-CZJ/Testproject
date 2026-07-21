package config

import (
	"errors"
	"fmt"
	"os"

	"github.com/spf13/viper"
)

type Config struct {
	Server       ServerConfig       `mapstructure:"server"`
	Database     DatabaseConfig     `mapstructure:"database"`
	JWT          JWTConfig          `mapstructure:"jwt"`
	Redis        RedisConfig        `mapstructure:"redis"`
	Notification NotificationConfig `mapstructure:"notification"`
	Secrets      SecretsConfig      `mapstructure:"secrets"`
	MCP          MCPConfig          `mapstructure:"mcp"`
}

type MCPConfig struct {
	Servers []MCPServerEntry `mapstructure:"servers"`
}

type MCPServerEntry struct {
	Name    string `mapstructure:"name"`
	Command string `mapstructure:"command"`
	Args    string `mapstructure:"args"`
}

type SecretsConfig struct {
	CredentialEncryptKey   string `mapstructure:"credential_encrypt_key"`
	AIConfigEncryptionKey  string `mapstructure:"ai_config_encryption_key"`
	InviteCodeSignKey      string `mapstructure:"invite_code_sign_key"`
}

type ServerConfig struct {
	Port          string   `mapstructure:"port"`
	Mode          string   `mapstructure:"mode"`
	CorsOrigins   []string `mapstructure:"cors_origins"`
	AdminPassword string   `mapstructure:"admin_password"`
	UploadDir     string   `mapstructure:"upload_dir"`
}

type DatabaseConfig struct {
	Driver              string `mapstructure:"driver"` // postgres only
	Host                string `mapstructure:"host"`
	Port                string `mapstructure:"port"`
	User                string `mapstructure:"user"`
	Password            string `mapstructure:"password"`
	DBName              string `mapstructure:"dbname"`
	Schema              string `mapstructure:"schema"`
	DSN                 string `mapstructure:"dsn"` // fallback raw DSN
	SSLMode             string `mapstructure:"sslmode"`
	MaxOpenConns        int    `mapstructure:"max_open_conns"`
	MaxIdleConns        int    `mapstructure:"max_idle_conns"`
	ConnMaxLifetime     int    `mapstructure:"conn_max_lifetime_seconds"`
	ConnMaxIdleTime     int    `mapstructure:"conn_max_idle_time_seconds"`
}

func (d *DatabaseConfig) GetDSN() string {
	if d.DSN != "" {
		return d.DSN
	}
	sslmode := d.SSLMode
	if sslmode == "" {
		sslmode = "disable"
	}
	schema := d.Schema
	if schema == "" {
		schema = "public"
	}
	return fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s search_path=%s sslmode=%s",
		d.Host, d.Port, d.User, d.Password, d.DBName, schema, sslmode)
}

type JWTConfig struct {
	Secret     string `mapstructure:"secret"`
	ExpireHour int    `mapstructure:"expire_hour"`
}

type RedisConfig struct {
	Host     string `mapstructure:"host"`
	Port     string `mapstructure:"port"`
	Password string `mapstructure:"password"`
	DB       int    `mapstructure:"db"`
}

type NotificationConfig struct {
	SMTPHost      string `mapstructure:"smtp_host"`
	SMTPPort      int    `mapstructure:"smtp_port"`
	SMTPUser      string `mapstructure:"smtp_user"`
	SMTPPassword  string `mapstructure:"smtp_password"`
	SMTPFrom      string `mapstructure:"smtp_from"`
	WebhookURL    string `mapstructure:"webhook_url"`
	WebhookSecret string `mapstructure:"webhook_secret"`
}

func (r *RedisConfig) Addr() string {
	return fmt.Sprintf("%s:%s", r.Host, r.Port)
}

var C Config

func Init() {
	viper.SetConfigName("config")
	viper.SetConfigType("yaml")
	viper.AddConfigPath(".")
	viper.AddConfigPath("./cmd/server")

	viper.SetEnvPrefix("BUG_AGENT")
	viper.AutomaticEnv()

	if v := os.Getenv("DB_DRIVER"); v != "" {
		viper.Set("database.driver", v)
	}
	if v := os.Getenv("DB_HOST"); v != "" {
		viper.Set("database.host", v)
	}
	if v := os.Getenv("DB_PORT"); v != "" {
		viper.Set("database.port", v)
	}
	if v := os.Getenv("DB_USER"); v != "" {
		viper.Set("database.user", v)
	}
	if v := os.Getenv("DB_NAME"); v != "" {
		viper.Set("database.dbname", v)
	}
	if v := os.Getenv("DB_SCHEMA"); v != "" {
		viper.Set("database.schema", v)
	}

	viper.SetDefault("server.port", "8765")
	viper.SetDefault("server.mode", "debug")
	viper.SetDefault("database.driver", "postgres")
	viper.SetDefault("database.sslmode", "disable")
	viper.SetDefault("jwt.expire_hour", 72)
	viper.SetDefault("redis.host", "localhost")
	viper.SetDefault("redis.port", "6379")
	viper.SetDefault("redis.db", 0)
	viper.SetDefault("notification.smtp_port", 587)
	viper.SetDefault("notification.smtp_from", "noreply@bugagent.local")

	// Bind secret config keys to environment variables
	_ = viper.BindEnv("database.password", "DB_PASSWORD")
	_ = viper.BindEnv("redis.password", "REDIS_PASSWORD")
	_ = viper.BindEnv("secrets.credential_encrypt_key", "CREDENTIAL_ENCRYPT_KEY")
	_ = viper.BindEnv("secrets.ai_config_encryption_key", "AI_CONFIG_ENCRYPTION_KEY")
	_ = viper.BindEnv("secrets.invite_code_sign_key", "INVITE_CODE_SIGN_KEY")
	_ = viper.BindEnv("jwt.secret", "JWT_SECRET")
	_ = viper.BindEnv("server.admin_password", "ADMIN_PASSWORD")
	_ = viper.BindEnv("notification.smtp_password", "SMTP_PASSWORD")
	_ = viper.BindEnv("notification.webhook_secret", "WEBHOOK_SECRET")
	_ = viper.BindEnv("redis.host", "REDIS_HOST")
	_ = viper.BindEnv("redis.port", "REDIS_PORT")

	if err := viper.ReadInConfig(); err != nil {
		var configFileNotFound viper.ConfigFileNotFoundError
		if !errors.As(err, &configFileNotFound) {
			panic(fmt.Errorf("config file syntax error: %w", err))
		}
	}
	if err := viper.Unmarshal(&C); err != nil {
		panic(fmt.Errorf("config unmarshal failed: %w", err))
	}
	if C.Database.Host == "" || C.Database.DBName == "" {
		panic(fmt.Errorf("database host and dbname are required"))
	}
	if C.JWT.Secret == "" {
		panic(fmt.Errorf("jwt.secret is required: set JWT_SECRET environment variable"))
	}
	if len(C.JWT.Secret) < 16 {
		panic(fmt.Errorf("jwt.secret must be at least 16 characters for security"))
	}
	if C.Secrets.CredentialEncryptKey != "" && len(C.Secrets.CredentialEncryptKey) < 16 {
		panic(fmt.Errorf("secrets.credential_encrypt_key must be at least 16 characters for security"))
	}
	if C.Secrets.AIConfigEncryptionKey != "" && len(C.Secrets.AIConfigEncryptionKey) < 16 {
		panic(fmt.Errorf("secrets.ai_config_encryption_key must be at least 16 characters for security"))
	}
	if C.Secrets.InviteCodeSignKey != "" && len(C.Secrets.InviteCodeSignKey) < 16 {
		panic(fmt.Errorf("secrets.invite_code_sign_key must be at least 16 characters for security"))
	}
}
