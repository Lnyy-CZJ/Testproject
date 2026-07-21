package service_test

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"
	"encoding/json"
	"testing"
	"time"
)

func TestSignalTriageService_ListClusters_EnrichesVersionSummaryAndFilters(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Signal Triage Project", "STP")
	owner := testutil.CreateTestUser(t, db, "signal_triage_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Aliyun Logs",
		Type:         model.ConnectorTypeAliyun,
		Status:       model.ConnectorStatusActive,
		InboundToken: "signal_triage_versions",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	for _, payload := range []map[string]interface{}{
		{
			"eventId":           "evt-android-1",
			"title":             "启动崩溃",
			"description":       "Android 崩溃",
			"platform":          "android",
			"appVersion":        "1.2.3",
			"buildNumber":       "1203001",
			"fingerprint":       "fp-android",
			"affectedUserCount": 5,
			"lastSeenAt":        "2026-04-12T12:00:00Z",
		},
		{
			"eventId":           "evt-ios-1",
			"title":             "页面卡死",
			"description":       "iOS 卡死",
			"platform":          "ios",
			"appVersion":        "3.0.0",
			"buildNumber":       "30001",
			"fingerprint":       "fp-ios",
			"affectedUserCount": 2,
			"lastSeenAt":        "2026-04-12T11:00:00Z",
		},
	} {
		body, _ := json.Marshal(payload)
		if _, _, _, err := ingestSvc.Ingest(connector, "manual_sync", body); err != nil {
			t.Fatalf("ingest signal failed: %v", err)
		}
	}

	routingSvc := service.NewProjectRoutingService(db)
	if _, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.2.3",
		BuildNumber: "1203001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 10, 0, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("create android release failed: %v", err)
	}

	triageSvc := service.NewSignalTriageService(db)
	items, total, err := triageSvc.ListClusters(project.ID, service.IssueClusterListParams{
		Page:     1,
		PageSize: 20,
	})
	if err != nil {
		t.Fatalf("list clusters failed: %v", err)
	}
	if total != 2 {
		t.Fatalf("expected total 2, got %d", total)
	}
	if len(items) != 2 {
		t.Fatalf("expected 2 items, got %d", len(items))
	}
	if items[0].Platform != "android" || items[0].AppVersion != "1.2.3" || items[0].BuildNumber != "1203001" {
		t.Fatalf("expected latest signal summary on first item, got %+v", items[0])
	}
	if items[0].ReleaseMatchCount != 1 {
		t.Fatalf("expected release match count 1, got %d", items[0].ReleaseMatchCount)
	}

	filtered, filteredTotal, err := triageSvc.ListClusters(project.ID, service.IssueClusterListParams{
		Platform:   "android",
		AppVersion: "1.2",
		Page:       1,
		PageSize:   20,
	})
	if err != nil {
		t.Fatalf("list filtered clusters failed: %v", err)
	}
	if filteredTotal != 1 || len(filtered) != 1 {
		t.Fatalf("expected 1 filtered item, got total=%d len=%d", filteredTotal, len(filtered))
	}
	if filtered[0].Platform != "android" {
		t.Fatalf("expected android filtered item, got %+v", filtered[0])
	}
}

func TestSignalTriageService_ListClusters_SupportsExactReleaseFilter(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Signal Release Filter Project", "SRF")
	owner := testutil.CreateTestUser(t, db, "signal_release_filter_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Bugly",
		Type:         model.ConnectorTypeBugly,
		Status:       model.ConnectorStatusActive,
		InboundToken: "signal_release_filter",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	for _, payload := range []map[string]interface{}{
		{
			"eventId":     "evt-release-filter-a",
			"title":       "启动崩溃",
			"platform":    "android",
			"appVersion":  "1.2.3",
			"buildNumber": "1203001",
			"fingerprint": "fp-release-filter-a",
		},
		{
			"eventId":     "evt-release-filter-b",
			"title":       "旧版启动崩溃",
			"platform":    "android",
			"appVersion":  "1.2.3",
			"buildNumber": "1203002",
			"fingerprint": "fp-release-filter-b",
		},
	} {
		body, _ := json.Marshal(payload)
		if _, _, _, err := ingestSvc.Ingest(connector, "manual_sync", body); err != nil {
			t.Fatalf("ingest signal failed: %v", err)
		}
	}

	routingSvc := service.NewProjectRoutingService(db)
	targetRelease, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.2.3",
		BuildNumber: "1203001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create target release failed: %v", err)
	}
	if _, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.2.3",
		BuildNumber: "1203002",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 11, 0, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("create secondary release failed: %v", err)
	}

	triageSvc := service.NewSignalTriageService(db)
	items, total, err := triageSvc.ListClusters(project.ID, service.IssueClusterListParams{
		ReleaseID: targetRelease.ID,
		Page:      1,
		PageSize:  20,
	})
	if err != nil {
		t.Fatalf("list clusters with release filter failed: %v", err)
	}
	if total != 1 || len(items) != 1 {
		t.Fatalf("expected one cluster for release filter, got total=%d len=%d", total, len(items))
	}
	if items[0].BuildNumber != "1203001" {
		t.Fatalf("expected build 1203001, got %+v", items[0])
	}
}

func TestSignalTriageService_ListReleaseSummaries_AggregatesByRelease(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Signal Release Summary Project", "SRS")
	owner := testutil.CreateTestUser(t, db, "signal_release_summary_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Aliyun Logs",
		Type:         model.ConnectorTypeAliyun,
		Status:       model.ConnectorStatusActive,
		InboundToken: "signal_release_summary",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	for _, payload := range []map[string]interface{}{
		{
			"eventId":           "evt-summary-a",
			"title":             "启动崩溃",
			"platform":          "android",
			"appVersion":        "1.2.3",
			"buildNumber":       "1203001",
			"fingerprint":       "fp-summary-a",
			"affectedUserCount": 5,
			"lastSeenAt":        "2026-04-12T12:00:00Z",
		},
		{
			"eventId":           "evt-summary-b",
			"title":             "支付页卡死",
			"platform":          "android",
			"appVersion":        "1.2.3",
			"buildNumber":       "1203001",
			"fingerprint":       "fp-summary-b",
			"affectedUserCount": 3,
			"lastSeenAt":        "2026-04-12T12:05:00Z",
		},
	} {
		body, _ := json.Marshal(payload)
		if _, _, _, err := ingestSvc.Ingest(connector, "manual_sync", body); err != nil {
			t.Fatalf("ingest signal failed: %v", err)
		}
	}

	routingSvc := service.NewProjectRoutingService(db)
	release, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.2.3",
		BuildNumber: "1203001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release failed: %v", err)
	}

	triageSvc := service.NewSignalTriageService(db)
	items, err := triageSvc.ListReleaseSummaries(project.ID, service.IssueClusterListParams{})
	if err != nil {
		t.Fatalf("list release summaries failed: %v", err)
	}
	if len(items) != 1 {
		t.Fatalf("expected one release summary, got %d", len(items))
	}
	if items[0].Release.ID != release.ID {
		t.Fatalf("expected release %d, got %d", release.ID, items[0].Release.ID)
	}
	if items[0].ClusterCount != 2 {
		t.Fatalf("expected cluster count 2, got %d", items[0].ClusterCount)
	}
	if items[0].SignalCount != 2 {
		t.Fatalf("expected signal count 2, got %d", items[0].SignalCount)
	}
	if items[0].AffectedUserCount != 8 {
		t.Fatalf("expected affected user count 8, got %d", items[0].AffectedUserCount)
	}
}

func TestSignalTriageService_ListClusters_SupportsAnomalyLevelFilter(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Signal Anomaly Filter Project", "SAF")
	owner := testutil.CreateTestUser(t, db, "signal_anomaly_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Webhook",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "signal_anomaly_filter",
		CreatedBy:    owner.ID,
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

	ingestSvc := service.NewSignalIngestService(db)
	for _, payload := range []map[string]interface{}{
		{
			"eventId":           "evt-anomaly-watch",
			"title":             "首页白屏",
			"platform":          "android",
			"appVersion":        "5.1.0",
			"buildNumber":       "51001",
			"fingerprint":       "fp-anomaly-watch",
			"affectedUserCount": 6,
		},
		{
			"eventId":           "evt-anomaly-baseline",
			"title":             "设置页报错",
			"platform":          "android",
			"appVersion":        "5.0.0",
			"buildNumber":       "50001",
			"fingerprint":       "fp-anomaly-baseline",
			"affectedUserCount": 1,
		},
	} {
		body, _ := json.Marshal(payload)
		if _, _, _, err := ingestSvc.Ingest(connector, "manual_sync", body); err != nil {
			t.Fatalf("ingest signal failed: %v", err)
		}
	}

	triageSvc := service.NewSignalTriageService(db)
	items, total, err := triageSvc.ListClusters(project.ID, service.IssueClusterListParams{
		AnomalyLevel: "watch",
		Page:         1,
		PageSize:     20,
	})
	if err != nil {
		t.Fatalf("list clusters with anomaly filter failed: %v", err)
	}
	if total != 1 || len(items) != 1 {
		t.Fatalf("expected one watch cluster, got total=%d len=%d", total, len(items))
	}
	if items[0].Title != "首页白屏" {
		t.Fatalf("expected watch cluster title 首页白屏, got %+v", items[0])
	}
	if items[0].AnomalyLevel != "watch" {
		t.Fatalf("expected anomaly level watch, got %+v", items[0])
	}
}

func TestSignalTriageService_ListClusters_IncludesRoutingExplanation(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Signal Routing Explanation Project", "SRE")
	owner := testutil.CreateTestUser(t, db, "signal_routing_explanation_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Bugly Android",
		Type:         model.ConnectorTypeBugly,
		Status:       model.ConnectorStatusActive,
		InboundToken: "signal_routing_explanation",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	module, err := routingSvc.CreateModule(project.ID, service.ProjectModuleInput{
		Name:        "启动模块",
		Code:        "startup",
		OwnerUserID: &owner.ID,
	})
	if err != nil {
		t.Fatalf("create module failed: %v", err)
	}
	rule, err := routingSvc.CreateRule(project.ID, service.IssueRoutingRuleInput{
		MatchType:        "platform",
		MatchValue:       "android",
		ModuleID:         &module.ID,
		OwnerUserID:      &owner.ID,
		PriorityOverride: "P1",
		SeverityOverride: "major",
		Enabled:          true,
		SortOrder:        1,
	})
	if err != nil {
		t.Fatalf("create rule failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	body, _ := json.Marshal(map[string]interface{}{
		"eventId":     "evt-routing-explanation-1",
		"title":       "启动白屏",
		"platform":    "android",
		"appVersion":  "6.0.0",
		"fingerprint": "fp-routing-explanation",
	})
	if _, _, _, err := ingestSvc.Ingest(connector, "manual_sync", body); err != nil {
		t.Fatalf("ingest signal failed: %v", err)
	}

	triageSvc := service.NewSignalTriageService(db)
	items, total, err := triageSvc.ListClusters(project.ID, service.IssueClusterListParams{
		Page:     1,
		PageSize: 20,
	})
	if err != nil {
		t.Fatalf("list clusters failed: %v", err)
	}
	if total != 1 || len(items) != 1 {
		t.Fatalf("expected one cluster, got total=%d len=%d", total, len(items))
	}
	if items[0].RoutingRuleID == nil || *items[0].RoutingRuleID != rule.ID {
		t.Fatalf("expected routing rule id %d, got %+v", rule.ID, items[0].RoutingRuleID)
	}
	if items[0].RoutingConfidence <= 0 {
		t.Fatalf("expected routing confidence, got %+v", items[0])
	}
	if len(items[0].RoutingEvidence) == 0 {
		t.Fatalf("expected routing evidence, got %+v", items[0])
	}
}
