package retrieval

import (
	"sort"
	"time"

	"bug-agent/internal/model"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

func SeedDefaultPlugins(db *gorm.DB) error {
	if db == nil {
		return nil
	}

	var projectIDs []uint
	if err := db.Model(&model.Project{}).Pluck("id", &projectIDs).Error; err != nil {
		return err
	}

	now := time.Now()
	for _, projectID := range projectIDs {
		plugins := []model.RetrieverPlugin{
			{
				ProjectID:   projectID,
				Name:        "repo_wiki",
				DisplayName: "repo-wiki 代码智能检索",
				Description: "基于 repo-wiki 的语义代码搜索、调用链定位和源码上下文检索",
				Config:      `{"endpoint":"http://127.0.0.1:8766","repo":"","branch":"","topK":10,"timeoutMs":8000,"searchPath":"/search_symbols","expandDepth":1,"rewrite":true}`,
				Enabled:     true,
				SortOrder:   0,
				IsBuiltIn:   true,
				CreatedAt:   now,
				UpdatedAt:   now,
			},
			{
				ProjectID:   projectID,
				Name:        "keyword",
				DisplayName: "仓库关键词检索",
				Description: "基于文件名和内容的本地关键词匹配，作为智能检索失败后的兜底",
				Config:      "{}",
				Enabled:     true,
				SortOrder:   10,
				IsBuiltIn:   true,
				CreatedAt:   now,
				UpdatedAt:   now,
			},
			{
				ProjectID:   projectID,
				Name:        "rag",
				DisplayName: "RAG 语义检索",
				Description: "基于外部向量库的语义检索",
				Config:      "{}",
				Enabled:     false,
				SortOrder:   20,
				IsBuiltIn:   true,
				CreatedAt:   now,
				UpdatedAt:   now,
			},
			{
				ProjectID:   projectID,
				Name:        "requirement",
				DisplayName: "需求文档检索",
				Description: "从需求文档中检索相关上下文",
				Config:      "{}",
				Enabled:     false,
				SortOrder:   30,
				IsBuiltIn:   true,
				CreatedAt:   now,
				UpdatedAt:   now,
			},
		}
		if err := db.Clauses(clause.OnConflict{
			Columns:   []clause.Column{{Name: "project_id"}, {Name: "name"}},
			DoNothing: true,
		}).Create(&plugins).Error; err != nil {
			return err
		}
		if err := NormalizePluginSortOrders(db, projectID); err != nil {
			return err
		}
	}
	return nil
}

func NormalizePluginSortOrders(db *gorm.DB, projectID uint) error {
	if db == nil || projectID == 0 {
		return nil
	}

	var plugins []model.RetrieverPlugin
	if err := db.Where("project_id = ?", projectID).Order("sort_order ASC, id ASC").Find(&plugins).Error; err != nil {
		return err
	}
	if len(plugins) <= 1 {
		return nil
	}

	sort.SliceStable(plugins, func(i, j int) bool {
		if plugins[i].SortOrder != plugins[j].SortOrder {
			return plugins[i].SortOrder < plugins[j].SortOrder
		}
		ip, iok := builtinSortPriority(plugins[i].Name)
		jp, jok := builtinSortPriority(plugins[j].Name)
		if iok != jok {
			return iok
		}
		if iok && ip != jp {
			return ip < jp
		}
		return plugins[i].ID < plugins[j].ID
	})

	for idx := range plugins {
		nextOrder := idx * 10
		if plugins[idx].SortOrder == nextOrder {
			continue
		}
		if err := db.Model(&model.RetrieverPlugin{}).
			Where("id = ? AND project_id = ?", plugins[idx].ID, projectID).
			Updates(map[string]interface{}{
				"sort_order": nextOrder,
				"updated_at": time.Now(),
			}).Error; err != nil {
			return err
		}
	}
	return nil
}

func builtinSortPriority(name string) (int, bool) {
	switch name {
	case "repo_wiki":
		return 0, true
	case "keyword":
		return 10, true
	case "rag":
		return 20, true
	case "requirement":
		return 30, true
	default:
		return 0, false
	}
}
