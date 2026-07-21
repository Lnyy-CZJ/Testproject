package cache

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	DefaultSessionPrefix = "session:"
	DefaultLockPrefix    = "lock:"
	DefaultCachePrefix    = "cache:"
	DefaultRateLimitPrefix = "ratelimit:"
)

type SessionStore struct {
	rdb        *redis.Client
	expiration time.Duration
}

func NewSessionStore(expiration time.Duration) *SessionStore {
	if expiration == 0 {
		expiration = 24 * time.Hour
	}
	return &SessionStore{rdb: RDB, expiration: expiration}
}

func (s *SessionStore) Set(ctx context.Context, userID uint, data map[string]interface{}) error {
	if s.rdb == nil {
		return fmt.Errorf("redis not available")
	}
	key := fmt.Sprintf("%s%d", DefaultSessionPrefix, userID)
	val, err := json.Marshal(data)
	if err != nil {
		return err
	}
	return s.rdb.Set(ctx, key, val, s.expiration).Err()
}

func (s *SessionStore) Get(ctx context.Context, userID uint) (map[string]interface{}, error) {
	if s.rdb == nil {
		return nil, nil
	}
	key := fmt.Sprintf("%s%d", DefaultSessionPrefix, userID)
	val, err := s.rdb.Get(ctx, key).Result()
	if err == redis.Nil {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var data map[string]interface{}
	err = json.Unmarshal([]byte(val), &data)
	return data, err
}

func (s *SessionStore) Delete(ctx context.Context, userID uint) error {
	if s.rdb == nil {
		return fmt.Errorf("redis not available")
	}
	key := fmt.Sprintf("%s%d", DefaultSessionPrefix, userID)
	return s.rdb.Del(ctx, key).Err()
}

func (s *SessionStore) Refresh(ctx context.Context, userID uint) error {
	if s.rdb == nil {
		return fmt.Errorf("redis not available")
	}
	key := fmt.Sprintf("%s%d", DefaultSessionPrefix, userID)
	return s.rdb.Expire(ctx, key, s.expiration).Err()
}

type DistributedLock struct {
	rdb      *redis.Client
	token    string
	key      string
	ttl      time.Duration
	acquired bool
}

func NewLock(resource string, ttl time.Duration) *DistributedLock {
	if ttl == 0 {
		ttl = 30 * time.Second
	}
	return &DistributedLock{
		rdb:   RDB,
		token: generateToken(),
		key:   fmt.Sprintf("%s%s", DefaultLockPrefix, resource),
		ttl:   ttl,
	}
}

func (l *DistributedLock) TryAcquire(ctx context.Context) bool {
	if l.rdb == nil {
		return false
	}
	ok, err := l.rdb.SetNX(ctx, l.key, l.token, l.ttl).Result()
	if err != nil || !ok {
		return false
	}
	l.acquired = true
	return true
}

func (l *DistributedLock) Acquire(ctx context.Context) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
			if l.TryAcquire(ctx) {
				return nil
			}
			time.Sleep(50 * time.Millisecond)
		}
	}
}

func (l *DistributedLock) Release(ctx context.Context) error {
	if l.rdb == nil {
		return fmt.Errorf("redis not available")
	}
	if !l.acquired {
		return nil
	}
	script := `
		if redis.call("get", KEYS[1]) == ARGV[1] then
			return redis.call("del", KEYS[1])
		else
			return 0
		end
	`
	_, err := l.rdb.Eval(ctx, script, []string{l.key}, l.token).Result()
	l.acquired = false
	return err
}

func (l *DistributedLock) Extend(ctx context.Context, extraTTL time.Duration) bool {
	if l.rdb == nil {
		return false
	}
	script := `
		if redis.call("get", KEYS[1]) == ARGV[1] then
			return redis.call("pexpire", KEYS[1], ARGV[2])
		else
			return 0
		end
	`
	result, err := l.rdb.Eval(ctx, script, []string{l.key}, l.token, int(extraTTL.Milliseconds())).Result()
	if err != nil {
		return false
	}
	switch v := result.(type) {
	case int64:
		return v == 1
	case float64:
		return int64(v) == 1
	default:
		return false
	}
}

type RateLimiter struct {
	rate   int
	burst  int
	prefix string
}

func NewRateLimiter(rate, burst int) *RateLimiter {
	if rate <= 0 {
		rate = 100
	}
	if burst <= 0 {
		burst = rate * 2
	}
	return &RateLimiter{rate: rate, burst: burst, prefix: DefaultRateLimitPrefix}
}

func (rl *RateLimiter) Allow(ctx context.Context, identifier string) (bool, float64, error) {
	if RDB == nil {
		return true, 0, nil
	}
	key := fmt.Sprintf("%s%s", rl.prefix, identifier)
	now := time.Now().UnixMilli()
	windowMs := int64(rl.burst) * 1000 / int64(rl.rate)

	pipe := RDB.Pipeline()
	pipe.ZRemRangeByScore(ctx, key, "-inf", fmt.Sprintf("%d", now-windowMs))
	zcardCmd := pipe.ZCard(ctx, key)
	pipe.ZAdd(ctx, key, redis.Z{Score: float64(now + windowMs), Member: now})
	_, pipeErr := pipe.Exec(ctx)
	if pipeErr != nil && pipeErr != redis.Nil {
		return true, 0, pipeErr
	}

	count := zcardCmd.Val()
	resetAt := float64(now)/1000.0 + float64(count)/float64(rl.rate)

	if count > int64(rl.burst) {
		return false, resetAt - float64(time.Now().UnixMilli())/1000.0, nil
	}
	return true, resetAt - float64(time.Now().UnixMilli())/1000.0, nil
}

type CacheHelper struct {
	prefix     string
	defaultTTL time.Duration
}

func NewCacheHelper(prefix string, defaultTTL time.Duration) *CacheHelper {
	if defaultTTL == 0 {
		defaultTTL = 5 * time.Minute
	}
	return &CacheHelper{prefix: prefix, defaultTTL: defaultTTL}
}

func (c *CacheHelper) GetJSON(ctx context.Context, key string, dest interface{}) error {
	if RDB == nil {
		return ErrCacheMiss
	}
	val, err := RDB.Get(ctx, c.prefix+key).Result()
	if err == redis.Nil {
		return ErrCacheMiss
	}
	if err != nil {
		return err
	}
	return json.Unmarshal([]byte(val), dest)
}

func (c *CacheHelper) SetJSON(ctx context.Context, key string, value interface{}, ttl ...time.Duration) {
	if RDB == nil {
		return
	}
	expiration := c.defaultTTL
	if len(ttl) > 0 && ttl[0] > 0 {
		expiration = ttl[0]
	}
	data, err := json.Marshal(value)
	if err != nil {
		return
	}
	RDB.Set(ctx, c.prefix+key, data, expiration)
}

func (c *CacheHelper) Invalidate(ctx context.Context, keys ...string) error {
	if RDB == nil {
		return fmt.Errorf("redis not available")
	}
	redisKeys := make([]string, len(keys))
	for i, k := range keys {
		redisKeys[i] = c.prefix + k
	}
	return RDB.Del(ctx, redisKeys...).Err()
}

func (c *CacheHelper) InvalidatePattern(ctx context.Context, pattern string) error {
	if RDB == nil {
		return fmt.Errorf("redis not available")
	}
	iter := RDB.Scan(ctx, 0, c.prefix+pattern+"*", 0).Iterator()
	var keys []string
	for iter.Next(ctx) {
		keys = append(keys, iter.Val())
	}
	if len(keys) > 0 {
		return RDB.Del(ctx, keys...).Err()
	}
	return nil
}

var (
	ErrCacheMiss   = fmt.Errorf("cache miss")
	ErrLockNotHeld = fmt.Errorf("lock not held")
)

func generateToken() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}
