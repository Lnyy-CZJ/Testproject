package database

import (
	"bug-agent/internal/config"
	"bug-agent/pkg/logger"
	"fmt"
	"log"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"
)

var DB *gorm.DB

func Init() {
	var err error
	gormLogger := gormlogger.Default.LogMode(gormlogger.Info)
	if config.C.Server.Mode == "release" {
		gormLogger = gormlogger.Default.LogMode(gormlogger.Warn)
	}

	gormConfig := &gorm.Config{
		Logger: gormLogger,
	}

	cfg := config.C.Database
	dsn := cfg.GetDSN()

	DB, err = gorm.Open(postgres.Open(dsn), gormConfig)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}

	sqlDB, err := DB.DB()
	if err != nil {
		log.Fatalf("Failed to get underlying sql.DB: %v", err)
	}

	maxOpen := 50
	if cfg.MaxOpenConns > 0 {
		maxOpen = cfg.MaxOpenConns
	}
	maxIdle := 25
	if cfg.MaxIdleConns > 0 {
		maxIdle = cfg.MaxIdleConns
	}
	sqlDB.SetMaxOpenConns(maxOpen)
	sqlDB.SetMaxIdleConns(maxIdle)

	connMaxLifetime := 30 * time.Minute
	if cfg.ConnMaxLifetime > 0 {
		connMaxLifetime = time.Duration(cfg.ConnMaxLifetime) * time.Second
	}
	connMaxIdleTime := 5 * time.Minute
	if cfg.ConnMaxIdleTime > 0 {
		connMaxIdleTime = time.Duration(cfg.ConnMaxIdleTime) * time.Second
	}
	sqlDB.SetConnMaxLifetime(connMaxLifetime)
	sqlDB.SetConnMaxIdleTime(connMaxIdleTime)

	logger.Infof("Database connected (postgres) @ %s:%s/%s schema=%s",
		cfg.Host, cfg.Port, cfg.DBName, cfg.Schema)
}

func HealthCheck() error {
	if DB == nil {
		return fmt.Errorf("database not initialized")
	}
	sqlDB, err := DB.DB()
	if err != nil {
		return fmt.Errorf("db health check failed: %w", err)
	}
	return sqlDB.Ping()
}

func AutoMigrate(models ...interface{}) {
	err := DB.AutoMigrate(models...)
	if err != nil {
		log.Fatalf("Failed to migrate database: %v", err)
	}
	logger.Info("Database tables migrated successfully")
}
