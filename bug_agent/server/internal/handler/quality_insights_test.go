package handler

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestQualityInsightsHandler_GetOverview(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	project := testutil.CreateTestProject(t, db, "Quality Handler Project", "QHP")
	operator := testutil.CreateTestUser(t, db, "quality_handler_user")
	module := model.ProjectModule{
		ProjectID: project.ID,
		Name:      "支付模块",
		Code:      "PAY",
	}
	if err := db.Create(&module).Error; err != nil {
		t.Fatalf("create module failed: %v", err)
	}
	release := model.AppRelease{
		ProjectID:   project.ID,
		Platform:    "android",
		AppVersion:  "5.1.0",
		BuildNumber: "51001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 11, 10, 0, 0, 0, time.UTC),
	}
	if err := db.Create(&release).Error; err != nil {
		t.Fatalf("create release failed: %v", err)
	}
	_, _, cluster := seedIssueClusterForProject(t, db, project.ID, "quality_handler_seed")
	if err := db.Model(&model.IssueCluster{}).Where("id = ?", cluster.ID).Updates(map[string]interface{}{
		"module_id": module.ID,
		"status":    model.IssueTriageStatusIgnored,
	}).Error; err != nil {
		t.Fatalf("update cluster failed: %v", err)
	}
	if err := db.Model(&model.IssueSignal{}).Where("cluster_id = ?", cluster.ID).Updates(map[string]interface{}{
		"platform":            release.Platform,
		"app_version":         release.AppVersion,
		"build_number":        release.BuildNumber,
		"affected_user_count": 9,
	}).Error; err != nil {
		t.Fatalf("update signal failed: %v", err)
	}
	regression := model.RegressionItem{
		ProjectID:         project.ID,
		ClusterID:         &cluster.ID,
		Title:             cluster.Title,
		Summary:           cluster.Summary,
		SourceFingerprint: cluster.ClusterKey,
		Status:            model.RegressionItemStatusDraft,
		CreatedBy:         operator.ID,
	}
	if err := db.Create(&regression).Error; err != nil {
		t.Fatalf("create regression item failed: %v", err)
	}

	h := NewQualityInsightsHandler(db)
	r := gin.New()
	r.GET("/projects/:id/quality-insights/overview", h.GetOverview)

	req, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/quality-insights/overview", nil)
	resp := httptest.NewRecorder()
	r.ServeHTTP(resp, req)

	if resp.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", resp.Code, resp.Body.String())
	}
	for _, fragment := range []string{`"issuePool"`, `"regression"`, `"sourceBreakdowns"`, `"moduleHotspots"`} {
		if !strings.Contains(resp.Body.String(), fragment) {
			t.Fatalf("expected response to contain %s, got %s", fragment, resp.Body.String())
		}
	}
}
