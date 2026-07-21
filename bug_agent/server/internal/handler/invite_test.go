package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func setupInviteTestRouter(t testing.TB) (*gin.Engine, uint) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "invite_h_user")

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	return r, user.ID
}

func TestInviteHandler_CreateInvite(t *testing.T) {
	r, _ := setupInviteTestRouter(t)

	h := NewInviteHandler(model.DB)
	r.POST("/invites", h.CreateInvite)

	body := `{"maxUses":5}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["code"] == nil || data["code"].(string) == "" {
		t.Error("Code should be a non-empty string")
	}
	if data["maxUses"].(float64) != 5 {
		t.Errorf("MaxUses should be 5, got %v", data["maxUses"])
	}
}

func TestInviteHandler_CreateUnlimited(t *testing.T) {
	r, _ := setupInviteTestRouter(t)

	h := NewInviteHandler(model.DB)
	r.POST("/invites", h.CreateInvite)

	body := `{}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d", w.Code)
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["maxUses"].(float64) != 0 {
		t.Errorf("Default MaxUses should be 0 (unlimited), got %v", data["maxUses"])
	}
}

func TestInviteHandler_CreateWithExpiry(t *testing.T) {
	r, _ := setupInviteTestRouter(t)

	h := NewInviteHandler(model.DB)
	r.POST("/invites", h.CreateInvite)

	future := time.Now().Add(24 * time.Hour).Format(time.RFC3339)
	body := `{"maxUses":10,"expiresAt":"` + future + `"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d", w.Code)
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["expiresAt"] == nil {
		t.Error("ExpiresAt should be set")
	}
}

func TestInviteHandler_ListInvites(t *testing.T) {
	r, _ := setupInviteTestRouter(t)

	h := NewInviteHandler(model.DB)
	r.POST("/invites", h.CreateInvite)
	r.GET("/invites", h.ListInvites)

	for i := 0; i < 3; i++ {
		body := `{"maxUses":1}`
		wc := httptest.NewRecorder()
		rc, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(body)))
		rc.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(wc, rc)
	}

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/invites", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	if len(data) != 3 {
		t.Errorf("Expected 3 invites, got %d", len(data))
	}
}

func TestInviteHandler_AcceptInvite(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	inviter := testutil.CreateTestUser(t, db, "invite_h_inviter")
	acceptor := testutil.CreateTestUser(t, db, "invite_h_acceptor")

	h := NewInviteHandler(db)
	r := gin.New()

	r.POST("/invites", func(c *gin.Context) { c.Set("userId", inviter.ID); c.Next(); h.CreateInvite(c) })
	r.POST("/invites/:code/accept", func(c *gin.Context) { c.Set("userId", acceptor.ID); c.Next(); h.AcceptInvite(c) })

	body := `{"maxUses":1}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(body)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	var cr map[string]interface{}
	json.Unmarshal(wc.Body.Bytes(), &cr)
	code := cr["data"].(map[string]interface{})["code"].(string)

	wa := httptest.NewRecorder()
	ra, _ := http.NewRequest("POST", "/invites/"+code+"/accept", nil)
	r.ServeHTTP(wa, ra)

	if wa.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", wa.Code, wa.Body.String())
	}
}

func TestInviteHandler_AcceptExpired(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "invite_h_exp")

	h := NewInviteHandler(db)
	r := gin.New()
	r.POST("/invites", func(c *gin.Context) { c.Set("userId", user.ID); c.Next(); h.CreateInvite(c) })
	r.POST("/invites/:code/accept", func(c *gin.Context) { c.Set("userId", user.ID); c.Next(); h.AcceptInvite(c) })

	past := time.Now().Add(-1 * time.Hour).Format(time.RFC3339)
	body := `{"maxUses":1,"expiresAt":"` + past + `"}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(body)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	var cr map[string]interface{}
	json.Unmarshal(wc.Body.Bytes(), &cr)
	code := cr["data"].(map[string]interface{})["code"].(string)

	wa := httptest.NewRecorder()
	ra, _ := http.NewRequest("POST", "/invites/"+code+"/accept", nil)
	r.ServeHTTP(wa, ra)

	if wa.Code != 400 {
		t.Errorf("Expected 400 for expired code, got %d", wa.Code)
	}
}

func TestInviteHandler_ValidateInvite(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "invite_h_val")

	h := NewInviteHandler(db)
	r := gin.New()
	r.POST("/invites", func(c *gin.Context) { c.Set("userId", user.ID); c.Next(); h.CreateInvite(c) })
	r.GET("/invites/:code/validate", h.ValidateInvite)

	body := `{}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(body)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	var cr map[string]interface{}
	json.Unmarshal(wc.Body.Bytes(), &cr)
	code := cr["data"].(map[string]interface{})["code"].(string)

	wv := httptest.NewRecorder()
	rv, _ := http.NewRequest("GET", "/invites/"+code+"/validate", nil)
	r.ServeHTTP(wv, rv)

	if wv.Code != 200 {
		t.Fatalf("Expected 200 for valid code, got %d: %s", wv.Code, wv.Body.String())
	}
}

func TestInviteHandler_ValidateNonexistent(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	testutil.CreateTestUser(t, db, "invite_h_vne")

	h := NewInviteHandler(db)
	r := gin.New()
	r.GET("/invites/:code/validate", h.ValidateInvite)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/invites/nonexistent_code_1234567890abcdef/validate", nil)
	r.ServeHTTP(w, req)

	if w.Code != 404 {
		t.Errorf("Expected 404 for nonexistent code, got %d", w.Code)
	}
}

func TestInviteHandler_AcceptInvite_RegisterByCode(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	inviter := testutil.CreateTestUser(t, db, "invite_h_reg_inviter")

	h := NewInviteHandler(db)
	r := gin.New()
	r.POST("/invites", func(c *gin.Context) { c.Set("userId", inviter.ID); c.Next(); h.CreateInvite(c) })
	r.POST("/invites/:code/accept", h.AcceptInvite)

	createBody := `{"maxUses":1}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", "/invites", bytes.NewReader([]byte(createBody)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	var cr map[string]interface{}
	json.Unmarshal(wc.Body.Bytes(), &cr)
	code := cr["data"].(map[string]interface{})["code"].(string)

	acceptBody := `{"username":"invite_new_user","email":"invite_new_user@test.com","password":"123456","nickname":"Invite New User"}`
	wa := httptest.NewRecorder()
	ra, _ := http.NewRequest("POST", "/invites/"+code+"/accept", bytes.NewReader([]byte(acceptBody)))
	ra.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wa, ra)

	if wa.Code != 201 {
		t.Fatalf("Expected 201 for invite registration, got %d: %s", wa.Code, wa.Body.String())
	}

	var created model.User
	if err := db.Where("username = ?", "invite_new_user").First(&created).Error; err != nil {
		t.Fatalf("Expected new user to be created, err=%v", err)
	}
	if created.InvitedBy == nil || *created.InvitedBy != inviter.ID {
		t.Fatalf("Expected invited_by=%d, got %v", inviter.ID, created.InvitedBy)
	}
}
