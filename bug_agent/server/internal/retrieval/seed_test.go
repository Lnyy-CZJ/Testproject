package retrieval

import (
	"testing"

	"bug-agent/internal/model"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func TestNormalizePluginSortOrdersResolvesDuplicateBuiltinOrders(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	if err := db.AutoMigrate(&model.RetrieverPlugin{}); err != nil {
		t.Fatalf("migrate: %v", err)
	}

	plugins := []model.RetrieverPlugin{
		{ProjectID: 1, Name: "keyword", DisplayName: "keyword", SortOrder: 0},
		{ProjectID: 1, Name: "repo_wiki", DisplayName: "repo-wiki", SortOrder: 0},
		{ProjectID: 1, Name: "rag", DisplayName: "rag", SortOrder: 1},
		{ProjectID: 1, Name: "requirement", DisplayName: "requirement", SortOrder: 2},
	}
	if err := db.Create(&plugins).Error; err != nil {
		t.Fatalf("seed plugins: %v", err)
	}

	if err := NormalizePluginSortOrders(db, 1); err != nil {
		t.Fatalf("normalize: %v", err)
	}

	var got []model.RetrieverPlugin
	if err := db.Where("project_id = ?", 1).Order("sort_order ASC").Find(&got).Error; err != nil {
		t.Fatalf("query plugins: %v", err)
	}

	wantNames := []string{"repo_wiki", "keyword", "rag", "requirement"}
	for i, plugin := range got {
		if plugin.Name != wantNames[i] {
			t.Fatalf("index %d: expected %s, got %s", i, wantNames[i], plugin.Name)
		}
		if plugin.SortOrder != i*10 {
			t.Fatalf("index %d: expected sort order %d, got %d", i, i*10, plugin.SortOrder)
		}
	}
}
