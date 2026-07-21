package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestProjectRoutingHandler_ModuleRuleReleaseCRUD(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	admin := testutil.CreateTestUser(t, db, "routing_admin")
	project := testutil.CreateTestProject(t, db, "Routing Project", "RTP")

	h := NewProjectRoutingHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.GET("/projects/:id/modules", h.ListModules)
	r.POST("/projects/:id/modules", h.CreateModule)
	r.PUT("/projects/:id/modules/:moduleId", h.UpdateModule)
	r.DELETE("/projects/:id/modules/:moduleId", h.DeleteModule)
	r.GET("/projects/:id/routing-rules", h.ListRules)
	r.POST("/projects/:id/routing-rules", h.CreateRule)
	r.PUT("/projects/:id/routing-rules/:ruleId", h.UpdateRule)
	r.DELETE("/projects/:id/routing-rules/:ruleId", h.DeleteRule)
	r.GET("/projects/:id/releases", h.ListReleases)
	r.POST("/projects/:id/releases", h.CreateRelease)
	r.PUT("/projects/:id/releases/:releaseId", h.UpdateRelease)
	r.DELETE("/projects/:id/releases/:releaseId", h.DeleteRelease)

	moduleBody := `{"name":"启动链路","code":"startup","description":"App 启动模块","ownerUserId":` + toStrUint(admin.ID) + `,"pathPattern":"app/startup/**","tags":"android,startup"}`
	moduleResp := httptest.NewRecorder()
	moduleReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/modules", bytes.NewBufferString(moduleBody))
	moduleReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(moduleResp, moduleReq)
	if moduleResp.Code != http.StatusCreated {
		t.Fatalf("expected create module 201, got %d: %s", moduleResp.Code, moduleResp.Body.String())
	}

	var modulePayload map[string]interface{}
	if err := json.Unmarshal(moduleResp.Body.Bytes(), &modulePayload); err != nil {
		t.Fatalf("unmarshal module payload failed: %v", err)
	}
	moduleID := uint(modulePayload["data"].(map[string]interface{})["id"].(float64))

	ruleBody := `{"matchType":"platform","matchValue":"android","moduleId":` + toStrUint(moduleID) + `,"ownerUserId":` + toStrUint(admin.ID) + `,"priorityOverride":"P0","severityOverride":"fatal","enabled":true,"sortOrder":10}`
	ruleResp := httptest.NewRecorder()
	ruleReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/routing-rules", bytes.NewBufferString(ruleBody))
	ruleReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(ruleResp, ruleReq)
	if ruleResp.Code != http.StatusCreated {
		t.Fatalf("expected create rule 201, got %d: %s", ruleResp.Code, ruleResp.Body.String())
	}

	var rulePayload map[string]interface{}
	if err := json.Unmarshal(ruleResp.Body.Bytes(), &rulePayload); err != nil {
		t.Fatalf("unmarshal rule payload failed: %v", err)
	}
	ruleID := uint(rulePayload["data"].(map[string]interface{})["id"].(float64))

	releaseBody := `{"platform":"android","appVersion":"5.0.0","buildNumber":"50001","channel":"prod","releaseTime":"2026-04-12T10:00:00Z","commitSha":"abc123","metadata":{"branch":"release/5.0.0"}}`
	releaseResp := httptest.NewRecorder()
	releaseReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/releases", bytes.NewBufferString(releaseBody))
	releaseReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(releaseResp, releaseReq)
	if releaseResp.Code != http.StatusCreated {
		t.Fatalf("expected create release 201, got %d: %s", releaseResp.Code, releaseResp.Body.String())
	}

	var releasePayload map[string]interface{}
	if err := json.Unmarshal(releaseResp.Body.Bytes(), &releasePayload); err != nil {
		t.Fatalf("unmarshal release payload failed: %v", err)
	}
	releaseID := uint(releasePayload["data"].(map[string]interface{})["id"].(float64))

	listResp := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/modules", nil)
	r.ServeHTTP(listResp, listReq)
	if listResp.Code != http.StatusOK {
		t.Fatalf("expected list modules 200, got %d: %s", listResp.Code, listResp.Body.String())
	}

	updateRuleBody := `{"matchType":"platform","matchValue":"ios","moduleId":` + toStrUint(moduleID) + `,"ownerUserId":` + toStrUint(admin.ID) + `,"priorityOverride":"P1","severityOverride":"major","enabled":true,"sortOrder":20}`
	updateRuleResp := httptest.NewRecorder()
	updateRuleReq, _ := http.NewRequest(http.MethodPut, "/projects/"+toStrUint(project.ID)+"/routing-rules/"+toStrUint(ruleID), bytes.NewBufferString(updateRuleBody))
	updateRuleReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(updateRuleResp, updateRuleReq)
	if updateRuleResp.Code != http.StatusOK {
		t.Fatalf("expected update rule 200, got %d: %s", updateRuleResp.Code, updateRuleResp.Body.String())
	}

	deleteReleaseResp := httptest.NewRecorder()
	deleteReleaseReq, _ := http.NewRequest(http.MethodDelete, "/projects/"+toStrUint(project.ID)+"/releases/"+toStrUint(releaseID), nil)
	r.ServeHTTP(deleteReleaseResp, deleteReleaseReq)
	if deleteReleaseResp.Code != http.StatusOK {
		t.Fatalf("expected delete release 200, got %d: %s", deleteReleaseResp.Code, deleteReleaseResp.Body.String())
	}

	deleteRuleResp := httptest.NewRecorder()
	deleteRuleReq, _ := http.NewRequest(http.MethodDelete, "/projects/"+toStrUint(project.ID)+"/routing-rules/"+toStrUint(ruleID), nil)
	r.ServeHTTP(deleteRuleResp, deleteRuleReq)
	if deleteRuleResp.Code != http.StatusOK {
		t.Fatalf("expected delete rule 200, got %d: %s", deleteRuleResp.Code, deleteRuleResp.Body.String())
	}

	deleteModuleResp := httptest.NewRecorder()
	deleteModuleReq, _ := http.NewRequest(http.MethodDelete, "/projects/"+toStrUint(project.ID)+"/modules/"+toStrUint(moduleID), nil)
	r.ServeHTTP(deleteModuleResp, deleteModuleReq)
	if deleteModuleResp.Code != http.StatusOK {
		t.Fatalf("expected delete module 200, got %d: %s", deleteModuleResp.Code, deleteModuleResp.Body.String())
	}

	var modules []model.ProjectModule
	if err := db.Find(&modules).Error; err != nil {
		t.Fatalf("query modules failed: %v", err)
	}
	if len(modules) != 0 {
		t.Fatalf("expected modules deleted, got %d", len(modules))
	}
}

func TestProjectRoutingHandler_ListReleaseTrends(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	admin := testutil.CreateTestUser(t, db, "routing_trend_admin")
	project := testutil.CreateTestProject(t, db, "Routing Trend Project", "RTR")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Trend Connector",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "routing_trend_connector",
		CreatedBy:    admin.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	h := NewProjectRoutingHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.GET("/projects/:id/releases", h.ListReleases)
	r.GET("/projects/:id/releases/trends", h.ListReleaseTrends)
	r.POST("/projects/:id/releases", h.CreateRelease)

	for _, body := range []string{
		`{"platform":"android","appVersion":"5.0.0","buildNumber":"50001","channel":"prod","releaseTime":"2026-04-11T10:00:00Z"}`,
		`{"platform":"android","appVersion":"5.1.0","buildNumber":"51001","channel":"prod","releaseTime":"2026-04-12T10:00:00Z"}`,
	} {
		resp := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/releases", bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(resp, req)
		if resp.Code != http.StatusCreated {
			t.Fatalf("expected create release 201, got %d: %s", resp.Code, resp.Body.String())
		}
	}

	ingest := service.NewSignalIngestService(db)
	if _, _, _, err := ingest.Ingest(connector, "test_seed", []byte(`{"eventId":"evt-routing-trend-1","title":"首页白屏","fingerprint":"fp-routing-trend-1","platform":"android","appVersion":"5.1.0","buildNumber":"51001","affectedUserCount":6}`)); err != nil {
		t.Fatalf("seed signal failed: %v", err)
	}

	resp := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/releases/trends", nil)
	r.ServeHTTP(resp, req)
	if resp.Code != http.StatusOK {
		t.Fatalf("expected list release trends 200, got %d: %s", resp.Code, resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"anomalyLevel":"watch"`)) {
		t.Fatalf("expected anomalyLevel watch in response, got %s", resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"appVersion":"5.1.0"`)) {
		t.Fatalf("expected app version in response, got %s", resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"affectedUserCount":6`)) {
		t.Fatalf("expected affected user count in response, got %s", resp.Body.String())
	}
}
