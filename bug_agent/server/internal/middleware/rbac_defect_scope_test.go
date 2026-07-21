package middleware

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestRequireDefectListPermission_ProjectScope(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	InitRBAC(db)

	user := testutil.CreateTestUser(t, db, "defect_scope_user")
	p1 := testutil.CreateTestProject(t, db, "ScopeP1", "SCP1")
	p2 := testutil.CreateTestProject(t, db, "ScopeP2", "SCP2")

	if err := db.Create(&model.ProjectMember{ProjectID: p1.ID, UserID: user.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create member failed: %v", err)
	}

	i1 := model.Iteration{
		ProjectID: p1.ID,
		Name:      "S1",
		Status:    "active",
		StartDate: time.Now(),
		EndDate:   time.Now().Add(24 * time.Hour),
	}
	if err := db.Create(&i1).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	r.GET("/defects", RequireDefectListPermission("defects:read"), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	t.Run("allow own project", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, "/defects?projectId="+toStr(p1.ID), nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
		}
	})

	t.Run("allow own iteration", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, "/defects?iterationId="+toStr(i1.ID), nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
		}
	})

	t.Run("deny other project", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, "/defects?projectId="+toStr(p2.ID), nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusForbidden {
			t.Fatalf("expected 403, got %d body=%s", w.Code, w.Body.String())
		}
	})
}

func TestRequireDefectCreatePermission_ProjectScope(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	InitRBAC(db)

	user := testutil.CreateTestUser(t, db, "defect_create_scope_user")
	p1 := testutil.CreateTestProject(t, db, "CreateScopeP1", "CSP1")
	p2 := testutil.CreateTestProject(t, db, "CreateScopeP2", "CSP2")

	if err := db.Create(&model.ProjectMember{ProjectID: p1.ID, UserID: user.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create member failed: %v", err)
	}

	i1 := model.Iteration{
		ProjectID: p1.ID,
		Name:      "S1",
		Status:    "active",
		StartDate: time.Now(),
		EndDate:   time.Now().Add(24 * time.Hour),
	}
	if err := db.Create(&i1).Error; err != nil {
		t.Fatalf("create iteration1 failed: %v", err)
	}
	i2 := model.Iteration{
		ProjectID: p2.ID,
		Name:      "S2",
		Status:    "active",
		StartDate: time.Now(),
		EndDate:   time.Now().Add(24 * time.Hour),
	}
	if err := db.Create(&i2).Error; err != nil {
		t.Fatalf("create iteration2 failed: %v", err)
	}

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	r.POST("/defects", RequireDefectCreatePermission("defects:create"), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	post := func(iterationID uint) *httptest.ResponseRecorder {
		payload := map[string]uint{"iterationId": iterationID}
		body, _ := json.Marshal(payload)
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodPost, "/defects", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(w, req)
		return w
	}

	t.Run("allow own project iteration", func(t *testing.T) {
		w := post(i1.ID)
		if w.Code != http.StatusOK {
			t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
		}
	})

	t.Run("deny other project iteration", func(t *testing.T) {
		w := post(i2.ID)
		if w.Code != http.StatusForbidden {
			t.Fatalf("expected 403, got %d body=%s", w.Code, w.Body.String())
		}
	})

	t.Run("invalid iteration id", func(t *testing.T) {
		w := post(999999)
		if w.Code != http.StatusBadRequest {
			t.Fatalf("expected 400, got %d body=%s", w.Code, w.Body.String())
		}
	})
}

func toStr(v uint) string {
	return strconv.FormatUint(uint64(v), 10)
}
