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

func TestRegressionPreventionHandler_CreateListAndUpdate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	operator := testutil.CreateTestUser(t, db, "regression_handler_operator")
	owner := testutil.CreateTestUser(t, db, "regression_handler_owner")
	project := testutil.CreateTestProject(t, db, "Regression Handler Project", "RGH")
	_, _, cluster := seedIssueClusterForProject(t, db, project.ID, "regression_handler_seed")
	if err := db.Model(&model.IssueCluster{}).Where("id = ?", cluster.ID).Update("owner_user_id", owner.ID).Error; err != nil {
		t.Fatalf("assign cluster owner failed: %v", err)
	}

	triageSvc := service.NewSignalTriageService(db)
	if _, _, err := triageSvc.ConvertCluster(project.ID, cluster.ID, operator.ID); err != nil {
		t.Fatalf("convert cluster failed: %v", err)
	}

	h := NewRegressionPreventionHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", operator.ID)
		c.Next()
	})
	r.GET("/projects/:id/regression-items", h.ListItems)
	r.POST("/projects/:id/issue-clusters/:clusterId/regression-items", h.CreateFromCluster)
	r.PUT("/projects/:id/regression-items/:itemId", h.UpdateItem)

	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(cluster.ID)+"/regression-items", bytes.NewBufferString(`{}`))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected create 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	itemID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	listResp := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/regression-items", nil)
	r.ServeHTTP(listResp, listReq)
	if listResp.Code != http.StatusOK {
		t.Fatalf("expected list 200, got %d: %s", listResp.Code, listResp.Body.String())
	}
	if !bytes.Contains(listResp.Body.Bytes(), []byte(`"sourceFingerprint":"fp-regression_handler_seed"`)) {
		t.Fatalf("expected source fingerprint in response, got %s", listResp.Body.String())
	}

	updateResp := httptest.NewRecorder()
	updateReq, _ := http.NewRequest(http.MethodPut, "/projects/"+toStrUint(project.ID)+"/regression-items/"+toStrUint(itemID), bytes.NewBufferString(`{"status":"verified"}`))
	updateReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(updateResp, updateReq)
	if updateResp.Code != http.StatusOK {
		t.Fatalf("expected update 200, got %d: %s", updateResp.Code, updateResp.Body.String())
	}
	if !bytes.Contains(updateResp.Body.Bytes(), []byte(`"status":"verified"`)) {
		t.Fatalf("expected verified status in response, got %s", updateResp.Body.String())
	}
	if !bytes.Contains(updateResp.Body.Bytes(), []byte(`"lastVerifiedAt"`)) {
		t.Fatalf("expected lastVerifiedAt in response, got %s", updateResp.Body.String())
	}
}
