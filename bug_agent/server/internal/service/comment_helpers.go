package service

import (
	"bug-agent/internal/model"
	"strings"

	"gorm.io/gorm"
)

func resolveCommentUserID(defect model.Defect, preferred ...uint) uint {
	for _, userID := range preferred {
		if userID > 0 {
			return userID
		}
	}
	if defect.AssigneeID != nil && *defect.AssigneeID > 0 {
		return *defect.AssigneeID
	}
	if defect.ReporterID > 0 {
		return defect.ReporterID
	}
	return 0
}

func ensureCommentUserExists(db *gorm.DB, userID uint) bool {
	if userID == 0 {
		return false
	}
	return db.Select("id").First(&model.User{}, userID).Error == nil
}

func sanitizeCommentContent(content string) string {
	return strings.ToValidUTF8(content, "�")
}
