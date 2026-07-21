package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"bug-agent/internal/model"
)

func TestAICatalogHandler_CreateAndListProviders(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	h := NewAICatalogHandler(model.DB)
	r.POST("/providers", h.CreateProvider)
	r.GET("/providers", h.ListProviders)

	body := `{"providerKey":"openai","displayName":"OpenAI","defaultEndpoint":"https://api.openai.com/v1","status":"active","sortOrder":1}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/providers", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected status 201, got %d: %s", w.Code, w.Body.String())
	}

	listW := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/providers", nil)
	r.ServeHTTP(listW, listReq)
	if listW.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", listW.Code, listW.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(listW.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	if len(data) != 1 {
		t.Fatalf("expected 1 provider, got %d", len(data))
	}
	item := data[0].(map[string]interface{})
	if item["providerKey"].(string) != "openai" {
		t.Fatalf("expected providerKey openai, got %v", item["providerKey"])
	}
}

func TestAICatalogHandler_CreateModelRequiresExistingProvider(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	h := NewAICatalogHandler(model.DB)
	r.POST("/models", h.CreateModel)

	body := `{"providerKey":"openai","modelName":"gpt-5.4","status":"active"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/models", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestAICatalogHandler_CreateAndListModels(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	h := NewAICatalogHandler(model.DB)
	r.POST("/providers", h.CreateProvider)
	r.POST("/models", h.CreateModel)
	r.GET("/models", h.ListModels)

	createProviderBody := `{"providerKey":"openai","displayName":"OpenAI","defaultEndpoint":"https://api.openai.com/v1","status":"active"}`
	pw := httptest.NewRecorder()
	preq, _ := http.NewRequest(http.MethodPost, "/providers", bytes.NewBufferString(createProviderBody))
	preq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(pw, preq)
	if pw.Code != http.StatusCreated {
		t.Fatalf("create provider failed: %d %s", pw.Code, pw.Body.String())
	}

	createModelBody := `{"providerKey":"openai","modelName":"gpt-5.4","status":"active","isDefault":true}`
	mw := httptest.NewRecorder()
	mreq, _ := http.NewRequest(http.MethodPost, "/models", bytes.NewBufferString(createModelBody))
	mreq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(mw, mreq)
	if mw.Code != http.StatusCreated {
		t.Fatalf("create model failed: %d %s", mw.Code, mw.Body.String())
	}

	lw := httptest.NewRecorder()
	lreq, _ := http.NewRequest(http.MethodGet, "/models?providerKey=openai", nil)
	r.ServeHTTP(lw, lreq)
	if lw.Code != http.StatusOK {
		t.Fatalf("list model failed: %d %s", lw.Code, lw.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(lw.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	if len(data) != 1 {
		t.Fatalf("expected 1 model, got %d", len(data))
	}
	item := data[0].(map[string]interface{})
	if item["modelName"].(string) != "gpt-5.4" {
		t.Fatalf("expected model gpt-5.4, got %v", item["modelName"])
	}
}

func TestAICatalogHandler_DeleteModelAndProvider(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	h := NewAICatalogHandler(model.DB)
	r.POST("/providers", h.CreateProvider)
	r.POST("/models", h.CreateModel)
	r.DELETE("/providers/:id", h.DeleteProvider)
	r.DELETE("/models/:id", h.DeleteModel)
	r.GET("/providers", h.ListProviders)
	r.GET("/models", h.ListModels)

	createProviderBody := `{"providerKey":"dashscope","displayName":"DashScope","status":"active"}`
	pw := httptest.NewRecorder()
	preq, _ := http.NewRequest(http.MethodPost, "/providers", bytes.NewBufferString(createProviderBody))
	preq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(pw, preq)
	if pw.Code != http.StatusCreated {
		t.Fatalf("create provider failed: %d %s", pw.Code, pw.Body.String())
	}
	var providerResp map[string]interface{}
	_ = json.Unmarshal(pw.Body.Bytes(), &providerResp)
	providerID := int(providerResp["data"].(map[string]interface{})["id"].(float64))

	createModelBody := `{"providerKey":"dashscope","modelName":"qwen-max-latest","status":"active"}`
	mw := httptest.NewRecorder()
	mreq, _ := http.NewRequest(http.MethodPost, "/models", bytes.NewBufferString(createModelBody))
	mreq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(mw, mreq)
	if mw.Code != http.StatusCreated {
		t.Fatalf("create model failed: %d %s", mw.Code, mw.Body.String())
	}
	var modelResp map[string]interface{}
	_ = json.Unmarshal(mw.Body.Bytes(), &modelResp)
	modelID := int(modelResp["data"].(map[string]interface{})["id"].(float64))

	// provider cannot be deleted before models are removed
	dpw := httptest.NewRecorder()
	dpreq, _ := http.NewRequest(http.MethodDelete, "/providers/"+strconv.Itoa(providerID), nil)
	r.ServeHTTP(dpw, dpreq)
	if dpw.Code != http.StatusBadRequest {
		t.Fatalf("expected provider delete 400 when model exists, got %d: %s", dpw.Code, dpw.Body.String())
	}

	dmw := httptest.NewRecorder()
	dmreq, _ := http.NewRequest(http.MethodDelete, "/models/"+strconv.Itoa(modelID), nil)
	r.ServeHTTP(dmw, dmreq)
	if dmw.Code != http.StatusOK {
		t.Fatalf("delete model failed: %d %s", dmw.Code, dmw.Body.String())
	}

	dpw2 := httptest.NewRecorder()
	dpreq2, _ := http.NewRequest(http.MethodDelete, "/providers/"+strconv.Itoa(providerID), nil)
	r.ServeHTTP(dpw2, dpreq2)
	if dpw2.Code != http.StatusOK {
		t.Fatalf("delete provider failed: %d %s", dpw2.Code, dpw2.Body.String())
	}
}

func TestAICatalogHandler_TestModelAvailability_OpenAICompatible(t *testing.T) {
	r, _ := setupAIProviderTestRouter(t)

	upstreamCalled := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		upstreamCalled = true
		if req.Method != http.MethodPost {
			t.Fatalf("expected POST, got %s", req.Method)
		}
		if req.URL.Path != "/chat/completions" {
			t.Fatalf("unexpected path: %s", req.URL.Path)
		}
		if req.Header.Get("Authorization") != "Bearer test-key" {
			t.Fatalf("unexpected auth header: %s", req.Header.Get("Authorization"))
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"chatcmpl-1","choices":[{"message":{"role":"assistant","content":"pong"}}]}`))
	}))
	defer upstream.Close()

	h := NewAICatalogHandler(model.DB)
	r.POST("/providers", h.CreateProvider)
	r.POST("/models", h.CreateModel)
	r.POST("/models/:id/test", h.TestModelAvailability)

	providerBody := `{"providerKey":"openai","displayName":"OpenAI","defaultEndpoint":"` + upstream.URL + `","status":"active"}`
	pw := httptest.NewRecorder()
	preq, _ := http.NewRequest(http.MethodPost, "/providers", bytes.NewBufferString(providerBody))
	preq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(pw, preq)
	if pw.Code != http.StatusCreated {
		t.Fatalf("create provider failed: %d %s", pw.Code, pw.Body.String())
	}

	modelBody := `{"providerKey":"openai","modelName":"gpt-5.4","status":"active"}`
	mw := httptest.NewRecorder()
	mreq, _ := http.NewRequest(http.MethodPost, "/models", bytes.NewBufferString(modelBody))
	mreq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(mw, mreq)
	if mw.Code != http.StatusCreated {
		t.Fatalf("create model failed: %d %s", mw.Code, mw.Body.String())
	}

	var modelResp map[string]interface{}
	_ = json.Unmarshal(mw.Body.Bytes(), &modelResp)
	modelID := int(modelResp["data"].(map[string]interface{})["id"].(float64))

	testBody := `{"apiKey":"test-key"}`
	tw := httptest.NewRecorder()
	treq, _ := http.NewRequest(http.MethodPost, "/models/"+strconv.Itoa(modelID)+"/test", bytes.NewBufferString(testBody))
	treq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(tw, treq)
	if tw.Code != http.StatusOK {
		t.Fatalf("test model failed: %d %s", tw.Code, tw.Body.String())
	}
	if !upstreamCalled {
		t.Fatal("expected upstream model test request")
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(tw.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if success, ok := data["success"].(bool); !ok || !success {
		t.Fatalf("expected success=true, got %#v", data["success"])
	}
	if data["latencyMs"] == nil {
		t.Fatalf("expected latencyMs in response")
	}
}
