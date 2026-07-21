package service

import (
	"bug-agent/internal/model"
	"fmt"
	"bug-agent/pkg/logger"
	"strings"
	"time"

	"gorm.io/gorm"
)

type ManualFixService struct {
	db *gorm.DB
}

func NewManualFixService(db *gorm.DB) *ManualFixService {
	return &ManualFixService{db: db}
}

type CompleteManualFixRequest struct {
	Description string `json:"description" binding:"required"`
	PRURL       string `json:"prUrl"`
	FixBranch   string `json:"fixBranch"`
}

func (s *ManualFixService) StartManualFix(defectID uint, userID uint) error {
	var defect model.Defect
	if err := s.db.Preload("Iteration").First(&defect, defectID).Error; err != nil {
		return fmt.Errorf("缺陷不存在: %w", err)
	}

	if defect.Status != model.DefectStatusPendingFix {
		return fmt.Errorf("当前状态 %s 不允许开始人工修复，需要 pending_fix 状态", defect.Status)
	}

	fromStatus := defect.Status
	return s.db.Transaction(func(tx *gorm.DB) error {
		result := tx.Model(&model.Defect{}).Where("id = ? AND status = ?", defectID, fromStatus).Update("status", model.DefectStatusManualFixing)
		if result.Error != nil {
			return fmt.Errorf("更新状态失败: %w", result.Error)
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("状态已变更，请刷新后重试")
		}
		return tx.Create(&model.StatusChange{
			DefectID:   defectID,
			FromStatus: fromStatus,
			ToStatus:   model.DefectStatusManualFixing,
			ChangedBy:  userID,
			Comment:    "开始人工修复",
			CreatedAt:  time.Now(),
		}).Error
	})
}

func (s *ManualFixService) CompleteManualFix(defectID uint, req CompleteManualFixRequest, userID uint) error {
	var defect model.Defect
	if err := s.db.Preload("Iteration").First(&defect, defectID).Error; err != nil {
		return fmt.Errorf("缺陷不存在: %w", err)
	}

	if defect.Status != model.DefectStatusManualFixing {
		return fmt.Errorf("当前状态 %s 不允许提交人工修复完成，需要 manual_fixing 状态", defect.Status)
	}

	prNumber := ""
	repoPath := ""
	if req.PRURL != "" {
		if idx := strings.Index(req.PRURL, "/pull/"); idx >= 0 {
			afterPull := req.PRURL[idx+6:]
			if slashIdx := strings.Index(afterPull, "/"); slashIdx >= 0 {
				prNumber = afterPull[:slashIdx]
			} else {
				prNumber = afterPull
			}
		} else if idx := strings.Index(req.PRURL, "/merge_requests/"); idx >= 0 {
			afterMR := req.PRURL[idx+16:]
			if slashIdx := strings.Index(afterMR, "/"); slashIdx >= 0 {
				prNumber = afterMR[:slashIdx]
			} else {
				prNumber = afterMR
			}
		} else {
			parts := strings.Split(req.PRURL, "/")
			if len(parts) > 0 {
				prNumber = parts[len(parts)-1]
			}
		}
		repoPath = ExtractRepoPath(req.PRURL)
	}

	now := time.Now()
	fromStatus := defect.Status
	task := model.FixTask{
		TaskCode:          GenerateTaskCode(defect.Code),
		DefectID:          defectID,
		AgentType:         "manual",
		Status:            model.FixTaskStatusCompleted,
		Source:            "manual",
		ManualDescription: req.Description,
		PRURL:             req.PRURL,
		PRNumber:          prNumber,
		PRStatus:          "open",
		RepoPath:          repoPath,
		FixBranch:         req.FixBranch,
		CompletedAt:       &now,
	}

	err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&task).Error; err != nil {
			return fmt.Errorf("创建修复任务失败: %w", err)
		}
		result := tx.Model(&model.Defect{}).Where("id = ? AND status = ?", defectID, fromStatus).Update("status", model.DefectStatusPendingVerify)
		if result.Error != nil {
			return fmt.Errorf("更新状态失败: %w", result.Error)
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("状态已变更，请刷新后重试")
		}
		return tx.Create(&model.StatusChange{
			DefectID:   defectID,
			FromStatus: fromStatus,
			ToStatus:   model.DefectStatusPendingVerify,
			ChangedBy:  userID,
			Comment:    "人工修复完成",
			CreatedAt:  time.Now(),
		}).Error
	})

	if err != nil {
		return err
	}

	s.publishManualFixComment(defect, &task)
	return nil
}

func (s *ManualFixService) AbandonManualFix(defectID uint, userID uint) error {
	var defect model.Defect
	if err := s.db.First(&defect, defectID).Error; err != nil {
		return fmt.Errorf("缺陷不存在: %w", err)
	}

	if defect.Status != model.DefectStatusManualFixing {
		return fmt.Errorf("当前状态 %s 不允许放弃人工修复，需要 manual_fixing 状态", defect.Status)
	}

	fromStatus := defect.Status
	return s.db.Transaction(func(tx *gorm.DB) error {
		result := tx.Model(&model.Defect{}).Where("id = ? AND status = ?", defectID, fromStatus).Update("status", model.DefectStatusPendingFix)
		if result.Error != nil {
			return fmt.Errorf("更新状态失败: %w", result.Error)
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("状态已变更，请刷新后重试")
		}
		return tx.Create(&model.StatusChange{
			DefectID:   defectID,
			FromStatus: fromStatus,
			ToStatus:   model.DefectStatusPendingFix,
			ChangedBy:  userID,
			Comment:    "放弃人工修复",
			CreatedAt:  time.Now(),
		}).Error
	})
}

func (s *ManualFixService) UpdateFixTaskPR(defectID uint, taskID uint, prURL string) error {
	var task model.FixTask
	if err := s.db.First(&task, taskID).Error; err != nil {
		return fmt.Errorf("修复任务不存在: %w", err)
	}

	if task.DefectID != defectID {
		return fmt.Errorf("修复任务不属于该缺陷")
	}

	prNumber := ""
	repoPath := ""
	if prURL != "" {
		prNumber = extractPRNumber(prURL)
		repoPath = ExtractRepoPath(prURL)
	}

	updates := map[string]interface{}{
		"PRURL":    prURL,
		"PRNumber": prNumber,
		"RepoPath": repoPath,
	}
	if prURL != "" {
		updates["PRStatus"] = "open"
	}

	if err := s.db.Model(&model.FixTask{}).Where("id = ?", taskID).Updates(updates).Error; err != nil {
		return fmt.Errorf("更新 PR 信息失败: %w", err)
	}

	return nil
}

func extractPRNumber(prURL string) string {
	if idx := strings.Index(prURL, "/pull/"); idx >= 0 {
		afterPull := prURL[idx+6:]
		if slashIdx := strings.Index(afterPull, "/"); slashIdx >= 0 {
			return afterPull[:slashIdx]
		}
		return afterPull
	}
	if idx := strings.Index(prURL, "/merge_requests/"); idx >= 0 {
		afterMR := prURL[idx+16:]
		if slashIdx := strings.Index(afterMR, "/"); slashIdx >= 0 {
			return afterMR[:slashIdx]
		}
		return afterMR
	}
	parts := strings.Split(prURL, "/")
	if len(parts) > 0 {
		return parts[len(parts)-1]
	}
	return ""
}

func (s *ManualFixService) publishManualFixComment(defect model.Defect, task *model.FixTask) {
	content := fmt.Sprintf("🔧 **人工修复完成**\n\n**任务编号**: %s\n**修复描述**: %s\n**PR链接**: %s\n\n> 请验证修复结果。",
		task.TaskCode,
		task.ManualDescription,
		task.PRURL,
	)

	comment := model.Comment{
		DefectID:       defect.ID,
		Content:        sanitizeCommentContent(content),
		IsAgentMessage: true,
	}
	comment.UserID = resolveCommentUserID(defect)
	if !ensureCommentUserExists(s.db, comment.UserID) {
		logger.Infof("[ManualFixService] 跳过发布修复评论: actor user not found (defect=%d user=%d)", defect.ID, comment.UserID)
		return
	}

	if err := s.db.Create(&comment).Error; err != nil {
		logger.Errorf("[ManualFixService] 发布修复评论失败: %v", err)
	}
}
