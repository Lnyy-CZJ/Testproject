package handler

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func seedIssueClusterForProject(t *testing.T, db *gorm.DB, projectID uint, username string) (model.User, model.IntegrationConnector, model.IssueCluster) {
	t.Helper()
	user := testutil.CreateTestUser(t, db, username)
	connector := model.IntegrationConnector{
		ProjectID:    projectID,
		Name:         "Webhook Seed",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "seed_tok_" + username,
		CreatedBy:    user.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingest := service.NewSignalIngestService(db)
	signal, cluster, _, err := ingest.Ingest(connector, "test_seed", []byte(`{"eventId":"evt-`+username+`","title":"启动崩溃","description":"用户打开 App 后立即闪退","fingerprint":"fp-`+username+`","platform":"android","appVersion":"1.0.1"}`))
	if err != nil {
		t.Fatalf("seed ingest failed: %v", err)
	}
	if signal.ID == 0 || cluster == nil || cluster.ID == 0 {
		t.Fatalf("seed signal/cluster failed")
	}
	return user, connector, *cluster
}

func TestIssuePoolHandler_ListAssignIgnoreConvert(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	operator := testutil.CreateTestUser(t, db, "issue_pool_operator")
	project := testutil.CreateTestProject(t, db, "Issue Pool Project", "ISP")
	nowIteration := model.Iteration{
		ProjectID: project.ID,
		Name:      "Sprint Intake",
		Status:    "active",
	}
	if err := db.Create(&nowIteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	assignee := testutil.CreateTestUser(t, db, "issue_pool_assignee")
	_, _, cluster := seedIssueClusterForProject(t, db, project.ID, "issue_pool_seed")

	h := NewIssuePoolHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", operator.ID)
		c.Next()
	})
	r.GET("/projects/:id/issue-clusters", h.ListClusters)
	r.GET("/projects/:id/issue-clusters/:clusterId", h.GetCluster)
	r.GET("/projects/:id/issue-clusters/:clusterId/signals", h.ListSignals)
	r.GET("/projects/:id/issue-clusters/:clusterId/releases", h.ListClusterReleases)
	r.POST("/projects/:id/issue-clusters/:clusterId/assign", h.AssignCluster)
	r.POST("/projects/:id/issue-clusters/:clusterId/ignore", h.IgnoreCluster)
	r.POST("/projects/:id/issue-clusters/:clusterId/merge", h.MergeCluster)
	r.POST("/projects/:id/issue-clusters/:clusterId/convert", h.ConvertCluster)

	listResp := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters", nil)
	r.ServeHTTP(listResp, listReq)
	if listResp.Code != http.StatusOK {
		t.Fatalf("expected list 200, got %d: %s", listResp.Code, listResp.Body.String())
	}

	filteredResp := httptest.NewRecorder()
	filteredReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters?status=new&q=启动", nil)
	r.ServeHTTP(filteredResp, filteredReq)
	if filteredResp.Code != http.StatusOK {
		t.Fatalf("expected filtered list 200, got %d: %s", filteredResp.Code, filteredResp.Body.String())
	}

	assignResp := httptest.NewRecorder()
	assignReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(cluster.ID)+"/assign", bytes.NewBufferString(`{"ownerUserId":`+toStrUint(assignee.ID)+`}`))
	assignReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(assignResp, assignReq)
	if assignResp.Code != http.StatusOK {
		t.Fatalf("expected assign 200, got %d: %s", assignResp.Code, assignResp.Body.String())
	}

	var assigned model.IssueCluster
	if err := db.First(&assigned, cluster.ID).Error; err != nil {
		t.Fatalf("query assigned cluster failed: %v", err)
	}
	if assigned.OwnerUserID == nil || *assigned.OwnerUserID != assignee.ID {
		t.Fatalf("expected owner user id %d, got %v", assignee.ID, assigned.OwnerUserID)
	}

	signalsResp := httptest.NewRecorder()
	signalsReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(cluster.ID)+"/signals", nil)
	r.ServeHTTP(signalsResp, signalsReq)
	if signalsResp.Code != http.StatusOK {
		t.Fatalf("expected signals 200, got %d: %s", signalsResp.Code, signalsResp.Body.String())
	}

	convertResp := httptest.NewRecorder()
	convertReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(cluster.ID)+"/convert", bytes.NewBufferString(`{}`))
	convertReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(convertResp, convertReq)
	if convertResp.Code != http.StatusOK {
		t.Fatalf("expected convert 200, got %d: %s", convertResp.Code, convertResp.Body.String())
	}

	var clusterAfterConvert model.IssueCluster
	if err := db.First(&clusterAfterConvert, cluster.ID).Error; err != nil {
		t.Fatalf("query converted cluster failed: %v", err)
	}
	if clusterAfterConvert.LinkedDefectID == nil {
		t.Fatalf("expected linked defect id after convert")
	}
	if clusterAfterConvert.Status != model.IssueTriageStatusConverted {
		t.Fatalf("expected converted status, got %s", clusterAfterConvert.Status)
	}

	var defect model.Defect
	if err := db.Preload("Reporter").First(&defect, *clusterAfterConvert.LinkedDefectID).Error; err != nil {
		t.Fatalf("query defect failed: %v", err)
	}
	if defect.Title == "" || defect.IterationID == 0 {
		t.Fatalf("expected converted defect to have title and iteration")
	}
	if defect.AssigneeID == nil || *defect.AssigneeID != assignee.ID {
		t.Fatalf("expected converted defect assignee %d, got %v", assignee.ID, defect.AssigneeID)
	}

	var comments []model.Comment
	if err := db.Where("defect_id = ?", defect.ID).Find(&comments).Error; err != nil {
		t.Fatalf("query defect comments failed: %v", err)
	}
	if len(comments) == 0 {
		t.Fatalf("expected issue-pool conversion comment to exist")
	}

	var signals []model.IssueSignal
	if err := db.Where("cluster_id = ?", cluster.ID).Find(&signals).Error; err != nil {
		t.Fatalf("query linked signals failed: %v", err)
	}
	for _, signal := range signals {
		if signal.LinkedDefectID == nil || *signal.LinkedDefectID != defect.ID {
			t.Fatalf("expected signal %d linked defect %d, got %v", signal.ID, defect.ID, signal.LinkedDefectID)
		}
	}

	clusterDetailResp := httptest.NewRecorder()
	clusterDetailReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(cluster.ID), nil)
	r.ServeHTTP(clusterDetailResp, clusterDetailReq)
	if clusterDetailResp.Code != http.StatusOK {
		t.Fatalf("expected detail 200, got %d: %s", clusterDetailResp.Code, clusterDetailResp.Body.String())
	}
	if !bytes.Contains(clusterDetailResp.Body.Bytes(), []byte(`"code":"`+defect.Code+`"`)) {
		t.Fatalf("expected linked defect code in detail response, got %s", clusterDetailResp.Body.String())
	}
	if !bytes.Contains(clusterDetailResp.Body.Bytes(), []byte(`"username":"issue_pool_assignee"`)) {
		t.Fatalf("expected linked defect assignee in detail response, got %s", clusterDetailResp.Body.String())
	}
	if !bytes.Contains(clusterDetailResp.Body.Bytes(), []byte(`"username":"issue_pool_operator"`)) {
		t.Fatalf("expected linked defect reporter in detail response, got %s", clusterDetailResp.Body.String())
	}

	_, _, ignoreCluster := seedIssueClusterForProject(t, db, project.ID, "issue_pool_ignore")
	ignoreResp := httptest.NewRecorder()
	ignoreReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(ignoreCluster.ID)+"/ignore", bytes.NewBufferString(`{"reason":"确认不是问题"}`))
	ignoreReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(ignoreResp, ignoreReq)
	if ignoreResp.Code != http.StatusOK {
		t.Fatalf("expected ignore 200, got %d: %s", ignoreResp.Code, ignoreResp.Body.String())
	}

	var ignored model.IssueCluster
	if err := db.First(&ignored, ignoreCluster.ID).Error; err != nil {
		t.Fatalf("query ignored cluster failed: %v", err)
	}
	if ignored.Status != model.IssueTriageStatusIgnored {
		t.Fatalf("expected ignored status, got %s", ignored.Status)
	}

	_, _, mergeTarget := seedIssueClusterForProject(t, db, project.ID, "issue_pool_merge_target")
	_, _, mergeSource := seedIssueClusterForProject(t, db, project.ID, "issue_pool_merge_source")
	mergeResp := httptest.NewRecorder()
	mergeReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(mergeSource.ID)+"/merge", bytes.NewBufferString(`{"targetClusterId":`+toStrUint(mergeTarget.ID)+`,"reason":"疑似重复"}`))
	mergeReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(mergeResp, mergeReq)
	if mergeResp.Code != http.StatusOK {
		t.Fatalf("expected merge 200, got %d: %s", mergeResp.Code, mergeResp.Body.String())
	}

	var mergedSource model.IssueCluster
	if err := db.First(&mergedSource, mergeSource.ID).Error; err != nil {
		t.Fatalf("query merged source cluster failed: %v", err)
	}
	if mergedSource.Status != model.IssueTriageStatusClustered {
		t.Fatalf("expected merged source status clustered, got %s", mergedSource.Status)
	}

	var mergedSignals []model.IssueSignal
	if err := db.Where("source_event_id = ?", "evt-issue_pool_merge_source").Find(&mergedSignals).Error; err != nil {
		t.Fatalf("query merged signals failed: %v", err)
	}
	if len(mergedSignals) != 1 || mergedSignals[0].ClusterID == nil || *mergedSignals[0].ClusterID != mergeTarget.ID {
		t.Fatalf("expected merged signal moved to target cluster %d, got %+v", mergeTarget.ID, mergedSignals)
	}

	var records []model.IssueTriageRecord
	if err := db.Order("id asc").Find(&records).Error; err != nil {
		t.Fatalf("query triage records failed: %v", err)
	}
	if len(records) < 4 {
		t.Fatalf("expected triage records for assign/convert/ignore/merge, got %d", len(records))
	}
}

func TestIssuePoolHandler_ListClusterReleases(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	operator := testutil.CreateTestUser(t, db, "issue_pool_release_operator")
	project := testutil.CreateTestProject(t, db, "Issue Pool Release Project", "ISPR")
	_, _, cluster := seedIssueClusterForProject(t, db, project.ID, "issue_pool_release_seed")

	routingSvc := service.NewProjectRoutingService(db)
	if _, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.0.1",
		BuildNumber: "10001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 14, 0, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("create app release failed: %v", err)
	}

	h := NewIssuePoolHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", operator.ID)
		c.Next()
	})
	r.GET("/projects/:id/issue-clusters/:clusterId/releases", h.ListClusterReleases)

	resp := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters/"+toStrUint(cluster.ID)+"/releases", nil)
	r.ServeHTTP(resp, req)
	if resp.Code != http.StatusOK {
		t.Fatalf("expected releases 200, got %d: %s", resp.Code, resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"matchMode":"app_version"`)) {
		t.Fatalf("expected app_version release match response, got %s", resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"appVersion":"1.0.1"`)) {
		t.Fatalf("expected app version in response, got %s", resp.Body.String())
	}
}

func TestIssuePoolHandler_ListClusters_SupportsVersionFiltersAndSummary(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	operator := testutil.CreateTestUser(t, db, "issue_pool_filter_operator")
	project := testutil.CreateTestProject(t, db, "Issue Pool Filter Project", "ISPF")
	creator := testutil.CreateTestUser(t, db, "issue_pool_filter_creator")

	_, connector, _ := seedIssueClusterForProject(t, db, project.ID, "issue_pool_filter_android")
	iosConnector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "iOS Webhook Seed",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "seed_tok_ios_filter",
		CreatedBy:    creator.ID,
	}
	if err := db.Create(&iosConnector).Error; err != nil {
		t.Fatalf("create ios connector failed: %v", err)
	}
	ingest := service.NewSignalIngestService(db)
	if _, _, _, err := ingest.Ingest(iosConnector, "test_seed", []byte(`{"eventId":"evt-ios-filter","title":"iOS 卡死","description":"进入首页后卡死","fingerprint":"fp-ios-filter","platform":"ios","appVersion":"2.0.0","buildNumber":"20001"}`)); err != nil {
		t.Fatalf("seed ios signal failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	if _, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.0.1",
		BuildNumber: "10001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 15, 0, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("create app release failed: %v", err)
	}

	h := NewIssuePoolHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", operator.ID)
		c.Next()
	})
	r.GET("/projects/:id/issue-clusters", h.ListClusters)

	resp := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters?platform=android&appVersion=1.0", nil)
	r.ServeHTTP(resp, req)
	if resp.Code != http.StatusOK {
		t.Fatalf("expected list 200, got %d: %s", resp.Code, resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"platform":"android"`)) {
		t.Fatalf("expected android platform in response, got %s", resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"appVersion":"1.0.1"`)) {
		t.Fatalf("expected app version summary in response, got %s", resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"releaseMatchCount":1`)) {
		t.Fatalf("expected release match count 1, got %s", resp.Body.String())
	}
	if bytes.Contains(resp.Body.Bytes(), []byte("iOS 卡死")) {
		t.Fatalf("expected ios cluster filtered out, got %s", resp.Body.String())
	}

	_ = connector
}

func TestIssuePoolHandler_ListClusters_SupportsReleaseFilterAndSummaryEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	operator := testutil.CreateTestUser(t, db, "issue_pool_release_filter_operator")
	project := testutil.CreateTestProject(t, db, "Issue Pool Release Filter Project", "ISPRF")
	creator := testutil.CreateTestUser(t, db, "issue_pool_release_filter_creator")

	firstConnector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Release Filter Seed A",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "seed_tok_release_a",
		CreatedBy:    creator.ID,
	}
	secondConnector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Release Filter Seed B",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "seed_tok_release_b",
		CreatedBy:    creator.ID,
	}
	if err := db.Create(&firstConnector).Error; err != nil {
		t.Fatalf("create first connector failed: %v", err)
	}
	if err := db.Create(&secondConnector).Error; err != nil {
		t.Fatalf("create second connector failed: %v", err)
	}

	ingest := service.NewSignalIngestService(db)
	if _, _, _, err := ingest.Ingest(firstConnector, "test_seed", []byte(`{"eventId":"evt-release-filter-a","title":"启动崩溃","fingerprint":"fp-release-filter-a","platform":"android","appVersion":"1.2.3","buildNumber":"1203001"}`)); err != nil {
		t.Fatalf("seed first signal failed: %v", err)
	}
	if _, _, _, err := ingest.Ingest(secondConnector, "test_seed", []byte(`{"eventId":"evt-release-filter-b","title":"旧版启动崩溃","fingerprint":"fp-release-filter-b","platform":"android","appVersion":"1.2.3","buildNumber":"1203002","affectedUserCount":4}`)); err != nil {
		t.Fatalf("seed second signal failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	targetRelease, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.2.3",
		BuildNumber: "1203001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 16, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create target release failed: %v", err)
	}
	if _, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.2.3",
		BuildNumber: "1203002",
		Channel:     "gray",
		ReleaseTime: time.Date(2026, 4, 12, 17, 0, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("create secondary release failed: %v", err)
	}

	h := NewIssuePoolHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", operator.ID)
		c.Next()
	})
	r.GET("/projects/:id/issue-clusters", h.ListClusters)
	r.GET("/projects/:id/issue-clusters/release-summary", h.ListReleaseSummaries)

	listResp := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters?releaseId="+toStrUint(targetRelease.ID), nil)
	r.ServeHTTP(listResp, listReq)
	if listResp.Code != http.StatusOK {
		t.Fatalf("expected list 200, got %d: %s", listResp.Code, listResp.Body.String())
	}
	if !bytes.Contains(listResp.Body.Bytes(), []byte(`"buildNumber":"1203001"`)) {
		t.Fatalf("expected selected release build in response, got %s", listResp.Body.String())
	}
	if bytes.Contains(listResp.Body.Bytes(), []byte(`"buildNumber":"1203002"`)) {
		t.Fatalf("expected other release build filtered out, got %s", listResp.Body.String())
	}

	summaryResp := httptest.NewRecorder()
	summaryReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters/release-summary", nil)
	r.ServeHTTP(summaryResp, summaryReq)
	if summaryResp.Code != http.StatusOK {
		t.Fatalf("expected summary 200, got %d: %s", summaryResp.Code, summaryResp.Body.String())
	}
	if !bytes.Contains(summaryResp.Body.Bytes(), []byte(`"clusterCount":1`)) {
		t.Fatalf("expected cluster count in summary, got %s", summaryResp.Body.String())
	}
	if !bytes.Contains(summaryResp.Body.Bytes(), []byte(`"appVersion":"1.2.3"`)) {
		t.Fatalf("expected app version in summary, got %s", summaryResp.Body.String())
	}
}

func TestIssuePoolHandler_ListClusters_SupportsAnomalyFilter(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	operator := testutil.CreateTestUser(t, db, "issue_pool_anomaly_operator")
	project := testutil.CreateTestProject(t, db, "Issue Pool Anomaly Project", "ISPA")
	creator := testutil.CreateTestUser(t, db, "issue_pool_anomaly_creator")

	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Anomaly Seed",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "seed_tok_anomaly",
		CreatedBy:    creator.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	for _, release := range []service.AppReleaseInput{
		{
			Platform:    "android",
			AppVersion:  "5.0.0",
			BuildNumber: "50001",
			Channel:     "prod",
			ReleaseTime: time.Date(2026, 4, 11, 10, 0, 0, 0, time.UTC),
		},
		{
			Platform:    "android",
			AppVersion:  "5.1.0",
			BuildNumber: "51001",
			Channel:     "prod",
			ReleaseTime: time.Date(2026, 4, 12, 10, 0, 0, 0, time.UTC),
		},
	} {
		if _, err := routingSvc.CreateRelease(project.ID, release); err != nil {
			t.Fatalf("create release failed: %v", err)
		}
	}

	ingest := service.NewSignalIngestService(db)
	for _, payload := range []string{
		`{"eventId":"evt-handler-anomaly-watch","title":"首页白屏","fingerprint":"fp-handler-anomaly-watch","platform":"android","appVersion":"5.1.0","buildNumber":"51001","affectedUserCount":6}`,
		`{"eventId":"evt-handler-anomaly-baseline","title":"设置页报错","fingerprint":"fp-handler-anomaly-baseline","platform":"android","appVersion":"5.0.0","buildNumber":"50001","affectedUserCount":1}`,
	} {
		if _, _, _, err := ingest.Ingest(connector, "test_seed", []byte(payload)); err != nil {
			t.Fatalf("seed signal failed: %v", err)
		}
	}

	h := NewIssuePoolHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", operator.ID)
		c.Next()
	})
	r.GET("/projects/:id/issue-clusters", h.ListClusters)

	resp := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(project.ID)+"/issue-clusters?anomalyLevel=watch", nil)
	r.ServeHTTP(resp, req)
	if resp.Code != http.StatusOK {
		t.Fatalf("expected list 200, got %d: %s", resp.Code, resp.Body.String())
	}
	if !bytes.Contains(resp.Body.Bytes(), []byte(`"anomalyLevel":"watch"`)) {
		t.Fatalf("expected anomaly level watch in response, got %s", resp.Body.String())
	}
	if bytes.Contains(resp.Body.Bytes(), []byte("设置页报错")) {
		t.Fatalf("expected baseline cluster filtered out, got %s", resp.Body.String())
	}
}

func TestIssuePoolHandler_BatchAssignIgnoreConvert(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)
	model.DB = db

	operator := testutil.CreateTestUser(t, db, "issue_pool_batch_operator")
	project := testutil.CreateTestProject(t, db, "Issue Pool Batch Project", "ISPB")
	iteration := model.Iteration{
		ProjectID: project.ID,
		Name:      "Sprint Batch",
		Status:    "active",
	}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	assignee := testutil.CreateTestUser(t, db, "issue_pool_batch_assignee")
	_, _, firstCluster := seedIssueClusterForProject(t, db, project.ID, "issue_pool_batch_first")
	_, _, secondCluster := seedIssueClusterForProject(t, db, project.ID, "issue_pool_batch_second")
	_, _, thirdCluster := seedIssueClusterForProject(t, db, project.ID, "issue_pool_batch_third")

	h := NewIssuePoolHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", operator.ID)
		c.Next()
	})
	r.POST("/projects/:id/issue-clusters/batch-assign", h.BatchAssignClusters)
	r.POST("/projects/:id/issue-clusters/batch-ignore", h.BatchIgnoreClusters)
	r.POST("/projects/:id/issue-clusters/batch-convert", h.BatchConvertClusters)

	assignResp := httptest.NewRecorder()
	assignReq, _ := http.NewRequest(
		http.MethodPost,
		"/projects/"+toStrUint(project.ID)+"/issue-clusters/batch-assign",
		bytes.NewBufferString(`{"clusterIds":[`+toStrUint(firstCluster.ID)+`,`+toStrUint(secondCluster.ID)+`],"ownerUserId":`+toStrUint(assignee.ID)+`}`),
	)
	assignReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(assignResp, assignReq)
	if assignResp.Code != http.StatusOK {
		t.Fatalf("expected batch assign 200, got %d: %s", assignResp.Code, assignResp.Body.String())
	}

	for _, clusterID := range []uint{firstCluster.ID, secondCluster.ID} {
		var cluster model.IssueCluster
		if err := db.First(&cluster, clusterID).Error; err != nil {
			t.Fatalf("query cluster %d failed: %v", clusterID, err)
		}
		if cluster.OwnerUserID == nil || *cluster.OwnerUserID != assignee.ID {
			t.Fatalf("expected owner %d on cluster %d, got %v", assignee.ID, clusterID, cluster.OwnerUserID)
		}
	}

	ignoreResp := httptest.NewRecorder()
	ignoreReq, _ := http.NewRequest(
		http.MethodPost,
		"/projects/"+toStrUint(project.ID)+"/issue-clusters/batch-ignore",
		bytes.NewBufferString(`{"clusterIds":[`+toStrUint(thirdCluster.ID)+`],"reason":"批量忽略测试"}`),
	)
	ignoreReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(ignoreResp, ignoreReq)
	if ignoreResp.Code != http.StatusOK {
		t.Fatalf("expected batch ignore 200, got %d: %s", ignoreResp.Code, ignoreResp.Body.String())
	}

	var ignoredCluster model.IssueCluster
	if err := db.First(&ignoredCluster, thirdCluster.ID).Error; err != nil {
		t.Fatalf("query ignored cluster failed: %v", err)
	}
	if ignoredCluster.Status != model.IssueTriageStatusIgnored {
		t.Fatalf("expected ignored cluster status, got %s", ignoredCluster.Status)
	}

	convertResp := httptest.NewRecorder()
	convertReq, _ := http.NewRequest(
		http.MethodPost,
		"/projects/"+toStrUint(project.ID)+"/issue-clusters/batch-convert",
		bytes.NewBufferString(`{"clusterIds":[`+toStrUint(firstCluster.ID)+`,`+toStrUint(secondCluster.ID)+`]}`),
	)
	convertReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(convertResp, convertReq)
	if convertResp.Code != http.StatusOK {
		t.Fatalf("expected batch convert 200, got %d: %s", convertResp.Code, convertResp.Body.String())
	}
	if !bytes.Contains(convertResp.Body.Bytes(), []byte(`"updatedCount":2`)) {
		t.Fatalf("expected updated count 2, got %s", convertResp.Body.String())
	}

	for _, clusterID := range []uint{firstCluster.ID, secondCluster.ID} {
		var cluster model.IssueCluster
		if err := db.First(&cluster, clusterID).Error; err != nil {
			t.Fatalf("query converted cluster %d failed: %v", clusterID, err)
		}
		if cluster.LinkedDefectID == nil {
			t.Fatalf("expected linked defect for cluster %d", clusterID)
		}
		if cluster.Status != model.IssueTriageStatusConverted {
			t.Fatalf("expected converted status for cluster %d, got %s", clusterID, cluster.Status)
		}
	}
}
