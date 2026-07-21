package service

import (
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"context"
	"os"
	"path/filepath"
	"strings"
	"time"

	"gorm.io/gorm"
)

type RepoCleanupService struct {
	db *gorm.DB
}

func NewRepoCleanupService(db *gorm.DB) *RepoCleanupService {
	return &RepoCleanupService{db: db}
}

func StartRepoCleanupLoop(ctx context.Context, db *gorm.DB) {
	svc := NewRepoCleanupService(db)
	go func() {
		ticker := time.NewTicker(time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if _, err := svc.CleanOrphanedRepos(ctx); err != nil {
					logger.Errorf("[RepoCleanup] scheduled cleanup failed: %v", err)
				}
			}
		}
	}()
}

func (s *RepoCleanupService) CleanOrphanedRepos(ctx context.Context) (int, error) {
	cutoff := time.Now().Add(-24 * time.Hour)

	var repos []model.DefectRepo
	if err := s.db.Where("status = ? AND created_at < ?", "active", cutoff).
		Where("fix_task_id IS NULL OR fix_task_id NOT IN (?)",
			s.db.Model(&model.FixTask{}).Where("status IN ?", []string{"pending", "planning", "executing"}).Select("id")).
		Find(&repos).Error; err != nil {
		return 0, err
	}

	cleaned := 0
	for _, repo := range repos {
		if repo.LocalPath != "" && isPathAllowed(repo.LocalPath) {
			if err := os.RemoveAll(repo.LocalPath); err != nil {
				logger.Errorf("[RepoCleanup] failed to remove %s: %v", repo.LocalPath, err)
				continue
			}
		}
		now := time.Now()
		if err := s.db.Model(&repo).Updates(map[string]interface{}{
			"status":     "deleted",
			"deleted_at": now,
		}).Error; err != nil {
			logger.Errorf("[RepoCleanup] failed to update repo %d status: %v", repo.ID, err)
			continue
		}
		cleaned++
	}

	if cleaned > 0 {
		logger.Infof("[RepoCleanup] cleaned %d/%d orphaned repos", cleaned, len(repos))
	}

	return cleaned, nil
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
