package middleware

import (
	"bug-agent/internal/config"
	"bug-agent/internal/model"
	"bug-agent/pkg/response"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"gorm.io/gorm"
)

// Token blacklist for revocation support.
//
// LIMITATION: This blacklist is stored in-process memory only and is lost on server restart.
// In production, consider replacing this with a persistent store (e.g. Redis SET with TTL)
// so that revoked tokens remain invalid across restarts and multi-instance deployments.
var (
	tokenBlacklist       = make(map[string]time.Time)
	tokenBlacklistMu     sync.RWMutex
	blacklistCleanupOnce sync.Once
)

func startBlacklistCleanup() {
	blacklistCleanupOnce.Do(func() {
		go func() {
			ticker := time.NewTicker(5 * time.Minute)
			defer ticker.Stop()
			for range ticker.C {
				CleanupExpiredBlacklist()
			}
		}()
	})
}

func init() {
	startBlacklistCleanup()
}

// RevokeToken adds a token's JTI to the blacklist with its expiration time
func RevokeToken(jti string, expiresAt time.Time) {
	tokenBlacklistMu.Lock()
	defer tokenBlacklistMu.Unlock()
	tokenBlacklist[jti] = expiresAt
}

func isTokenRevoked(jti string) bool {
	tokenBlacklistMu.RLock()
	defer tokenBlacklistMu.RUnlock()
	_, exists := tokenBlacklist[jti]
	return exists
}

// CleanupExpiredBlacklist removes tokens whose expiration time has passed.
// Should be called periodically.
func CleanupExpiredBlacklist() {
	tokenBlacklistMu.Lock()
	defer tokenBlacklistMu.Unlock()
	now := time.Now()
	for jti, expiresAt := range tokenBlacklist {
		if now.After(expiresAt) {
			delete(tokenBlacklist, jti)
		}
	}
}

type Claims struct {
	UserID   uint   `json:"userId"`
	Username string `json:"username"`
	JTI      string `json:"jti"`
	jwt.RegisteredClaims
}

func JWTAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			response.Unauthorized(c, "缺少认证头")
			c.Abort()
			return
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || parts[0] != "Bearer" {
			response.Unauthorized(c, "认证格式错误")
			c.Abort()
			return
		}

		token, err := jwt.ParseWithClaims(parts[1], &Claims{}, func(t *jwt.Token) (interface{}, error) {
			return []byte(config.C.JWT.Secret), nil
		}, jwt.WithValidMethods([]string{"HS256"}))

		if err != nil || !token.Valid {
			response.Unauthorized(c, "无效的令牌")
			c.Abort()
			return
		}

		if claims, ok := token.Claims.(*Claims); ok {
			if claims.JTI != "" && isTokenRevoked(claims.JTI) {
				response.Unauthorized(c, "令牌已被撤销")
				c.Abort()
				return
			}
			c.Set("userId", claims.UserID)
			c.Set("username", claims.Username)
			c.Set("jti", claims.JTI)
			c.Set("exp", claims.ExpiresAt.Unix())
		} else {
			response.Unauthorized(c, "无效的令牌")
			c.Abort()
			return
		}

		c.Next()
	}
}

func PasswordChangeGuard(db *gorm.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		if isPasswordChangeAllowedRequest(c) {
			c.Next()
			return
		}

		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "未登录")
			c.Abort()
			return
		}

		var user model.User
		if err := db.Select("id, must_change_password").First(&user, userID).Error; err != nil {
			response.Unauthorized(c, "用户不存在")
			c.Abort()
			return
		}
		if user.MustChangePassword {
			c.JSON(http.StatusForbidden, response.Response{
				Code:    http.StatusForbidden,
				Message: "请先修改初始密码",
				Data: gin.H{
					"mustChangePassword": true,
				},
			})
			c.Abort()
			return
		}

		c.Next()
	}
}

func isPasswordChangeAllowedRequest(c *gin.Context) bool {
	path := c.FullPath()
	if path == "" {
		path = c.Request.URL.Path
	}
	method := c.Request.Method

	switch {
	case method == http.MethodOptions:
		return true
	case method == http.MethodGet && strings.HasSuffix(path, "/users/me"):
		return true
	case method == http.MethodPut && strings.HasSuffix(path, "/users/me/password"):
		return true
	case method == http.MethodPost && strings.HasSuffix(path, "/auth/logout"):
		return true
	default:
		return false
	}
}

func GetUserID(c *gin.Context) uint {
	if v, exists := c.Get("userId"); exists {
		switch id := v.(type) {
		case uint:
			return id
		case float64:
			return uint(id)
		case int:
			return uint(id)
		case int64:
			return uint(id)
		case uint64:
			return uint(id)
		}
	}
	return 0
}
