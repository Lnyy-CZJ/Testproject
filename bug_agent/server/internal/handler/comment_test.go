package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestCommentHandler_CreateComment_SendsMentionNotification(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	commenter := testutil.CreateTestUser(t, db, "commenter_user")
	mentioned := testutil.CreateTestUser(t, db, "mentioned_user")
	defect := testutil.CreateTestDefect(t, db, "mention-comment-notify", commenter.ID)

	h := NewCommentHandler(nil)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", commenter.ID); c.Next() })
	r.POST("/defects/:id/comments", h.CreateComment)

	payload := map[string]interface{}{
		"content":  "@mentioned_user 请关注这个缺陷",
		"mentions": []uint{mentioned.ID},
	}
	raw, _ := json.Marshal(payload)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/comments", bytes.NewReader(raw))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("expected 201, got %d: %s", w.Code, w.Body.String())
	}

	var count int64
	if err := db.Model(&model.Notification{}).
		Where("user_id = ? AND category = ? AND related_id = ?", mentioned.ID, "defect_mention", defect.ID).
		Count(&count).Error; err != nil {
		t.Fatalf("query notifications failed: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected 1 mention notification, got %d", count)
	}
}
