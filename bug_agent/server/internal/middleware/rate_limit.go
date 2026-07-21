package middleware

import (
	"context"
	"fmt"
	"net/http"
	"sync"
	"time"

	"bug-agent/internal/cache"
	"bug-agent/pkg/logger"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

const (
	redisRateLimitTimeout = 100 * time.Millisecond
	defaultRateLimitRate  = 100
	defaultRateLimitBurst = 200
	apiRateLimitRate      = 50
	apiRateLimitBurst     = 100
)

var (
	rateLimiter     *cache.RateLimiter
	rateLimiterOnce sync.Once

	apiLimiter     *cache.RateLimiter
	apiLimiterOnce sync.Once

	memoryLimiters   = make(map[string]*rate.Limiter)
	memoryLimitersMu sync.Mutex
	rateLimitStopCh  = make(chan struct{})
)

func StartRateLimitCleanup() {
	go func() {
		ticker := time.NewTicker(10 * time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				memoryLimitersMu.Lock()
				if len(memoryLimiters) > 10000 {
					keys := make([]string, 0, len(memoryLimiters))
					for k := range memoryLimiters {
						keys = append(keys, k)
					}
					for i := 0; i < len(keys)-5000; i++ {
						delete(memoryLimiters, keys[i])
					}
				}
				memoryLimitersMu.Unlock()
			case <-rateLimitStopCh:
				return
			}
		}
	}()
}

func StopRateLimitCleanup() {
	close(rateLimitStopCh)
}

func getMemoryLimiter(key string) *rate.Limiter {
	memoryLimitersMu.Lock()
	defer memoryLimitersMu.Unlock()
	if limiter, ok := memoryLimiters[key]; ok {
		return limiter
	}
	limiter := rate.NewLimiter(rate.Limit(defaultRateLimitRate/10), defaultRateLimitBurst/10)
	memoryLimiters[key] = limiter
	return limiter
}

// InitRateLimiter initializes the global rate limiter
func InitRateLimiter(rate, burst int) {
	rateLimiterOnce.Do(func() {
		rateLimiter = cache.NewRateLimiter(rate, burst)
	})
}

// RateLimitMiddleware creates a middleware that limits requests per IP
func RateLimitMiddleware() gin.HandlerFunc {
	rateLimiterOnce.Do(func() {
		if rateLimiter == nil {
			rateLimiter = cache.NewRateLimiter(defaultRateLimitRate, defaultRateLimitBurst)
		}
	})
	return func(c *gin.Context) {
		clientIP := c.ClientIP()
		ctx, cancel := context.WithTimeout(c.Request.Context(), redisRateLimitTimeout)
		defer cancel()

		allowed, retryAfter, err := rateLimiter.Allow(ctx, clientIP)
		if err != nil {
			logger.Warnf("[RateLimit] Redis unavailable, using in-memory fallback for %s", clientIP)
			limiter := getMemoryLimiter(clientIP)
			if !limiter.Allow() {
				c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
					"code":    http.StatusTooManyRequests,
					"message": "请求过于频繁",
				})
				return
			}
			c.Next()
			return
		}

		if !allowed {
			c.Header("X-Retry-After", formatRetryAfter(retryAfter))
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"code":       http.StatusTooManyRequests,
				"message":    "请求过于频繁",
				"retryAfter": int(retryAfter + 0.5),
			})
			return
		}

		c.Next()
	}
}

// APILimitMiddleware creates stricter rate limiting for API endpoints
func APILimitMiddleware() gin.HandlerFunc {
	apiLimiterOnce.Do(func() {
		apiLimiter = cache.NewRateLimiter(apiRateLimitRate, apiRateLimitBurst)
	})
	return func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), redisRateLimitTimeout)
		defer cancel()

		allowed, _, err := apiLimiter.Allow(ctx, "api:"+c.ClientIP())
		if err != nil {
			logger.Warnf("[RateLimit] Redis unavailable for API limit, using in-memory fallback for %s", c.ClientIP())
			limiter := getMemoryLimiter("api:" + c.ClientIP())
			if !limiter.Allow() {
				c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
					"code":    http.StatusTooManyRequests,
					"message": "API请求频率超限",
				})
				return
			}
			c.Next()
			return
		}
		if !allowed {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"code":    http.StatusTooManyRequests,
				"message": "API请求频率超限",
			})
			return
		}
		c.Next()
	}
}

func formatRetryAfter(seconds float64) string {
	s := int(seconds + 0.5)
	if s < 1 {
		s = 1
	}
	return fmt.Sprintf("%ds", s)
}
