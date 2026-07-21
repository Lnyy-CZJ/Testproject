package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func setupAIProviderTestRouter(t testing.TB) (*gin.Engine, *model.User) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "ai_user")

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	return r, &user
}

func TestGetAIProviders_Success(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	h := NewProjectAIConfigHandler(model.DB)
	r.GET("/test-providers", h.GetAIProviders)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test-providers", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["code"].(float64) != 0 {
		t.Errorf("Expected code 0, got %v", resp["code"])
	}

	data := resp["data"].([]interface{})
	if len(data) != 1 {
		t.Errorf("Expected 1 provider, got %d", len(data))
	}
	first := data[0].(map[string]interface{})
	if first["value"].(string) != "custom" {
		t.Fatalf("expected only custom provider when catalog empty, got %v", first["value"])
	}
}

func TestGetAIProviders_ResponseFormat(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	h := NewProjectAIConfigHandler(model.DB)
	r.GET("/test-providers", h.GetAIProviders)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test-providers", nil)
	r.ServeHTTP(w, req)

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)

	if resp["code"] == nil {
		t.Error("Response should have 'code' field")
	}
	if resp["data"] == nil {
		t.Error("Response should have 'data' field")
	}

	providers := resp["data"].([]interface{})
	for i, p := range providers {
		prov := p.(map[string]interface{})
		requiredFields := []string{"name", "value", "models"}
		for _, f := range requiredFields {
			if prov[f] == nil {
				t.Errorf("Provider[%d] missing field: %s", i, f)
			}
		}
	}
}

func TestGetAIProviders_UsesCatalogWhenConfigured(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	if err := model.DB.Create(&model.AIProviderCatalog{
		ProviderKey:     "openai",
		DisplayName:     "OpenAI Catalog",
		DefaultEndpoint: "https://api.openai.com/v1",
		Status:          "active",
		SortOrder:       1,
	}).Error; err != nil {
		t.Fatalf("seed provider failed: %v", err)
	}
	if err := model.DB.Create(&model.AIModelCatalog{
		ProviderKey: "openai",
		ModelName:   "gpt-5.4",
		Status:      "active",
		IsDefault:   true,
		SortOrder:   1,
	}).Error; err != nil {
		t.Fatalf("seed model failed: %v", err)
	}

	h := NewProjectAIConfigHandler(model.DB)
	r.GET("/test-providers", h.GetAIProviders)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test-providers", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})

	if len(data) != 2 {
		t.Fatalf("Expected 2 providers (catalog + custom), got %d", len(data))
	}

	first := data[0].(map[string]interface{})
	if first["value"].(string) != "openai" {
		t.Fatalf("expected first provider openai, got %v", first["value"])
	}
	if first["name"].(string) != "OpenAI Catalog" {
		t.Fatalf("expected display name from catalog, got %v", first["name"])
	}

	models := first["models"].([]interface{})
	if len(models) != 1 {
		t.Fatalf("expected 1 model, got %d", len(models))
	}
	firstModel := models[0].(map[string]interface{})
	if firstModel["name"].(string) != "gpt-5.4" {
		t.Fatalf("unexpected model name: %v", firstModel["name"])
	}
	if firstModel["endpoint"].(string) != "https://api.openai.com/v1" {
		t.Fatalf("expected endpoint fallback from provider, got %v", firstModel["endpoint"])
	}

	last := data[len(data)-1].(map[string]interface{})
	if last["value"].(string) != "custom" {
		t.Fatalf("expected custom option appended, got %v", last["value"])
	}
}

func TestGetAIProviders_ExcludesInactiveCatalogEntries(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	if err := model.DB.Create(&model.AIProviderCatalog{
		ProviderKey:     "openai",
		DisplayName:     "OpenAI",
		DefaultEndpoint: "https://api.openai.com/v1",
		Status:          "active",
		SortOrder:       1,
	}).Error; err != nil {
		t.Fatalf("seed provider failed: %v", err)
	}
	if err := model.DB.Create(&model.AIProviderCatalog{
		ProviderKey:     "anthropic",
		DisplayName:     "Anthropic",
		DefaultEndpoint: "https://api.anthropic.com",
		Status:          "inactive",
		SortOrder:       2,
	}).Error; err != nil {
		t.Fatalf("seed provider failed: %v", err)
	}
	if err := model.DB.Create(&model.AIModelCatalog{
		ProviderKey: "openai",
		ModelName:   "gpt-5.4",
		Status:      "inactive",
		SortOrder:   1,
	}).Error; err != nil {
		t.Fatalf("seed model failed: %v", err)
	}
	if err := model.DB.Create(&model.AIModelCatalog{
		ProviderKey: "openai",
		ModelName:   "gpt-5.4-mini",
		Status:      "active",
		SortOrder:   2,
	}).Error; err != nil {
		t.Fatalf("seed model failed: %v", err)
	}

	h := NewProjectAIConfigHandler(model.DB)
	r.GET("/test-providers", h.GetAIProviders)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test-providers", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	if len(data) != 2 {
		t.Fatalf("expected active provider + custom, got %d", len(data))
	}

	first := data[0].(map[string]interface{})
	if first["value"].(string) != "openai" {
		t.Fatalf("expected openai provider first, got %v", first["value"])
	}
	models := first["models"].([]interface{})
	if len(models) != 1 {
		t.Fatalf("expected only active model, got %d", len(models))
	}
	if models[0].(map[string]interface{})["name"].(string) != "gpt-5.4-mini" {
		t.Fatalf("unexpected model payload: %v", models[0])
	}
}
