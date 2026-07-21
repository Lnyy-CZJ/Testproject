package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestRateLimitMiddleware_Allowed(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(RateLimitMiddleware())
	r.GET("/test", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})

	for i := 0; i < 5; i++ {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/test", nil)
		req.RemoteAddr = "192.168.1.1:1234"
		r.ServeHTTP(w, req)

		if w.Code != http.StatusOK {
			t.Errorf("Expected 200 at iteration %d, got %d", i, w.Code)
		}
	}
}

func TestAPILimitMiddleware(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(APILimitMiddleware())
	r.GET("/api-test", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api-test", nil)
	req.RemoteAddr = "10.0.0.1:5678"
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("Expected 200 for first request, got %d", w.Code)
	}
}

func TestInitRateLimiter_Defaults(t *testing.T) {
	InitRateLimiter(50, 100)
	if rateLimiter == nil {
		t.Error("rateLimiter should not be nil after Init")
	}
}

func TestFormatRetryAfter(t *testing.T) {
	tests := []struct {
		input  float64
		expect string
	}{
		{0.3, "1s"},
		{1.5, "2s"},
		{10.0, "10s"},
		{9.6, "10s"},
	}
	for _, tc := range tests {
		result := formatRetryAfter(tc.input)
		if result != tc.expect {
			t.Errorf("formatRetryAfter(%v) = %s, want %s", tc.input, result, tc.expect)
		}
	}
}
