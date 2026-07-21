package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestDefectHandler_ListDefects_SupportsCSVFilters(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "defect_csv_user")
	d1 := testutil.CreateTestDefect(t, db, "csv-filter-a", user.ID)
	d2 := testutil.CreateTestDefect(t, db, "csv-filter-b", user.ID)
	d3 := testutil.CreateTestDefect(t, db, "csv-filter-c", user.ID)

	if err := db.Model(&model.Defect{}).Where("id = ?", d1.ID).Updates(map[string]interface{}{
		"status":   model.DefectStatusPendingAssign,
		"severity": model.SeverityMajor,
	}).Error; err != nil {
		t.Fatalf("update defect1 failed: %v", err)
	}
	if err := db.Model(&model.Defect{}).Where("id = ?", d2.ID).Updates(map[string]interface{}{
		"status":   model.DefectStatusFixing,
		"severity": model.SeverityFatal,
	}).Error; err != nil {
		t.Fatalf("update defect2 failed: %v", err)
	}
	if err := db.Model(&model.Defect{}).Where("id = ?", d3.ID).Updates(map[string]interface{}{
		"status":   model.DefectStatusCompleted,
		"severity": model.SeverityMinor,
	}).Error; err != nil {
		t.Fatalf("update defect3 failed: %v", err)
	}

	h := NewDefectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.GET("/defects", h.ListDefects)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(
		"GET",
		"/defects?status=pending_assign,fixing&severity=major,fatal&page=1&size=20",
		nil,
	)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response failed: %v", err)
	}

	data, ok := resp["data"].(map[string]interface{})
	if !ok {
		t.Fatalf("unexpected response data: %s", w.Body.String())
	}
	items, ok := data["list"].([]interface{})
	if !ok {
		t.Fatalf("unexpected list data: %s", w.Body.String())
	}
	if len(items) != 2 {
		t.Fatalf("expected 2 defects after csv filter, got %d, body=%s", len(items), w.Body.String())
	}
}

func TestDefectHandler_ListDefects_FiltersByProjectID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "defect_project_filter_user")
	d1 := testutil.CreateTestDefect(t, db, "project-filter-a", user.ID)
	d2 := testutil.CreateTestDefect(t, db, "project-filter-b", user.ID)

	var iter1, iter2 model.Iteration
	if err := db.First(&iter1, d1.IterationID).Error; err != nil {
		t.Fatalf("load iteration1 failed: %v", err)
	}
	if err := db.First(&iter2, d2.IterationID).Error; err != nil {
		t.Fatalf("load iteration2 failed: %v", err)
	}
	if iter1.ProjectID == iter2.ProjectID {
		t.Fatalf("expected different project IDs for test defects, got same=%d", iter1.ProjectID)
	}

	h := NewDefectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.GET("/defects", h.ListDefects)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/defects?projectId="+strconv.FormatUint(uint64(iter1.ProjectID), 10), nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp struct {
		Data struct {
			List []struct {
				ID uint `json:"id"`
			} `json:"list"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response failed: %v", err)
	}
	if len(resp.Data.List) != 1 {
		t.Fatalf("expected 1 defect after project filter, got %d, body=%s", len(resp.Data.List), w.Body.String())
	}
	if resp.Data.List[0].ID != d1.ID {
		t.Fatalf("expected defect id=%d, got %d", d1.ID, resp.Data.List[0].ID)
	}
}
