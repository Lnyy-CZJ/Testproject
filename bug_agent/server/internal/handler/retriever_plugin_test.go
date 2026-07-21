package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/adk"
	"bug-agent/internal/model"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func setupRetrieverPluginTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	assert.NoError(t, err)
	err = db.AutoMigrate(
		&model.RetrieverPlugin{},
		&model.Project{},
		&model.User{},
	)
	assert.NoError(t, err)
	return db
}

func setupRetrieverPluginRouter(db *gorm.DB) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	return r
}

func createRetrieverPluginFixtures(db *gorm.DB, projectID uint) []model.RetrieverPlugin {
	plugins := []model.RetrieverPlugin{
		{ProjectID: projectID, Name: "keyword", DisplayName: "Keyword Search", Config: "{}", Enabled: true, SortOrder: 0, IsBuiltIn: true},
		{ProjectID: projectID, Name: "rag", DisplayName: "RAG Retriever", Config: `{"endpoint":"http://localhost"}`, Enabled: false, SortOrder: 1, IsBuiltIn: true},
		{ProjectID: projectID, Name: "custom", DisplayName: "Custom Plugin", Description: "A custom plugin", Config: "{}", Enabled: true, SortOrder: 2, IsBuiltIn: false},
	}
	for i := range plugins {
		db.Create(&plugins[i])
	}
	return plugins
}

func TestRetrieverPluginHandler_ListEmpty(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP"}
	db.Create(project)

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.GET("/projects/:id/retriever-plugins", h.List)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("/projects/%d/retriever-plugins", project.ID), nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	assert.Equal(t, 0, len(data))
}

func TestRetrieverPluginHandler_ListWithData(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP2"}
	db.Create(project)
	createRetrieverPluginFixtures(db, project.ID)

	adk.InitRegistry()

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.GET("/projects/:id/retriever-plugins", h.List)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("/projects/%d/retriever-plugins", project.ID), nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	assert.Equal(t, 3, len(data))

	first := data[0].(map[string]interface{})
	assert.Equal(t, "keyword", first["name"])
	assert.Equal(t, float64(0), first["sortOrder"])
	assert.NotNil(t, first["configSchema"])

	second := data[1].(map[string]interface{})
	assert.Equal(t, "rag", second["name"])
	schema := second["configSchema"].(map[string]interface{})
	properties := schema["properties"].(map[string]interface{})
	assert.Contains(t, properties, "endpoint")
}

func TestRetrieverPluginHandler_UpdateConfig(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP3"}
	db.Create(project)
	plugins := createRetrieverPluginFixtures(db, project.ID)

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.PUT("/projects/:id/retriever-plugins/:pluginId", h.Update)

	body := `{"config":"{\"endpoint\":\"http://new-host:9090\"}","displayName":"Updated RAG"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPut,
		fmt.Sprintf("/projects/%d/retriever-plugins/%d", project.ID, plugins[1].ID),
		bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	assert.Equal(t, `{"endpoint":"http://new-host:9090"}`, data["config"])
	assert.Equal(t, "Updated RAG", data["displayName"])
}

func TestRetrieverPluginHandler_UpdateNotFound(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP4"}
	db.Create(project)

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.PUT("/projects/:id/retriever-plugins/:pluginId", h.Update)

	body := `{"config":"{}"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPut,
		fmt.Sprintf("/projects/%d/retriever-plugins/9999", project.ID),
		bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, 404, w.Code)
}

func TestRetrieverPluginHandler_Toggle(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP5"}
	db.Create(project)
	plugins := createRetrieverPluginFixtures(db, project.ID)

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.PATCH("/projects/:id/retriever-plugins/:pluginId/toggle", h.Toggle)

	assert.True(t, plugins[0].Enabled)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPatch,
		fmt.Sprintf("/projects/%d/retriever-plugins/%d/toggle", project.ID, plugins[0].ID), nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	assert.Equal(t, false, data["enabled"])
}

func TestRetrieverPluginHandler_ToggleNotFound(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP6"}
	db.Create(project)

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.PATCH("/projects/:id/retriever-plugins/:pluginId/toggle", h.Toggle)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPatch,
		fmt.Sprintf("/projects/%d/retriever-plugins/9999/toggle", project.ID), nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 404, w.Code)
}

func TestRetrieverPluginHandler_BatchSort(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP7"}
	db.Create(project)
	plugins := createRetrieverPluginFixtures(db, project.ID)

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.PUT("/projects/:id/retriever-plugins/sort", h.BatchSort)

	body := fmt.Sprintf(`{"items":[{"id":%d,"sortOrder":2},{"id":%d,"sortOrder":0},{"id":%d,"sortOrder":1}]}`,
		plugins[0].ID, plugins[1].ID, plugins[2].ID)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPut,
		fmt.Sprintf("/projects/%d/retriever-plugins/sort", project.ID),
		bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var updated []model.RetrieverPlugin
	db.Where("project_id = ?", project.ID).Order("sort_order ASC").Find(&updated)
	assert.Equal(t, 0, updated[0].SortOrder)
	assert.Equal(t, 1, updated[1].SortOrder)
	assert.Equal(t, 2, updated[2].SortOrder)
	assert.Equal(t, "rag", updated[0].Name)
	assert.Equal(t, "custom", updated[1].Name)
	assert.Equal(t, "keyword", updated[2].Name)
}

func TestRetrieverPluginHandler_TestKeywordAlwaysSucceeds(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP8"}
	db.Create(project)
	plugins := createRetrieverPluginFixtures(db, project.ID)

	adk.GlobalRegistry = nil

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.POST("/projects/:id/retriever-plugins/:pluginId/test", h.Test)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost,
		fmt.Sprintf("/projects/%d/retriever-plugins/%d/test", project.ID, plugins[0].ID), nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	assert.Equal(t, true, data["connected"])
}

func TestRetrieverPluginHandler_TestUnregisteredPlugin(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP9"}
	db.Create(project)
	plugins := createRetrieverPluginFixtures(db, project.ID)

	adk.GlobalRegistry = nil

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.POST("/projects/:id/retriever-plugins/:pluginId/test", h.Test)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost,
		fmt.Sprintf("/projects/%d/retriever-plugins/%d/test", project.ID, plugins[1].ID), nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	assert.Equal(t, false, data["connected"])
}

func TestRetrieverPluginHandler_TestWithRegistry(t *testing.T) {
	db := setupRetrieverPluginTestDB(t)
	project := &model.Project{Name: "test-project", Code: "TP10"}
	db.Create(project)
	plugins := createRetrieverPluginFixtures(db, project.ID)

	adk.InitRegistry()

	h := NewRetrieverPluginHandler(db)
	r := setupRetrieverPluginRouter(db)
	r.POST("/projects/:id/retriever-plugins/:pluginId/test", h.Test)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost,
		fmt.Sprintf("/projects/%d/retriever-plugins/%d/test", project.ID, plugins[1].ID), nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	assert.Equal(t, true, data["connected"])
}
