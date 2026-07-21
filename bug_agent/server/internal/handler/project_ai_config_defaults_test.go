package handler

import (
	"bug-agent/internal/model"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestProjectAIConfigHandler_CreateFirstConfigBecomesDefault(t *testing.T) {
	r, user := setupAIProviderTestRouter(t)
	_ = user
	project := model.Project{Name: "AI Project", Code: "AIPROJ"}
	if err := model.DB.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}

	h := NewProjectAIConfigHandler(model.DB)
	r.POST("/projects/:id/ai-configs", h.CreateAIConfig)

	body, _ := json.Marshal(map[string]any{
		"provider":  "openai",
		"modelName": "gpt-5.4-mini",
		"apiKey":    "sk-test",
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/projects/"+jsonNumber(project.ID)+"/ai-configs", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d: %s", w.Code, w.Body.String())
	}

	var config model.ProjectAIConfig
	if err := model.DB.Where("project_id = ?", project.ID).First(&config).Error; err != nil {
		t.Fatalf("load config failed: %v", err)
	}
	if !config.IsDefault {
		t.Fatalf("expected first config to become default")
	}
}

func TestProjectAIConfigHandler_DeleteDefaultPromotesLatestRemainingConfig(t *testing.T) {
	r, user := setupAIProviderTestRouter(t)
	_ = user
	project := model.Project{Name: "AI Delete Project", Code: "AIDEL"}
	if err := model.DB.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}

	h := NewProjectAIConfigHandler(model.DB)
	r.DELETE("/projects/:id/ai-configs/:configId", h.DeleteAIConfig)

	configs := []model.ProjectAIConfig{
		{ProjectID: project.ID, Provider: "openai", ModelName: "gpt-4.1", APIKey: "cipher-1", IsDefault: true},
		{ProjectID: project.ID, Provider: "openai", ModelName: "gpt-5.4-mini", APIKey: "cipher-2", IsDefault: false},
	}
	if err := model.DB.Create(&configs).Error; err != nil {
		t.Fatalf("seed configs failed: %v", err)
	}

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodDelete, "/projects/"+jsonNumber(project.ID)+"/ai-configs/"+jsonNumber(configs[0].ID), nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var remain model.ProjectAIConfig
	if err := model.DB.First(&remain, configs[1].ID).Error; err != nil {
		t.Fatalf("reload remaining config failed: %v", err)
	}
	if !remain.IsDefault {
		t.Fatalf("expected remaining config to be promoted as default")
	}
}

func jsonNumber(v uint) string {
	b, _ := json.Marshal(v)
	return string(b)
}
