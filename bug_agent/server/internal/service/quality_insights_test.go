package service_test

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"
	"encoding/json"
	"testing"
	"time"
)

func TestQualityInsightsService_GetOverview(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Quality Project", "QLT")
	operator := testutil.CreateTestUser(t, db, "quality_operator")
	modulePay := model.ProjectModule{ProjectID: project.ID, Name: "支付模块", Code: "PAY"}
	moduleLogin := model.ProjectModule{ProjectID: project.ID, Name: "登录模块", Code: "LOGIN"}
	if err := db.Create(&modulePay).Error; err != nil {
		t.Fatalf("create pay module failed: %v", err)
	}
	if err := db.Create(&moduleLogin).Error; err != nil {
		t.Fatalf("create login module failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	release1, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "5.0.0",
		BuildNumber: "50001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 10, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release1 failed: %v", err)
	}
	_, err = routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "5.1.0",
		BuildNumber: "51001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 11, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release2 failed: %v", err)
	}
	_, err = routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "5.2.0",
		BuildNumber: "52001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release3 failed: %v", err)
	}

	buglyConnector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Bugly",
		Type:         model.ConnectorTypeBugly,
		Status:       model.ConnectorStatusActive,
		InboundToken: "quality_bugly",
		CreatedBy:    operator.ID,
	}
	aliyunConnector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Aliyun",
		Type:         model.ConnectorTypeAliyun,
		Status:       model.ConnectorStatusActive,
		InboundToken: "quality_aliyun",
		CreatedBy:    operator.ID,
	}
	if err := db.Create(&buglyConnector).Error; err != nil {
		t.Fatalf("create bugly connector failed: %v", err)
	}
	if err := db.Create(&aliyunConnector).Error; err != nil {
		t.Fatalf("create aliyun connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	makeBody := func(eventID, title, version, build string, affected int) []byte {
		body, _ := json.Marshal(map[string]interface{}{
			"eventId":           eventID,
			"title":             title,
			"description":       title + " 描述",
			"platform":          "android",
			"appVersion":        version,
			"buildNumber":       build,
			"fingerprint":       "fp-" + eventID,
			"affectedUserCount": affected,
		})
		return body
	}

	_, clusterIgnored, _, err := ingestSvc.Ingest(buglyConnector, "manual_sync", makeBody("evt-q-1", "登录页闪退", release1.AppVersion, release1.BuildNumber, 2))
	if err != nil {
		t.Fatalf("ingest ignored cluster failed: %v", err)
	}
	_, clusterConverted, _, err := ingestSvc.Ingest(aliyunConnector, "manual_sync", makeBody("evt-q-2", "支付页闪退", "5.1.0", "51001", 8))
	if err != nil {
		t.Fatalf("ingest converted cluster failed: %v", err)
	}
	_, clusterNew, _, err := ingestSvc.Ingest(buglyConnector, "manual_sync", makeBody("evt-q-3", "订单页闪退", "5.2.0", "52001", 20))
	if err != nil {
		t.Fatalf("ingest new cluster failed: %v", err)
	}

	if err := db.Model(&model.IssueCluster{}).Where("id = ?", clusterIgnored.ID).Updates(map[string]interface{}{
		"module_id": moduleLogin.ID,
		"status":    model.IssueTriageStatusIgnored,
	}).Error; err != nil {
		t.Fatalf("update ignored cluster failed: %v", err)
	}
	if err := db.Model(&model.IssueCluster{}).Where("id = ?", clusterConverted.ID).Updates(map[string]interface{}{
		"module_id": modulePay.ID,
	}).Error; err != nil {
		t.Fatalf("update converted cluster failed: %v", err)
	}
	if err := db.Model(&model.IssueCluster{}).Where("id = ?", clusterNew.ID).Updates(map[string]interface{}{
		"module_id": modulePay.ID,
	}).Error; err != nil {
		t.Fatalf("update new cluster failed: %v", err)
	}

	triageSvc := service.NewSignalTriageService(db)
	convertedCluster, _, err := triageSvc.ConvertCluster(project.ID, clusterConverted.ID, operator.ID)
	if err != nil {
		t.Fatalf("convert cluster failed: %v", err)
	}
	if convertedCluster.Status != model.IssueTriageStatusConverted {
		t.Fatalf("expected converted status, got %s", convertedCluster.Status)
	}

	regressionSvc := service.NewRegressionPreventionService(db)
	verifiedItem, err := regressionSvc.CreateFromCluster(project.ID, convertedCluster.ID, operator.ID)
	if err != nil {
		t.Fatalf("create verified regression item failed: %v", err)
	}
	if _, err := regressionSvc.UpdateItem(project.ID, verifiedItem.ID, service.RegressionItemUpdateInput{Status: model.RegressionItemStatusVerified}); err != nil {
		t.Fatalf("verify regression item failed: %v", err)
	}
	if _, err := regressionSvc.CreateFromCluster(project.ID, clusterNew.ID, operator.ID); err != nil {
		t.Fatalf("create draft regression item failed: %v", err)
	}

	insightSvc := service.NewQualityInsightsService(db)
	overview, err := insightSvc.GetOverview(project.ID)
	if err != nil {
		t.Fatalf("get quality overview failed: %v", err)
	}

	if overview.IssuePool.TotalClusters != 3 {
		t.Fatalf("expected 3 clusters, got %d", overview.IssuePool.TotalClusters)
	}
	if overview.IssuePool.OpenClusters != 1 {
		t.Fatalf("expected 1 open cluster, got %d", overview.IssuePool.OpenClusters)
	}
	if overview.IssuePool.ConvertedClusters != 1 {
		t.Fatalf("expected 1 converted cluster, got %d", overview.IssuePool.ConvertedClusters)
	}
	if overview.IssuePool.IgnoredClusters != 1 {
		t.Fatalf("expected 1 ignored cluster, got %d", overview.IssuePool.IgnoredClusters)
	}
	if overview.Regression.TotalItems != 2 || overview.Regression.OpenItems != 1 || overview.Regression.VerifiedItems != 1 {
		t.Fatalf("unexpected regression stats: %+v", overview.Regression)
	}
	if overview.ReleaseHealth.HighAnomalyCount != 1 || overview.ReleaseHealth.WatchAnomalyCount != 1 {
		t.Fatalf("unexpected release health stats: %+v", overview.ReleaseHealth)
	}
	if len(overview.TopReleaseAnomalies) != 2 {
		t.Fatalf("expected 2 top release anomalies, got %d", len(overview.TopReleaseAnomalies))
	}

	payModule := overview.ModuleHotspots[0]
	if payModule.ModuleName != "支付模块" || payModule.ClusterCount != 2 || payModule.HighAnomalyClusterCount != 1 {
		t.Fatalf("unexpected pay module hotspot: %+v", payModule)
	}

	sourceCounts := map[string]int{}
	for _, item := range overview.SourceBreakdowns {
		sourceCounts[item.SourceType] = item.SignalCount
	}
	if sourceCounts[model.ConnectorTypeBugly] != 2 || sourceCounts[model.ConnectorTypeAliyun] != 1 {
		t.Fatalf("unexpected source breakdown: %+v", sourceCounts)
	}
}
