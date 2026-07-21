package service_test

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"
	"encoding/json"
	"testing"
	"time"
)

func TestSignalIngestService_AppliesRoutingRuleToNewCluster(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Routing Project", "RTP")
	owner := testutil.CreateTestUser(t, db, "routing_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Bugly Android",
		Type:         model.ConnectorTypeBugly,
		Status:       model.ConnectorStatusActive,
		InboundToken: "sig_routing_1",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	module, err := routingSvc.CreateModule(project.ID, service.ProjectModuleInput{
		Name:        "启动链路",
		Code:        "startup",
		OwnerUserID: &owner.ID,
	})
	if err != nil {
		t.Fatalf("create module failed: %v", err)
	}
	if _, err := routingSvc.CreateRule(project.ID, service.IssueRoutingRuleInput{
		MatchType:        "platform",
		MatchValue:       "android",
		ModuleID:         &module.ID,
		PriorityOverride: "P0",
		SeverityOverride: "fatal",
		Enabled:          true,
		SortOrder:        1,
	}); err != nil {
		t.Fatalf("create routing rule failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	body, _ := json.Marshal(map[string]interface{}{
		"eventId":         "bugly-startup-1",
		"title":           "启动崩溃",
		"description":     "Android 正式包启动后闪退",
		"platform":        "android",
		"appVersion":      "5.0.0",
		"fingerprint":     "startup-fp",
		"occurrenceCount": 5,
	})

	signal, cluster, _, err := ingestSvc.Ingest(connector, "manual_sync", body)
	if err != nil {
		t.Fatalf("ingest signal failed: %v", err)
	}
	if signal == nil || cluster == nil {
		t.Fatalf("expected signal and cluster to be created")
	}
	if cluster.ModuleID == nil || *cluster.ModuleID != module.ID {
		t.Fatalf("expected cluster module %d, got %#v", module.ID, cluster.ModuleID)
	}
	if cluster.OwnerUserID == nil || *cluster.OwnerUserID != owner.ID {
		t.Fatalf("expected cluster owner %d, got %#v", owner.ID, cluster.OwnerUserID)
	}
	if cluster.Priority != "P0" {
		t.Fatalf("expected priority override P0, got %q", cluster.Priority)
	}
	if cluster.Severity != "fatal" {
		t.Fatalf("expected severity override fatal, got %q", cluster.Severity)
	}
}

func TestProjectRoutingService_ListClusterReleaseMatches_PrefersExactBuild(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Release Match Project", "RMP")
	owner := testutil.CreateTestUser(t, db, "release_match_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Aliyun Logs",
		Type:         model.ConnectorTypeAliyun,
		Status:       model.ConnectorStatusActive,
		InboundToken: "release_match_exact",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	body, _ := json.Marshal(map[string]interface{}{
		"eventId":           "evt-release-exact-1",
		"title":             "启动崩溃",
		"description":       "Android 正式包启动后闪退",
		"platform":          "android",
		"appVersion":        "5.0.0",
		"buildNumber":       "50002",
		"fingerprint":       "release-fp-exact",
		"affectedUserCount": 7,
		"occurrenceCount":   9,
	})
	_, cluster, _, err := ingestSvc.Ingest(connector, "manual_sync", body)
	if err != nil {
		t.Fatalf("ingest signal failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	if _, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "5.0.0",
		BuildNumber: "50001",
		Channel:     "gray",
		ReleaseTime: time.Date(2026, 4, 12, 10, 0, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("create older release failed: %v", err)
	}
	expected, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "5.0.0",
		BuildNumber: "50002",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 12, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create expected release failed: %v", err)
	}

	matches, err := routingSvc.ListClusterReleaseMatches(project.ID, cluster.ID)
	if err != nil {
		t.Fatalf("list cluster release matches failed: %v", err)
	}
	if len(matches) != 1 {
		t.Fatalf("expected 1 release match, got %d", len(matches))
	}
	if matches[0].Release.ID != expected.ID {
		t.Fatalf("expected release %d, got %d", expected.ID, matches[0].Release.ID)
	}
	if matches[0].MatchMode != "exact_build" {
		t.Fatalf("expected exact_build match mode, got %q", matches[0].MatchMode)
	}
	if matches[0].SignalCount != 1 {
		t.Fatalf("expected signal count 1, got %d", matches[0].SignalCount)
	}
	if matches[0].AffectedUserCount != 7 {
		t.Fatalf("expected affected user count 7, got %d", matches[0].AffectedUserCount)
	}
}

func TestProjectRoutingService_ListClusterReleaseMatches_FallbacksToUniqueVersion(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Release Fallback Project", "RFP")
	owner := testutil.CreateTestUser(t, db, "release_fallback_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Bugly",
		Type:         model.ConnectorTypeBugly,
		Status:       model.ConnectorStatusActive,
		InboundToken: "release_match_fallback",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	body, _ := json.Marshal(map[string]interface{}{
		"eventId":           "evt-release-fallback-1",
		"title":             "页面卡死",
		"description":       "iOS 线上版本页面卡死",
		"platform":          "ios",
		"appVersion":        "3.2.1",
		"fingerprint":       "release-fp-fallback",
		"affectedUserCount": 3,
		"occurrenceCount":   4,
	})
	_, cluster, _, err := ingestSvc.Ingest(connector, "manual_sync", body)
	if err != nil {
		t.Fatalf("ingest signal failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	expected, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "ios",
		AppVersion:  "3.2.1",
		BuildNumber: "32100",
		Channel:     "appstore",
		ReleaseTime: time.Date(2026, 4, 12, 9, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release failed: %v", err)
	}

	matches, err := routingSvc.ListClusterReleaseMatches(project.ID, cluster.ID)
	if err != nil {
		t.Fatalf("list cluster release matches failed: %v", err)
	}
	if len(matches) != 1 {
		t.Fatalf("expected 1 fallback release match, got %d", len(matches))
	}
	if matches[0].Release.ID != expected.ID {
		t.Fatalf("expected release %d, got %d", expected.ID, matches[0].Release.ID)
	}
	if matches[0].MatchMode != "app_version" {
		t.Fatalf("expected app_version match mode, got %q", matches[0].MatchMode)
	}
}

func TestProjectRoutingService_ListClusterReleaseMatches_SkipsAmbiguousVersionOnly(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Release Ambiguous Project", "RAP")
	owner := testutil.CreateTestUser(t, db, "release_ambiguous_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Webhook",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "release_match_ambiguous",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	body, _ := json.Marshal(map[string]interface{}{
		"eventId":           "evt-release-ambiguous-1",
		"title":             "接口超时",
		"description":       "Android 某版本请求超时",
		"platform":          "android",
		"appVersion":        "7.1.0",
		"fingerprint":       "release-fp-ambiguous",
		"affectedUserCount": 11,
	})
	_, cluster, _, err := ingestSvc.Ingest(connector, "manual_sync", body)
	if err != nil {
		t.Fatalf("ingest signal failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	for _, build := range []string{"71001", "71002"} {
		if _, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
			Platform:    "android",
			AppVersion:  "7.1.0",
			BuildNumber: build,
			Channel:     "prod",
			ReleaseTime: time.Date(2026, 4, 12, 8, 0, 0, 0, time.UTC),
		}); err != nil {
			t.Fatalf("create release %s failed: %v", build, err)
		}
	}

	matches, err := routingSvc.ListClusterReleaseMatches(project.ID, cluster.ID)
	if err != nil {
		t.Fatalf("list cluster release matches failed: %v", err)
	}
	if len(matches) != 0 {
		t.Fatalf("expected 0 release matches for ambiguous version-only signals, got %d", len(matches))
	}
}

func TestProjectRoutingService_ListReleaseTrends_ComputesBaselinesAndAnomalies(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Release Trend Project", "RTPR")
	owner := testutil.CreateTestUser(t, db, "release_trend_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Bugly Android",
		Type:         model.ConnectorTypeBugly,
		Status:       model.ConnectorStatusActive,
		InboundToken: "release_trend_token",
		CreatedBy:    owner.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	routingSvc := service.NewProjectRoutingService(db)
	release1, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.0.0",
		BuildNumber: "10001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 10, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release1 failed: %v", err)
	}
	release2, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.1.0",
		BuildNumber: "11001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 11, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release2 failed: %v", err)
	}
	release3, err := routingSvc.CreateRelease(project.ID, service.AppReleaseInput{
		Platform:    "android",
		AppVersion:  "1.2.0",
		BuildNumber: "12001",
		Channel:     "prod",
		ReleaseTime: time.Date(2026, 4, 12, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatalf("create release3 failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	for _, payload := range []map[string]interface{}{
		{
			"eventId":           "evt-release-trend-r1-a",
			"title":             "启动崩溃 v1",
			"platform":          "android",
			"appVersion":        "1.0.0",
			"buildNumber":       "10001",
			"fingerprint":       "fp-r1-a",
			"affectedUserCount": 3,
			"lastSeenAt":        "2026-04-10T12:00:00Z",
		},
		{
			"eventId":           "evt-release-trend-r2-a",
			"title":             "支付崩溃 v2 A",
			"platform":          "android",
			"appVersion":        "1.1.0",
			"buildNumber":       "11001",
			"fingerprint":       "fp-r2-a",
			"affectedUserCount": 5,
			"lastSeenAt":        "2026-04-11T12:00:00Z",
		},
		{
			"eventId":           "evt-release-trend-r2-b",
			"title":             "支付崩溃 v2 B",
			"platform":          "android",
			"appVersion":        "1.1.0",
			"buildNumber":       "11001",
			"fingerprint":       "fp-r2-b",
			"affectedUserCount": 3,
			"lastSeenAt":        "2026-04-11T12:30:00Z",
		},
		{
			"eventId":           "evt-release-trend-r3-a",
			"title":             "首页崩溃 v3 A",
			"platform":          "android",
			"appVersion":        "1.2.0",
			"buildNumber":       "12001",
			"fingerprint":       "fp-r3-a",
			"affectedUserCount": 8,
			"lastSeenAt":        "2026-04-12T11:00:00Z",
		},
		{
			"eventId":           "evt-release-trend-r3-b",
			"title":             "首页崩溃 v3 B",
			"platform":          "android",
			"appVersion":        "1.2.0",
			"buildNumber":       "12001",
			"fingerprint":       "fp-r3-b",
			"affectedUserCount": 6,
			"lastSeenAt":        "2026-04-12T11:10:00Z",
		},
		{
			"eventId":           "evt-release-trend-r3-c",
			"title":             "首页崩溃 v3 C",
			"platform":          "android",
			"appVersion":        "1.2.0",
			"buildNumber":       "12001",
			"fingerprint":       "fp-r3-c",
			"affectedUserCount": 6,
			"lastSeenAt":        "2026-04-12T11:20:00Z",
		},
	} {
		body, _ := json.Marshal(payload)
		if _, _, _, err := ingestSvc.Ingest(connector, "manual_sync", body); err != nil {
			t.Fatalf("ingest signal failed: %v", err)
		}
	}

	items, err := routingSvc.ListReleaseTrends(project.ID)
	if err != nil {
		t.Fatalf("list release trends failed: %v", err)
	}
	if len(items) != 3 {
		t.Fatalf("expected 3 release trend items, got %d", len(items))
	}

	if items[0].Release.ID != release3.ID || items[0].PreviousRelease == nil || items[0].PreviousRelease.ID != release2.ID {
		t.Fatalf("expected latest release %d to compare with %d, got %+v", release3.ID, release2.ID, items[0])
	}
	if items[0].ClusterCount != 3 || items[0].SignalCount != 3 || items[0].AffectedUserCount != 20 {
		t.Fatalf("unexpected metrics for latest release: %+v", items[0])
	}
	if items[0].AnomalyLevel != "high" {
		t.Fatalf("expected latest release anomaly high, got %q", items[0].AnomalyLevel)
	}

	if items[1].Release.ID != release2.ID || items[1].PreviousRelease == nil || items[1].PreviousRelease.ID != release1.ID {
		t.Fatalf("expected middle release %d to compare with %d, got %+v", release2.ID, release1.ID, items[1])
	}
	if items[1].ClusterCount != 2 || items[1].AffectedUserCount != 8 {
		t.Fatalf("unexpected metrics for middle release: %+v", items[1])
	}
	if items[1].AnomalyLevel != "watch" {
		t.Fatalf("expected middle release anomaly watch, got %q", items[1].AnomalyLevel)
	}

	if items[2].Release.ID != release1.ID || items[2].PreviousRelease != nil {
		t.Fatalf("expected baseline release at tail, got %+v", items[2])
	}
	if items[2].AnomalyLevel != "baseline" {
		t.Fatalf("expected first release anomaly baseline, got %q", items[2].AnomalyLevel)
	}
}
