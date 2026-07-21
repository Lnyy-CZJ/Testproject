package handler

import (
	"strings"

	"gorm.io/gorm"

	"bug-agent/internal/model"
)

func isPlatformAdmin(db *gorm.DB, userID uint) bool {
	return hasPlatformRole(db, userID, "super_admin", "admin")
}

func hasPlatformRole(db *gorm.DB, userID uint, roles ...string) bool {
	if userID == 0 || len(roles) == 0 {
		return false
	}

	var count int64
	if err := db.Model(&model.User{}).
		Where("id = ? AND platform_role IN ?", userID, roles).
		Count(&count).Error; err != nil {
		return false
	}
	return count > 0
}

var validProjectRoles = map[string]struct{}{
	"project_admin": {},
	"developer":     {},
	"tester":        {},
	"viewer":        {},
}

func normalizeProjectRole(role string) (string, bool) {
	key := strings.ToLower(strings.TrimSpace(role))
	_, ok := validProjectRoles[key]
	return key, ok
}
