package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestNotificationService_Send(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "notify_user")

	t.Run("send in_app notification", func(t *testing.T) {
		result, err := svc.Send(&NotifyRequest{
			UserIDs:  []uint{user.ID},
			Title:    "测试通知",
			Content:  "这是一条测试通知",
			Type:     "in_app",
			Category: "system_announce",
		})

		assert.NoError(t, err)
		assert.Len(t, result, 1)
		assert.Equal(t, user.ID, result[0].UserID)
		assert.Equal(t, "测试通知", result[0].Title)
		assert.False(t, result[0].Read)
	})

	t.Run("send to multiple users", func(t *testing.T) {
		user2 := testutil.CreateTestUser(t, db, "notify_user2")

		result, err := svc.Send(&NotifyRequest{
			UserIDs:  []uint{user.ID, user2.ID},
			Title:    "群发通知",
			Content:  "多人通知",
			Type:     "in_app",
			Category: "system_announce",
		})

		assert.NoError(t, err)
		assert.Len(t, result, 2)
	})

	t.Run("email type without smtp config does not panic", func(t *testing.T) {
		result, err := svc.Send(&NotifyRequest{
			UserIDs:  []uint{user.ID},
			Title:    "邮件通知",
			Content:  "邮件内容",
			Type:     "email",
			Category: "defect_status_change",
		})

		assert.NoError(t, err)
		assert.Len(t, result, 1)
		assert.Equal(t, "email", result[0].Type)
	})

	t.Run("empty user_ids returns error", func(t *testing.T) {
		result, err := svc.Send(&NotifyRequest{
			UserIDs: []uint{},
			Title:   "空用户",
			Content: "空",
			Type:    "in_app",
		})

		assert.NoError(t, err)
		assert.Len(t, result, 0)
	})

	t.Run("respect user notification preference", func(t *testing.T) {
		pref := model.NotificationPreference{
			UserID:   user.ID,
			Category: "system_announce",
			Channels: "email",
		}
		db.Where("user_id = ? AND category = ?", user.ID, "system_announce").Delete(&model.NotificationPreference{})
		db.Create(&pref)

		result, err := svc.Send(&NotifyRequest{
			UserIDs:  []uint{user.ID},
			Title:    "偏好过滤",
			Content:  "不应发送站内消息",
			Type:     "in_app",
			Category: "system_announce",
		})

		assert.NoError(t, err)
		assert.Len(t, result, 0)
	})
}

func TestNotificationService_MirrorsInAppToPersonalWebhook(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "notify_webhook_user")

	var received atomic.Int32
	done := make(chan struct{}, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		received.Add(1)
		w.WriteHeader(http.StatusOK)
		select {
		case done <- struct{}{}:
		default:
		}
	}))
	defer server.Close()

	webhookSvc := NewUserWebhookService(db)
	secret := "personal-secret"
	if _, err := webhookSvc.Save(user.ID, UserWebhookSettingsInput{
		URL:     server.URL,
		Secret:  &secret,
		Enabled: true,
	}); err != nil {
		t.Fatalf("save personal webhook failed: %v", err)
	}

	result, err := svc.Send(&NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    "镜像测试",
		Content:  "站内消息",
		Type:     "in_app",
		Category: "system_announce",
	})
	assert.NoError(t, err)
	assert.Len(t, result, 1)

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("expected personal webhook mirror request")
	}

	assert.Equal(t, int32(1), received.Load())
}

func TestNotificationService_GetByUser(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "notify_list_user")

	for i := 0; i < 5; i++ {
		svc.Send(&NotifyRequest{
			UserIDs:  []uint{user.ID},
			Title:    fmt.Sprintf("通知 %d", i+1),
			Content:  fmt.Sprintf("内容 %d", i+1),
			Type:     "in_app",
			Category: "system_announce",
		})
	}

	t.Run("list with pagination", func(t *testing.T) {
		list, total, err := svc.GetByUser(user.ID, 1, 3)

		assert.NoError(t, err)
		assert.Equal(t, int64(5), total)
		assert.Len(t, list, 3)
	})

	t.Run("page 2", func(t *testing.T) {
		list, total, err := svc.GetByUser(user.ID, 2, 3)

		assert.NoError(t, err)
		assert.Equal(t, int64(5), total)
		assert.Len(t, list, 2)
	})
}

func TestNotificationService_MarkRead(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "notify_read_user")

	result, _ := svc.Send(&NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    "未读通知",
		Content:  "请阅读",
		Type:     "in_app",
		Category: "system_announce",
	})

	t.Run("mark single as read", func(t *testing.T) {
		ids := []uint{result[0].ID}
		affected, err := svc.MarkRead(user.ID, ids)

		assert.NoError(t, err)
		assert.Equal(t, int64(1), affected)

		var n model.Notification
		db.First(&n, result[0].ID)
		assert.True(t, n.Read)
	})

	t.Run("mark already read is no-op", func(t *testing.T) {
		ids := []uint{result[0].ID}
		affected, err := svc.MarkRead(user.ID, ids)

		assert.NoError(t, err)
		assert.Equal(t, int64(0), affected)
	})
}

func TestNotificationService_MarkAllRead(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "notify_allread_user")

	for i := 0; i < 3; i++ {
		svc.Send(&NotifyRequest{
			UserIDs:  []uint{user.ID},
			Title:    fmt.Sprintf("批量 %d", i),
			Content:  "内容",
			Type:     "in_app",
			Category: "system_announce",
		})
	}

	affected, err := svc.MarkAllRead(user.ID)
	assert.NoError(t, err)
	assert.Equal(t, int64(3), affected)

	count, _ := svc.GetUnreadCount(user.ID)
	assert.Equal(t, int64(0), count)
}

func TestNotificationService_UnreadCount(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "notify_count_user")

	count, err := svc.GetUnreadCount(user.ID)
	assert.NoError(t, err)
	assert.Equal(t, int64(0), count)

	svc.Send(&NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    "新通知",
		Content:  "新",
		Type:     "in_app",
		Category: "system_announce",
	})

	count, _ = svc.GetUnreadCount(user.ID)
	assert.Equal(t, int64(1), count)
}

func TestNotificationService_SendAssignment(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	assignee := testutil.CreateTestUser(t, db, "assignee")
	assigner := testutil.CreateTestUser(t, db, "assigner")

	n, err := svc.SendAssignment(assignee.ID, assigner.Nickname, "DEF-123", "登录页面崩溃")

	assert.NoError(t, err)
	assert.NotNil(t, n)
	assert.Equal(t, assignee.ID, n.UserID)
	assert.Equal(t, "defect_assigned", n.Category)
	assert.Contains(t, n.Title, "DEF-123")
}

func TestNotificationService_Metadata(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "meta_user")

	result, err := svc.Send(&NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    "带元数据",
		Content:  "测试",
		Type:     "in_app",
		Category: "defect_status_change",
		Metadata: map[string]interface{}{
			"defect_code": "DEF-456",
			"from_status": "new",
			"to_status":   "analyzing",
		},
	})

	assert.NoError(t, err)
	assert.NotEmpty(t, result[0].Metadata)
	assert.Contains(t, result[0].Metadata, "DEF-456")
}

func TestNotificationService_ProjectPolicyBlocksDisabledChannel(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "project_policy_user")
	project := testutil.CreateTestProject(t, db, "Project Policy", "PPOLI")

	policy := model.ProjectNotificationPolicy{
		ProjectID:    project.ID,
		Category:     "defect_mention",
		InAppEnabled: false,
		EmailEnabled: true,
		WebhookID:    nil,
	}
	if err := db.Create(&policy).Error; err != nil {
		t.Fatalf("create project policy failed: %v", err)
	}

	loadedPolicy, loadErr := svc.projectNotifSvc.lookupPolicy(project.ID, "defect_mention")
	assert.NoError(t, loadErr)
	if assert.NotNil(t, loadedPolicy) {
		assert.False(t, loadedPolicy.InAppEnabled)
	}
	assert.False(t, svc.projectNotifSvc.IsChannelEnabled(project.ID, "defect_mention", "in_app"))

	result, err := svc.Send(&NotifyRequest{
		UserIDs:   []uint{user.ID},
		Title:     "项目通知",
		Content:   "当前项目关闭站内消息",
		Type:      "in_app",
		Category:  "defect_mention",
		ProjectID: project.ID,
	})

	assert.NoError(t, err)
	assert.Len(t, result, 0)
}

func TestNotificationService_ProjectWebhookDispatchesSelectedTarget(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationService(db, nil)
	user := testutil.CreateTestUser(t, db, "project_webhook_user")
	project := testutil.CreateTestProject(t, db, "Project Webhook", "PWEBH")

	hitCh := make(chan string, 1)
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		hitCh <- req.Header.Get("X-Webhook-Secret")
		w.WriteHeader(http.StatusOK)
	}))
	defer mockServer.Close()

	webhook := model.ProjectWebhook{
		ProjectID: project.ID,
		Name:      "项目群机器人",
		URL:       mockServer.URL,
		Secret:    "project-secret",
		Enabled:   true,
	}
	if err := db.Create(&webhook).Error; err != nil {
		t.Fatalf("create webhook failed: %v", err)
	}

	policy := model.ProjectNotificationPolicy{
		ProjectID:    project.ID,
		Category:     "defect_mention",
		InAppEnabled: true,
		EmailEnabled: true,
		WebhookID:    &webhook.ID,
	}
	if err := db.Create(&policy).Error; err != nil {
		t.Fatalf("create project policy failed: %v", err)
	}

	result, err := svc.Send(&NotifyRequest{
		UserIDs:   []uint{user.ID},
		Title:     "项目 webhook",
		Content:   "应发送到项目 webhook",
		Type:      "in_app",
		Category:  "defect_mention",
		ProjectID: project.ID,
		Metadata: map[string]interface{}{
			"project_id": project.ID,
		},
	})

	assert.NoError(t, err)
	assert.Len(t, result, 1)

	select {
	case secret := <-hitCh:
		assert.Equal(t, "project-secret", secret)
	case <-time.After(2 * time.Second):
		t.Fatal("expected project webhook dispatch")
	}
}
