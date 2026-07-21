package sse

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"bug-agent/internal/config"
	"bug-agent/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

type SSEHandler struct {
	broker *Broker
}

func NewSSEHandler(broker *Broker) *SSEHandler {
	return &SSEHandler{broker: broker}
}

func (h *SSEHandler) HandleSSE(c *gin.Context) {
	tokenStr := c.Query("token")
	if tokenStr == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "missing token"})
		return
	}

	cfg := config.C
	token, err := jwt.Parse(tokenStr, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return []byte(cfg.JWT.Secret), nil
	})
	if err != nil || !token.Valid {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid token"})
		return
	}

	roomsParam := c.Query("rooms")
	var rooms []string
	if roomsParam != "" {
		rooms = strings.Split(roomsParam, ",")
	} else {
		rooms = []string{"global"}
	}

	ch := h.broker.Subscribe(rooms)
	defer h.broker.Unsubscribe(ch)

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	c.Writer.Write([]byte(":connected\n\n"))
	if flusher, ok := c.Writer.(http.Flusher); ok {
		flusher.Flush()
	}

	ctx := c.Request.Context()
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return

		case <-ticker.C:
			c.Writer.Write([]byte(":keepalive\n\n"))
			if flusher, ok := c.Writer.(http.Flusher); ok {
				flusher.Flush()
			}

		case event, ok := <-ch:
			if !ok {
				return
			}
			data, err := json.Marshal(event.Data)
			if err != nil {
				logger.Errorf("[SSE Handler] marshal event failed: %v", err)
				continue
			}
			fmt.Fprintf(c.Writer, "event: %s\ndata: %s\n\n", event.Event, data)
			if flusher, ok := c.Writer.(http.Flusher); ok {
				flusher.Flush()
			}
		}
	}
}
