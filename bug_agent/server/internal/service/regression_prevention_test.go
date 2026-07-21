package service_test

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"
	"encoding/json"
	"testing"
)

func TestRegressionPreventionService_CreateFromClusterAndVerify(t *testing.T) {
	db := setupServiceTestDB(t)

	project := testutil.CreateTestProject(t, db, "Regression Project", "RGP")
	reporter := testutil.CreateTestUser(t, db, "regression_reporter")
	owner := testutil.CreateTestUser(t, db, "regression_owner")
	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Regression Webhook",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "regression_item_seed",
		CreatedBy:    reporter.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	ingestSvc := service.NewSignalIngestService(db)
	body, _ := json.Marshal(map[string]interface{}{
		"eventId":           "evt-regression-item-1",
		"title":             "支付页崩溃",
		"description":       "用户进入支付页后白屏并崩溃",
		"platform":          "android",
		"appVersion":        "5.2.0",
		"buildNumber":       "52001",
		"fingerprint":       "fp-regression-item",
		"affectedUserCount": 8,
	})
	_, cluster, _, err := ingestSvc.Ingest(connector, "manual_sync", body)
	if err != nil {
		t.Fatalf("ingest signal failed: %v", err)
	}
	if err := db.Model(&model.IssueCluster{}).Where("id = ?", cluster.ID).Update("owner_user_id", owner.ID).Error; err != nil {
		t.Fatalf("assign cluster owner failed: %v", err)
	}

	triageSvc := service.NewSignalTriageService(db)
	convertedCluster, defect, err := triageSvc.ConvertCluster(project.ID, cluster.ID, reporter.ID)
	if err != nil {
		t.Fatalf("convert cluster failed: %v", err)
	}

	regressionSvc := service.NewRegressionPreventionService(db)
	item, err := regressionSvc.CreateFromCluster(project.ID, convertedCluster.ID, reporter.ID)
	if err != nil {
		t.Fatalf("create regression item failed: %v", err)
	}
	if item.ProjectID != project.ID {
		t.Fatalf("expected project id %d, got %d", project.ID, item.ProjectID)
	}
	if item.ClusterID == nil || *item.ClusterID != convertedCluster.ID {
		t.Fatalf("expected cluster id %d, got %#v", convertedCluster.ID, item.ClusterID)
	}
	if item.DefectID == nil || *item.DefectID != defect.ID {
		t.Fatalf("expected defect id %d, got %#v", defect.ID, item.DefectID)
	}
	if item.OwnerUserID == nil || *item.OwnerUserID != owner.ID {
		t.Fatalf("expected owner id %d, got %#v", owner.ID, item.OwnerUserID)
	}
	if item.SourceFingerprint != convertedCluster.ClusterKey {
		t.Fatalf("expected fingerprint %q, got %q", convertedCluster.ClusterKey, item.SourceFingerprint)
	}
	if item.Status != model.RegressionItemStatusDraft {
		t.Fatalf("expected default draft status, got %q", item.Status)
	}

	sameItem, err := regressionSvc.CreateFromCluster(project.ID, convertedCluster.ID, reporter.ID)
	if err != nil {
		t.Fatalf("create regression item second time failed: %v", err)
	}
	if sameItem.ID != item.ID {
		t.Fatalf("expected idempotent item id %d, got %d", item.ID, sameItem.ID)
	}

	updated, err := regressionSvc.UpdateItem(project.ID, item.ID, service.RegressionItemUpdateInput{
		Status: model.RegressionItemStatusVerified,
	})
	if err != nil {
		t.Fatalf("update regression item failed: %v", err)
	}
	if updated.LastVerifiedAt == nil {
		t.Fatalf("expected last verified at to be set")
	}
	if updated.Status != model.RegressionItemStatusVerified {
		t.Fatalf("expected verified status, got %q", updated.Status)
	}

	items, err := regressionSvc.ListItems(project.ID, service.RegressionItemListParams{
		Status: model.RegressionItemStatusVerified,
	})
	if err != nil {
		t.Fatalf("list regression items failed: %v", err)
	}
	if len(items) != 1 {
		t.Fatalf("expected one verified regression item, got %d", len(items))
	}
	if items[0].Defect == nil || items[0].Defect.Code != defect.Code {
		t.Fatalf("expected preloaded linked defect, got %+v", items[0].Defect)
	}
}
