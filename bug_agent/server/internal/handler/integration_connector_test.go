package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestIntegrationConnectorHandler_CRUDAndSyncRecords(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	admin := testutil.CreateTestUser(t, db, "connector_admin")
	project := testutil.CreateTestProject(t, db, "Connector Project", "CNPRJ")
	mockBugly := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/issues" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"items":[]}`))
	}))
	defer mockBugly.Close()

	h := NewIntegrationConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.GET("/projects/:id/integrations", h.List)
	r.POST("/projects/:id/integrations", h.Create)
	r.PUT("/projects/:id/integrations/:connectorId", h.Update)
	r.POST("/projects/:id/integrations/:connectorId/test", h.Test)
	r.POST("/projects/:id/integrations/:connectorId/sync", h.Sync)
	r.GET("/projects/:id/integrations/:connectorId/sync-records", h.ListSyncRecords)
	r.DELETE("/projects/:id/integrations/:connectorId", h.Delete)

	createBody := `{"name":"Bugly 主连接器","type":"bugly","status":"active","config":{"appId":"demo-app","appKey":"demo-key"}}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)

	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	connectorID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	listResp := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/integrations", nil)
	r.ServeHTTP(listResp, listReq)
	if listResp.Code != http.StatusOK {
		t.Fatalf("expected list 200, got %d: %s", listResp.Code, listResp.Body.String())
	}

	updateBody := `{"name":"Bugly 主连接器-更新","status":"active","config":{"appId":"demo-app","appKey":"demo-key","endpoint":"` + mockBugly.URL + `","issuesPath":"/issues"}}`
	updateResp := httptest.NewRecorder()
	updateReq, _ := http.NewRequest(http.MethodPut, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID), bytes.NewBufferString(updateBody))
	updateReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(updateResp, updateReq)
	if updateResp.Code != http.StatusOK {
		t.Fatalf("expected update 200, got %d: %s", updateResp.Code, updateResp.Body.String())
	}

	testResp := httptest.NewRecorder()
	testReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/test", bytes.NewBufferString(`{}`))
	testReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(testResp, testReq)
	if testResp.Code != http.StatusOK {
		t.Fatalf("expected test 200, got %d: %s", testResp.Code, testResp.Body.String())
	}

	syncResp := httptest.NewRecorder()
	syncReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync", bytes.NewBufferString(`{"items":[{"eventId":"evt-b1","title":"线上闪退","description":"来自手动同步","fingerprint":"bugly-fp","platform":"android"}]}`))
	syncReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(syncResp, syncReq)
	if syncResp.Code != http.StatusOK {
		t.Fatalf("expected sync 200, got %d: %s", syncResp.Code, syncResp.Body.String())
	}

	recordsResp := httptest.NewRecorder()
	recordsReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync-records", nil)
	r.ServeHTTP(recordsResp, recordsReq)
	if recordsResp.Code != http.StatusOK {
		t.Fatalf("expected sync records 200, got %d: %s", recordsResp.Code, recordsResp.Body.String())
	}

	var recordsPayload map[string]interface{}
	if err := json.Unmarshal(recordsResp.Body.Bytes(), &recordsPayload); err != nil {
		t.Fatalf("unmarshal records payload failed: %v", err)
	}
	records := recordsPayload["data"].([]interface{})
	if len(records) == 0 {
		t.Fatalf("expected sync records to exist")
	}

	deleteResp := httptest.NewRecorder()
	deleteReq, _ := http.NewRequest(http.MethodDelete, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID), nil)
	r.ServeHTTP(deleteResp, deleteReq)
	if deleteResp.Code != http.StatusBadRequest {
		t.Fatalf("expected delete 400 when connector has signals, got %d: %s", deleteResp.Code, deleteResp.Body.String())
	}
}

func TestIntegrationConnectorHandler_DeleteConnectorWithoutSignals(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	admin := testutil.CreateTestUser(t, db, "connector_delete_admin")
	project := testutil.CreateTestProject(t, db, "Connector Delete Project", "CNDEL")

	h := NewIntegrationConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.POST("/projects/:id/integrations", h.Create)
	r.DELETE("/projects/:id/integrations/:connectorId", h.Delete)

	createBody := `{"name":"Webhook 待删连接器","type":"webhook","status":"active","config":{}}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected create 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	connectorID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	deleteResp := httptest.NewRecorder()
	deleteReq, _ := http.NewRequest(http.MethodDelete, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID), nil)
	r.ServeHTTP(deleteResp, deleteReq)
	if deleteResp.Code != http.StatusOK {
		t.Fatalf("expected delete 200, got %d: %s", deleteResp.Code, deleteResp.Body.String())
	}
}

func TestIntegrationConnectorHandler_BuglySyncPullsRemoteIssues(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	admin := testutil.CreateTestUser(t, db, "bugly_connector_admin")
	project := testutil.CreateTestProject(t, db, "Bugly Project", "BGLY")

	mockBugly := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/issues" {
			http.NotFound(w, r)
			return
		}
		if got := r.Header.Get("X-Bugly-App-Id"); got != "demo-app" {
			http.Error(w, "missing app id", http.StatusBadRequest)
			return
		}
		if got := r.Header.Get("X-Bugly-App-Key"); got != "demo-key" {
			http.Error(w, "missing app key", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"items":[{"issueId":"bg-1","title":"启动崩溃","description":"用户打开 App 闪退","platform":"android","appVersion":"1.2.3","crashHash":"fp-start","count":5,"affectedUsers":3},{"issueId":"bg-2","title":"登录白屏","description":"登录成功后白屏","platform":"ios","appVersion":"1.2.4","crashHash":"fp-login","count":2,"affectedUsers":1}]}`))
	}))
	defer mockBugly.Close()

	h := NewIntegrationConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.POST("/projects/:id/integrations", h.Create)
	r.POST("/projects/:id/integrations/:connectorId/sync", h.Sync)
	r.GET("/projects/:id/integrations/:connectorId/sync-records", h.ListSyncRecords)

	createBody := `{"name":"Bugly 线上","type":"bugly","status":"active","config":{"endpoint":"` + mockBugly.URL + `","issuesPath":"/issues","appId":"demo-app","appKey":"demo-key"}}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected create 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	connectorID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	syncResp := httptest.NewRecorder()
	syncReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync", bytes.NewBufferString(`{}`))
	syncReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(syncResp, syncReq)
	if syncResp.Code != http.StatusOK {
		t.Fatalf("expected sync 200, got %d: %s", syncResp.Code, syncResp.Body.String())
	}

	var syncPayload map[string]interface{}
	if err := json.Unmarshal(syncResp.Body.Bytes(), &syncPayload); err != nil {
		t.Fatalf("unmarshal sync payload failed: %v", err)
	}
	data := syncPayload["data"].(map[string]interface{})
	if got := int(data["importedCount"].(float64)); got != 2 {
		t.Fatalf("expected imported count 2, got %d", got)
	}

	var signals []model.IssueSignal
	if err := db.Order("source_event_id asc").Find(&signals).Error; err != nil {
		t.Fatalf("query signals failed: %v", err)
	}
	if len(signals) != 2 {
		t.Fatalf("expected 2 signals, got %d", len(signals))
	}

	recordsResp := httptest.NewRecorder()
	recordsReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync-records", nil)
	r.ServeHTTP(recordsResp, recordsReq)
	if recordsResp.Code != http.StatusOK {
		t.Fatalf("expected records 200, got %d: %s", recordsResp.Code, recordsResp.Body.String())
	}

	var recordsPayload map[string]interface{}
	if err := json.Unmarshal(recordsResp.Body.Bytes(), &recordsPayload); err != nil {
		t.Fatalf("unmarshal records payload failed: %v", err)
	}
	records := recordsPayload["data"].([]interface{})
	if len(records) != 1 {
		t.Fatalf("expected 1 sync record, got %d", len(records))
	}
}

func TestIntegrationConnectorHandler_AliyunLogSyncPullsRemoteLogs(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	admin := testutil.CreateTestUser(t, db, "aliyun_connector_admin")
	project := testutil.CreateTestProject(t, db, "Aliyun Log Project", "ALOG")

	mockAliyun := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if r.URL.Path != "/logstores/mobile-error/logs" {
			http.NotFound(w, r)
			return
		}

		var requestBody map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&requestBody); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if requestBody["query"] != "level:error" {
			http.Error(w, "unexpected query", http.StatusBadRequest)
			return
		}
		if int(requestBody["line"].(float64)) != 2 {
			http.Error(w, "unexpected lines", http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"meta":{
				"progress":"Complete",
				"count":2,
				"hasSQL":false,
				"processedRows":2,
				"processedBytes":256,
				"elapsedMillisecond":1,
				"cpuSec":0,
				"cpuCores":0,
				"powerSql":false,
				"insertedSQL":""
			},
			"data":[
				{
					"event_id":"sls-1",
					"message":"启动页闪退\njava.lang.IllegalStateException: startup boom",
					"stack":"java.lang.IllegalStateException: startup boom\n\tat app.StartupActivity.onCreate(StartupActivity.kt:42)",
					"level":"fatal",
					"app_version":"6.2.1",
					"build_number":"6201001",
					"platform":"android",
					"device_model":"Pixel 8",
					"fingerprint":"aliyun-startup",
					"count":"6",
					"affected_users":"3",
					"__time__":"2026-04-12 09:10:11"
				},
				{
					"event_id":"sls-2",
					"message":"登录页白屏\nrender timeout",
					"stack":"render timeout\n\tat app.LoginActivity.render(LoginActivity.kt:88)",
					"level":"major",
					"app_version":"6.2.2",
					"build_number":"6202001",
					"platform":"android",
					"device_model":"OnePlus 12",
					"fingerprint":"aliyun-login",
					"count":"2",
					"affected_users":"1",
					"__time__":"2026-04-12 09:12:11"
				}
			]
		}`))
	}))
	defer mockAliyun.Close()

	h := NewIntegrationConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.POST("/projects/:id/integrations", h.Create)
	r.POST("/projects/:id/integrations/:connectorId/sync", h.Sync)
	r.GET("/projects/:id/integrations/:connectorId/sync-records", h.ListSyncRecords)

	createBody := `{"name":"阿里云日志 Android","type":"aliyun_log","status":"active","config":{"endpoint":"` + mockAliyun.URL + `","project":"mobile-app","logstore":"mobile-error","query":"level:error","accessKeyId":"demo-ak","accessKeySecret":"demo-sk","lines":2}}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected create 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	connectorID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	syncResp := httptest.NewRecorder()
	syncReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync", bytes.NewBufferString(`{}`))
	syncReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(syncResp, syncReq)
	if syncResp.Code != http.StatusOK {
		t.Fatalf("expected sync 200, got %d: %s", syncResp.Code, syncResp.Body.String())
	}

	var syncPayload map[string]interface{}
	if err := json.Unmarshal(syncResp.Body.Bytes(), &syncPayload); err != nil {
		t.Fatalf("unmarshal sync payload failed: %v", err)
	}
	data := syncPayload["data"].(map[string]interface{})
	if got := int(data["importedCount"].(float64)); got != 2 {
		t.Fatalf("expected imported count 2, got %d", got)
	}

	var signals []model.IssueSignal
	if err := db.Order("source_event_id asc").Find(&signals).Error; err != nil {
		t.Fatalf("query signals failed: %v", err)
	}
	if len(signals) != 2 {
		t.Fatalf("expected 2 signals, got %d", len(signals))
	}
	if signals[0].SourceType != model.ConnectorTypeAliyun {
		t.Fatalf("expected source type aliyun_log, got %q", signals[0].SourceType)
	}
	if !strings.Contains(signals[0].LogExcerpt, "启动页闪退") {
		t.Fatalf("expected first signal log excerpt to contain source message, got %q", signals[0].LogExcerpt)
	}

	recordsResp := httptest.NewRecorder()
	recordsReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync-records", nil)
	r.ServeHTTP(recordsResp, recordsReq)
	if recordsResp.Code != http.StatusOK {
		t.Fatalf("expected records 200, got %d: %s", recordsResp.Code, recordsResp.Body.String())
	}

	var recordsPayload map[string]interface{}
	if err := json.Unmarshal(recordsResp.Body.Bytes(), &recordsPayload); err != nil {
		t.Fatalf("unmarshal records payload failed: %v", err)
	}
	records := recordsPayload["data"].([]interface{})
	if len(records) != 1 {
		t.Fatalf("expected 1 sync record, got %d", len(records))
	}
}


func TestIntegrationConnectorHandler_ProjectScopedCRUDAndSyncRecords(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	admin := testutil.CreateTestUser(t, db, "project_scoped_connector_admin")
	project := testutil.CreateTestProject(t, db, "Project Scoped Connector", "PSC")
	mockBugly := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/issues" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"items":[]}`))
	}))
	defer mockBugly.Close()

	h := NewIntegrationConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.GET("/projects/:id/integrations", h.List)
	r.POST("/projects/:id/integrations", h.Create)
	r.PUT("/projects/:id/integrations/:connectorId", h.Update)
	r.POST("/projects/:id/integrations/:connectorId/test", h.Test)
	r.POST("/projects/:id/integrations/:connectorId/sync", h.Sync)
	r.GET("/projects/:id/integrations/:connectorId/sync-records", h.ListSyncRecords)
	r.DELETE("/projects/:id/integrations/:connectorId", h.Delete)

	createBody := `{"name":"项目内 Bugly 连接器","type":"bugly","status":"active","config":{"appId":"demo-app","appKey":"demo-key"}}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected create 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	data := createPayload["data"].(map[string]interface{})
	connectorID := uint(data["id"].(float64))
	if gotProjectID := uint(data["projectId"].(float64)); gotProjectID != project.ID {
		t.Fatalf("expected project id %d, got %d", project.ID, gotProjectID)
	}

	listResp := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/integrations", nil)
	r.ServeHTTP(listResp, listReq)
	if listResp.Code != http.StatusOK {
		t.Fatalf("expected list 200, got %d: %s", listResp.Code, listResp.Body.String())
	}

	updateBody := `{"name":"项目内 Bugly 连接器-更新","status":"inactive","config":{"appId":"demo-app","appKey":"demo-key","endpoint":"` + mockBugly.URL + `","issuesPath":"/issues"}}`
	updateResp := httptest.NewRecorder()
	updateReq, _ := http.NewRequest(http.MethodPut, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID), bytes.NewBufferString(updateBody))
	updateReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(updateResp, updateReq)
	if updateResp.Code != http.StatusOK {
		t.Fatalf("expected update 200, got %d: %s", updateResp.Code, updateResp.Body.String())
	}

	testResp := httptest.NewRecorder()
	testReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/test", bytes.NewBufferString(`{}`))
	testReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(testResp, testReq)
	if testResp.Code != http.StatusOK {
		t.Fatalf("expected test 200, got %d: %s", testResp.Code, testResp.Body.String())
	}

	syncResp := httptest.NewRecorder()
	syncReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync", bytes.NewBufferString(`{"items":[{"eventId":"evt-project-1","title":"项目内同步","description":"来自项目内手动同步","fingerprint":"project-sync-fp","platform":"android"}]}`))
	syncReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(syncResp, syncReq)
	if syncResp.Code != http.StatusBadRequest {
		t.Fatalf("expected sync 400 while connector inactive, got %d: %s", syncResp.Code, syncResp.Body.String())
	}

	activateBody := `{"name":"项目内 Bugly 连接器-更新","status":"active","config":{"appId":"demo-app","appKey":"demo-key","endpoint":"` + mockBugly.URL + `","issuesPath":"/issues"}}`
	activateResp := httptest.NewRecorder()
	activateReq, _ := http.NewRequest(http.MethodPut, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID), bytes.NewBufferString(activateBody))
	activateReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(activateResp, activateReq)
	if activateResp.Code != http.StatusOK {
		t.Fatalf("expected activate 200, got %d: %s", activateResp.Code, activateResp.Body.String())
	}

	syncResp = httptest.NewRecorder()
	syncReq, _ = http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync", bytes.NewBufferString(`{"items":[{"eventId":"evt-project-1","title":"项目内同步","description":"来自项目内手动同步","fingerprint":"project-sync-fp","platform":"android"}]}`))
	syncReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(syncResp, syncReq)
	if syncResp.Code != http.StatusOK {
		t.Fatalf("expected sync 200, got %d: %s", syncResp.Code, syncResp.Body.String())
	}

	recordsResp := httptest.NewRecorder()
	recordsReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync-records", nil)
	r.ServeHTTP(recordsResp, recordsReq)
	if recordsResp.Code != http.StatusOK {
		t.Fatalf("expected sync records 200, got %d: %s", recordsResp.Code, recordsResp.Body.String())
	}

	deleteResp := httptest.NewRecorder()
	deleteReq, _ := http.NewRequest(http.MethodDelete, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID), nil)
	r.ServeHTTP(deleteResp, deleteReq)
	if deleteResp.Code != http.StatusBadRequest {
		t.Fatalf("expected delete 400 when connector has signals, got %d: %s", deleteResp.Code, deleteResp.Body.String())
	}
}

func TestIntegrationConnectorHandler_ProjectScopedRejectsCrossProjectAccess(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	admin := testutil.CreateTestUser(t, db, "cross_project_connector_admin")
	projectA := testutil.CreateTestProject(t, db, "Connector Project A", "CPA")
	projectB := testutil.CreateTestProject(t, db, "Connector Project B", "CPB")

	h := NewIntegrationConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.POST("/projects/:id/integrations", h.Create)
	r.GET("/projects/:id/integrations/:connectorId/sync-records", h.ListSyncRecords)

	createBody := `{"name":"Project A Connector","type":"webhook","status":"active","config":{}}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(projectA.ID)+"/integrations", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected create 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	connectorID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	recordsResp := httptest.NewRecorder()
	recordsReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(projectB.ID)+"/integrations/"+toStrUint(connectorID)+"/sync-records", nil)
	r.ServeHTTP(recordsResp, recordsReq)
	if recordsResp.Code != http.StatusNotFound {
		t.Fatalf("expected cross-project access 404, got %d: %s", recordsResp.Code, recordsResp.Body.String())
	}
}

func TestIntegrationConnectorHandler_ProjectScopedSyncClassifiesAuthFailure(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	admin := testutil.CreateTestUser(t, db, "connector_auth_failure_admin")
	project := testutil.CreateTestProject(t, db, "Connector Auth Failure", "CAF")

	mockBugly := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
	}))
	defer mockBugly.Close()

	h := NewIntegrationConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	r.POST("/projects/:id/integrations", h.Create)
	r.POST("/projects/:id/integrations/:connectorId/sync", h.Sync)
	r.GET("/projects/:id/integrations/:connectorId/sync-records", h.ListSyncRecords)

	createBody := `{"name":"Bugly 鉴权失败","type":"bugly","status":"active","config":{"endpoint":"` + mockBugly.URL + `","issuesPath":"/issues","appId":"demo-app","appKey":"demo-key"}}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("expected create 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	if err := json.Unmarshal(createResp.Body.Bytes(), &createPayload); err != nil {
		t.Fatalf("unmarshal create payload failed: %v", err)
	}
	connectorID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	syncResp := httptest.NewRecorder()
	syncReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync", bytes.NewBufferString(`{}`))
	syncReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(syncResp, syncReq)
	if syncResp.Code != http.StatusBadRequest {
		t.Fatalf("expected auth failure 400, got %d: %s", syncResp.Code, syncResp.Body.String())
	}
	if !strings.Contains(syncResp.Body.String(), "连接器认证失败") {
		t.Fatalf("expected auth failure message, got %s", syncResp.Body.String())
	}

	recordsResp := httptest.NewRecorder()
	recordsReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/integrations/"+toStrUint(connectorID)+"/sync-records", nil)
	r.ServeHTTP(recordsResp, recordsReq)
	if recordsResp.Code != http.StatusOK {
		t.Fatalf("expected sync records 200, got %d: %s", recordsResp.Code, recordsResp.Body.String())
	}

	var recordsPayload map[string]interface{}
	if err := json.Unmarshal(recordsResp.Body.Bytes(), &recordsPayload); err != nil {
		t.Fatalf("unmarshal records payload failed: %v", err)
	}
	records := recordsPayload["data"].([]interface{})
	if len(records) != 1 {
		t.Fatalf("expected 1 sync record, got %d", len(records))
	}
	record := records[0].(map[string]interface{})
	if got := record["errorKind"]; got != "auth_failed" {
		t.Fatalf("expected errorKind auth_failed, got %v", got)
	}
	if got := record["retryable"]; got != false {
		t.Fatalf("expected retryable false, got %v", got)
	}
}
