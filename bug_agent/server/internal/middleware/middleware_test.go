package middleware

import (
	"bug-agent/internal/config"
	"bug-agent/internal/model"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func setupMiddlewareRouter(db *gorm.DB) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	InitRBAC(db)
	InitAudit(db)
	return r
}

func setupMiddlewareSQLiteDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := "file:" + strings.ReplaceAll(t.Name(), "/", "_") + "?mode=memory&cache=shared"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		t.Fatalf("open sqlite db failed: %v", err)
	}
	if err := db.AutoMigrate(&model.User{}); err != nil {
		t.Fatalf("auto migrate sqlite db failed: %v", err)
	}
	return db
}

func TestAuthMiddleware_MissingHeader(t *testing.T) {
	db := setupMiddlewareSQLiteDB(t)
	router := setupMiddlewareRouter(db)

	router.GET("/test", JWTAuth(), func(c *gin.Context) {
		c.JSON(200, gin.H{"ok": true})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestAuthMiddleware_InvalidFormat(t *testing.T) {
	db := setupMiddlewareSQLiteDB(t)
	router := setupMiddlewareRouter(db)

	router.GET("/test", JWTAuth(), func(c *gin.Context) {
		c.JSON(200, gin.H{"ok": true})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	req.Header.Set("Authorization", "InvalidFormat token123")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestRBACMiddleware_RequirePermission_Denied(t *testing.T) {
	db := setupMiddlewareSQLiteDB(t)
	router := setupMiddlewareRouter(db)

	router.GET("/protected", RequirePermission("defects:create"), func(c *gin.Context) {
		c.JSON(200, gin.H{"ok": true})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/protected", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestRBACMiddleware_RequireRole_Denied(t *testing.T) {
	db := setupMiddlewareSQLiteDB(t)
	router := setupMiddlewareRouter(db)

	router.GET("/admin-only", RequireRole("super_admin"), func(c *gin.Context) {
		c.JSON(200, gin.H{"ok": true})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/admin-only", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestAuditMiddleware_RecordsRequest(t *testing.T) {
	db := setupMiddlewareSQLiteDB(t)
	router := setupMiddlewareRouter(db)

	router.GET("/test", AuditMiddleware(), func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "ok"})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test?foo=bar", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestGetUserID_DefaultValue(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()

	r.GET("/test", func(c *gin.Context) {
		userID := GetUserID(c)
		assert.Equal(t, uint(0), userID)
		c.JSON(200, gin.H{"userId": userID})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestSSEAuth_MissingToken(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()

	r.GET("/sse", func(c *gin.Context) {
		tokenStr := c.Query("token")
		if tokenStr == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "missing token"})
			return
		}
		c.JSON(200, gin.H{"status": "ok"})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/sse", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestSSEAuth_InvalidToken(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()

	r.GET("/sse", func(c *gin.Context) {
		tokenStr := c.Query("token")
		if tokenStr == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "missing token"})
			return
		}
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid token"})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/sse?token=invalid.test.token", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestPasswordChangeGuard_BlocksProtectedAPIsUntilPasswordChanged(t *testing.T) {
	db := setupMiddlewareSQLiteDB(t)
	router := setupMiddlewareRouter(db)
	config.C.JWT.Secret = "test-secret-at-least-16-bytes"
	config.C.JWT.ExpireHour = 1

	user := model.User{
		Username:           "must_change_guard_user",
		Email:              "must_change_guard_user@test.com",
		Password:           "hashed_password",
		MustChangePassword: true,
	}
	if err := db.Create(&user).Error; err != nil {
		t.Fatalf("create user failed: %v", err)
	}
	token, err := model.GenerateToken(user.ID, user.Username, config.C.JWT.Secret, config.C.JWT.ExpireHour)
	if err != nil {
		t.Fatalf("generate token failed: %v", err)
	}

	protectedHit := false
	router.GET("/protected", JWTAuth(), PasswordChangeGuard(db), func(c *gin.Context) {
		protectedHit = true
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	router.PUT("/users/me/password", JWTAuth(), PasswordChangeGuard(db), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/protected", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	router.ServeHTTP(w, req)
	assert.Equal(t, http.StatusForbidden, w.Code)
	assert.False(t, protectedHit)

	w = httptest.NewRecorder()
	req, _ = http.NewRequest(http.MethodPut, "/users/me/password", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	router.ServeHTTP(w, req)
	assert.Equal(t, http.StatusOK, w.Code)
}
