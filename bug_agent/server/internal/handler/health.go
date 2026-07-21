package handler

import (
	"net/http"
	"time"

	"bug-agent/internal/cache"
	"bug-agent/internal/database"

	"github.com/gin-gonic/gin"
)

type HealthHandler struct{}

func NewHealthHandler() *HealthHandler {
	return &HealthHandler{}
}

func (h *HealthHandler) Healthz(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status": "ok",
	})
}

func (h *HealthHandler) Readiness(c *gin.Context) {
	checks := make(map[string]string)
	allHealthy := true

	start := time.Now()
	if err := database.HealthCheck(); err != nil {
		checks["database"] = "unhealthy: " + err.Error()
		allHealthy = false
	} else {
		checks["database"] = "healthy (" + time.Since(start).String() + ")"
	}

	start = time.Now()
	if err := cache.HealthCheck(c.Request.Context()); err != nil {
		checks["redis"] = "unhealthy: " + err.Error()
		allHealthy = false
	} else {
		checks["redis"] = "healthy (" + time.Since(start).String() + ")"
	}

	status := http.StatusOK
	if !allHealthy {
		status = http.StatusServiceUnavailable
	}

	c.JSON(status, gin.H{
		"status": map[bool]string{true: "ok", false: "degraded"}[allHealthy],
		"checks": checks,
	})
}
