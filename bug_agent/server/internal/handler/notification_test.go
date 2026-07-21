package handler

import (
	"bug-agent/internal/service"
	"bug-agent/testutil"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func setupNotifyRouter(db interface{}) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	return r
}

func TestNotificationHandler_List(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupNotifyRouter(db)
	svc := service.NewNotificationService(db, nil)
	handler := NewNotificationHandler(db, svc)
	user := testutil.CreateTestUser(t, db, "notify_h_user")

	svc.Send(&service.NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    "列表测试",
		Content:  "内容",
		Type:     "in_app",
		Category: "system",
	})

	router.GET("/api/notifications", func(c *gin.Context) {
		c.Set("user_id", float64(user.ID))
		handler.List(c)
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/notifications", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Equal(t, float64(0), resp["code"])
	data := resp["data"].([]interface{})
	assert.GreaterOrEqual(t, len(data), 1)
}

func TestNotificationHandler_UnreadCount(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupNotifyRouter(db)
	svc := service.NewNotificationService(db, nil)
	handler := NewNotificationHandler(db, svc)
	user := testutil.CreateTestUser(t, db, "notify_h_count")

	svc.Send(&service.NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    "未读",
		Content:  "未读内容",
		Type:     "in_app",
		Category: "system",
	})

	router.GET("/api/notifications/unread-count", func(c *gin.Context) {
		c.Set("user_id", float64(user.ID))
		handler.UnreadCount(c)
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/notifications/unread-count", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Equal(t, float64(1), resp["count"])
}

func TestNotificationHandler_MarkRead(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupNotifyRouter(db)
	svc := service.NewNotificationService(db, nil)
	handler := NewNotificationHandler(db, svc)
	user := testutil.CreateTestUser(t, db, "notify_h_read")

	result, _ := svc.Send(&service.NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    "标记已读",
		Content:  "标记",
		Type:     "in_app",
		Category: "system",
	})

	router.PUT("/api/notifications/read", func(c *gin.Context) {
		c.Set("user_id", float64(user.ID))
		handler.MarkRead(c)
	})

	body, _ := json.Marshal(map[string]interface{}{
		"ids": []uint{result[0].ID},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/api/notifications/read", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Equal(t, float64(1), resp["affected_rows"])
}

func TestNotificationHandler_Send(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupNotifyRouter(db)
	svc := service.NewNotificationService(db, nil)
	handler := NewNotificationHandler(db, svc)
	user := testutil.CreateTestUser(t, db, "notify_h_send")

	router.POST("/api/notifications/send", func(c *gin.Context) {
		c.Set("user_id", float64(user.ID))
		handler.Send(c)
	})

	t.Run("valid send request", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"user_ids": []uint{user.ID},
			"title":    "发送测试",
			"content":  "通过API发送",
			"type":     "in_app",
			"category": "system",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/notifications/send", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var resp map[string]interface{}
		json.Unmarshal(w.Body.Bytes(), &resp)
		assert.Equal(t, float64(0), resp["code"])
		data := resp["data"].([]interface{})
		assert.Len(t, data, 1)
	})

	t.Run("empty user_ids returns 400", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"user_ids": []uint{},
			"title":    "空用户",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/notifications/send", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
	})
}
