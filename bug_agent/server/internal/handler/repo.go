package handler

import (
	"bug-agent/internal/model"
	"bug-agent/pkg/response"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type RepoHandler struct {
	db *gorm.DB
}

func NewRepoHandler(db *gorm.DB) *RepoHandler {
	return &RepoHandler{db: db}
}

func (h *RepoHandler) ListDefectRepos(c *gin.Context) {
	defectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}

	var repos []model.DefectRepo
	if err := h.db.Where("defect_id = ?", defectID).Order("created_at DESC").Find(&repos).Error; err != nil {
		response.ServerError(c, "查询仓库列表失败")
		return
	}

	response.Success(c, repos)
}

func (h *RepoHandler) DeleteDefectRepo(c *gin.Context) {
	defectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	repoID, err := parsePathUintParam(c, "repoId")
	if err != nil {
		response.BadRequest(c, "无效的仓库 ID")
		return
	}

	var repo model.DefectRepo
	if err := h.db.Where("id = ? AND defect_id = ?", repoID, defectID).First(&repo).Error; err != nil {
		response.NotFound(c, "仓库记录不存在")
		return
	}

	if repo.Status == "deleted" {
		response.BadRequest(c, "仓库已被删除")
		return
	}

	if !isPathAllowed(repo.LocalPath) {
		response.BadRequest(c, "仓库路径不合法")
		return
	}

	if repo.LocalPath != "" {
		os.RemoveAll(repo.LocalPath)
	}

	now := time.Now()
	h.db.Model(&repo).Updates(map[string]interface{}{
		"status":     "deleted",
		"deleted_at": now,
	})

	response.Success(c, gin.H{"message": "仓库已清理"})
}

func (h *RepoHandler) ListOrphanedRepos(c *gin.Context) {
	cutoff := time.Now().Add(-24 * time.Hour)

	var repos []model.DefectRepo
	h.db.Where("status = ? AND created_at < ?", "active", cutoff).
		Where("fix_task_id IS NULL OR fix_task_id NOT IN (?)",
			h.db.Model(&model.FixTask{}).Where("status IN ?", []string{"pending", "planning", "executing"}).Select("id")).
		Find(&repos)

	response.Success(c, repos)
}

func (h *RepoHandler) TriggerCleanup(c *gin.Context) {
	cutoff := time.Now().Add(-24 * time.Hour)

	var repos []model.DefectRepo
	h.db.Where("status = ? AND created_at < ?", "active", cutoff).Find(&repos)

	cleaned := 0
	for _, repo := range repos {
		if repo.LocalPath != "" && isPathAllowed(repo.LocalPath) {
			os.RemoveAll(repo.LocalPath)
		}
		now := time.Now()
		h.db.Model(&repo).Updates(map[string]interface{}{
			"status":     "deleted",
			"deleted_at": now,
		})
		cleaned++
	}

	response.Success(c, gin.H{"cleaned": cleaned, "total": len(repos)})
}

func isPathAllowed(path string) bool {
	if path == "" {
		return false
	}
	allowedPrefixes := []string{"/data/bug-agent/repos", "/tmp/bug-agent"}
	if baseDir := strings.TrimSpace(os.Getenv("BUG_AGENT_REPO_BASE_DIR")); baseDir != "" {
		allowedPrefixes = append(allowedPrefixes, baseDir)
	}
	cleanPath := filepath.Clean(path)
	for _, prefix := range allowedPrefixes {
		cleanPrefix := filepath.Clean(prefix)
		if cleanPath == cleanPrefix || strings.HasPrefix(cleanPath, cleanPrefix+string(os.PathSeparator)) {
			return true
		}
	}
	return false
}
