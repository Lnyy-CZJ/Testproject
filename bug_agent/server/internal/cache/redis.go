package cache

import (
	"bug-agent/internal/config"
	"context"
	"fmt"
	"bug-agent/pkg/logger"
	"time"

	"github.com/redis/go-redis/v9"
)

var RDB *redis.Client

func Init() {
	cfg := config.C.Redis

	RDB = redis.NewClient(&redis.Options{
		Addr:     cfg.Addr(),
		Password: cfg.Password,
		DB:       cfg.DB,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	_, err := RDB.Ping(ctx).Result()
	if err != nil {
		logger.Errorf("⚠️ Failed to connect to Redis (%s): %v", cfg.Addr(), err)
		RDB = nil
		return
	}

	logger.Infof("Redis connected @ %s (db=%d)", cfg.Addr(), cfg.DB)
}

// Get 获取缓存值
func Get(ctx context.Context, key string) (string, error) {
	if RDB == nil {
		return "", redis.Nil
	}
	return RDB.Get(ctx, key).Result()
}

func Set(ctx context.Context, key string, value interface{}, expiration time.Duration) error {
	if RDB == nil {
		logger.Warnf("[Cache] Redis not available, skip SET %s", key)
		return nil
	}
	return RDB.Set(ctx, key, value, expiration).Err()
}

func Del(ctx context.Context, keys ...string) error {
	if RDB == nil {
		return nil
	}
	return RDB.Del(ctx, keys...).Err()
}

func Exists(ctx context.Context, keys ...string) (int64, error) {
	if RDB == nil {
		return 0, nil
	}
	return RDB.Exists(ctx, keys...).Result()
}

// Close 关闭Redis连接
func Close() error {
	if RDB != nil {
		return RDB.Close()
	}
	return nil
}

// HealthCheck 健康检查
func HealthCheck(ctx context.Context) error {
	if RDB == nil {
		return fmt.Errorf("redis not connected")
	}
	_, err := RDB.Ping(ctx).Result()
	if err != nil {
		return fmt.Errorf("redis health check failed: %w", err)
	}
	return nil
}
