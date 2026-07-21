package handler

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestDefectHandler_CreateDraftFromChat(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "draft_chat_user")
	project := testutil.CreateTestProject(t, db, "Draft Chat Project", "DCP")
	iteration := model.Iteration{ProjectID: project.ID, Name: "Sprint Draft", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	h := NewDefectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	r.POST("/projects/:id/defects/draft-from-chat", h.CreateDraftFromChat)

	body := []byte(`{"message":"登录页按钮被键盘遮挡"}`)
	req := httptest.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/defects/draft-from-chat", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	if !bytes.Contains(w.Body.Bytes(), []byte(`"sourceMode":"manual_chat"`)) {
		t.Fatalf("expected manual_chat in response, got %s", w.Body.String())
	}
}

func TestDefectHandler_ConfirmCreateFromDraft_CreatesManualChatSignalAndCluster(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "draft_confirm_user")
	project := testutil.CreateTestProject(t, db, "Draft Confirm Project", "DCF")
	iteration := model.Iteration{ProjectID: project.ID, Name: "Sprint Confirm", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	h := NewDefectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	r.POST("/projects/:id/defects/confirm-create", h.ConfirmCreateDefect)

	body := []byte(`{"iterationId":` + toStrUint(iteration.ID) + `,"title":"登录按钮被键盘遮挡","descriptionMarkdown":"## 现象\n按钮被遮挡","severity":"major","priority":"P1","type":"ui","tags":["login","ios"],"sourceMode":"manual_chat"}`)
	req := httptest.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/defects/confirm-create", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d body=%s", w.Code, w.Body.String())
	}

	var resp struct {
		Data model.Defect `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response failed: %v", err)
	}
	if resp.Data.ID == 0 {
		t.Fatalf("expected created defect id")
	}

	var signal model.IssueSignal
	if err := db.Where("linked_defect_id = ?", resp.Data.ID).First(&signal).Error; err != nil {
		t.Fatalf("load manual signal failed: %v", err)
	}
	if signal.SourceType != model.IssueSourceManualChat {
		t.Fatalf("expected manual_chat source type, got %s", signal.SourceType)
	}
	if signal.ConnectorID != nil {
		t.Fatalf("expected nil connector for manual signal, got %+v", signal.ConnectorID)
	}

	var cluster model.IssueCluster
	if err := db.First(&cluster, *signal.ClusterID).Error; err != nil {
		t.Fatalf("load manual cluster failed: %v", err)
	}
	if cluster.Status != model.IssueTriageStatusConverted {
		t.Fatalf("expected converted cluster, got %s", cluster.Status)
	}
	if cluster.LinkedDefectID == nil || *cluster.LinkedDefectID != resp.Data.ID {
		t.Fatalf("expected linked defect on cluster, got %+v", cluster.LinkedDefectID)
	}
}

func TestDefectHandler_CreateDefect_AdvancedModeAlsoCreatesManualFormSignal(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "manual_form_user")
	project := testutil.CreateTestProject(t, db, "Manual Form Project", "MFP")
	iteration := model.Iteration{ProjectID: project.ID, Name: "Sprint Form", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	h := NewDefectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	r.POST("/defects", h.CreateDefect)

	body := []byte(`{"iterationId":` + toStrUint(iteration.ID) + `,"title":"高级模式创建缺陷","description":"描述正文","severity":"normal","priority":"P2","type":"functional","tags":["manual"]}`)
	req := httptest.NewRequest(http.MethodPost, "/defects", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d body=%s", w.Code, w.Body.String())
	}

	var defect model.Defect
	if err := json.Unmarshal(w.Body.Bytes(), &struct {
		Data *model.Defect `json:"data"`
	}{Data: &defect}); err != nil {
		t.Fatalf("unmarshal defect failed: %v", err)
	}
	if defect.ID == 0 {
		t.Fatalf("expected created defect")
	}

	var signal model.IssueSignal
	if err := db.Where("linked_defect_id = ?", defect.ID).First(&signal).Error; err != nil {
		t.Fatalf("load manual_form signal failed: %v", err)
	}
	if signal.SourceType != model.IssueSourceManualForm {
		t.Fatalf("expected manual_form source type, got %s", signal.SourceType)
	}
}
