package service

import (
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"errors"
	"sort"
	"strings"
	"sync"
	"time"

	"gorm.io/gorm"
)

const (
	cacheTTL     = 5 * time.Minute
	maxCacheSize = 10000
)

type cacheEntry struct {
	perms     []model.Permission
	expiredAt time.Time
}

type userRoleAssignment struct {
	RoleName  string `gorm:"column:role_name"`
	ScopeType string `gorm:"column:scope_type"`
	ScopeID   uint   `gorm:"column:scope_id"`
}

var platformRolePermissions = map[string][]string{
	"super_admin": {"*"},
	"admin": {
		"projects:create", "projects:read", "projects:update",
		"users:read", "users:manage",
		"rbac:manage", "audit:read", "reports:export",
		"system:settings", "notifications:send",
	},
	"member": {},
}

var projectRolePermissions = map[string][]string{
	"project_admin": {
		"projects:read", "projects:update",
		"defects:create", "defects:read", "defects:update", "defects:delete",
		"agents:analyze", "agents:read_report",
		"fix_tasks:create", "fix_tasks:update",
	},
	"developer": {
		"projects:read",
		"defects:create", "defects:read", "defects:update",
		"agents:analyze", "agents:read_report",
		"fix_tasks:create", "fix_tasks:update",
	},
	"tester": {
		"projects:read",
		"defects:create", "defects:read", "defects:update",
	},
	"viewer": {"projects:read", "defects:read", "agents:read_report"},
}

var platformRoleAliasToCanonical = map[string]string{
	"super_admin": "super_admin",
	"admin":       "admin",
	"member":      "member",
}

var projectRoleAliasToCanonical = map[string]string{
	"project_admin": "project_admin",
	"developer":     "developer",
	"tester":        "tester",
	"viewer":        "viewer",
}

var roleDisplayName = map[string]string{
	"super_admin":   "超级管理员",
	"admin":         "平台管理员",
	"member":        "成员",
	"project_admin": "项目管理员",
	"developer":     "开发人员",
	"tester":        "测试人员",
	"viewer":        "只读成员",
}

// RBACService handles role-based access control with TTL cache
type RBACService struct {
	db      *gorm.DB
	cache   map[uint]*cacheEntry
	cacheMu sync.RWMutex
	stopCh  chan struct{}
}

func NewRBACService(db *gorm.DB) *RBACService {
	svc := &RBACService{
		db:     db,
		cache:  make(map[uint]*cacheEntry),
		stopCh: make(chan struct{}),
	}
	if !asyncx.BackgroundWorkersDisabled() {
		go svc.cleanupLoop()
	}
	return svc
}

func (s *RBACService) DB() *gorm.DB { return s.db }

func (s *RBACService) Stop() {
	close(s.stopCh)
}

func (s *RBACService) cleanupLoop() {
	ticker := time.NewTicker(2 * time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			s.cacheMu.Lock()
			now := time.Now()
			for userID, entry := range s.cache {
				if now.After(entry.expiredAt) {
					delete(s.cache, userID)
				}
			}
			s.cacheMu.Unlock()
		case <-s.stopCh:
			return
		}
	}
}

func (s *RBACService) HasPermission(userID uint, permissionCode string) bool {
	perms := s.GetUserPermissions(userID)
	return hasPermissionInPermissions(perms, permissionCode)
}

func (s *RBACService) HasAnyPermission(userID uint, permissions ...string) bool {
	for _, perm := range permissions {
		if s.HasPermission(userID, perm) {
			return true
		}
	}
	return false
}

func (s *RBACService) HasRole(userID uint, roleName string) bool {
	if canonical := canonicalPlatformRole(roleName); canonical != "" {
		var user model.User
		if err := s.db.Select("platform_role").Where("id = ?", userID).First(&user).Error; err != nil {
			logger.Errorf("[RBAC] HasRole: query user platform_role failed (userID=%d): %v", userID, err)
		} else if canonicalPlatformRole(user.PlatformRole) == canonical {
			return true
		}
	}

	if canonical := canonicalProjectRole(roleName); canonical != "" {
		var count int64
		s.db.Model(&model.ProjectMember{}).
			Where("user_id = ? AND role IN ?", userID, projectRoleAliases(canonical)).
			Count(&count)
		if count > 0 {
			return true
		}
	}

	canonical := canonicalRoleName(roleName)
	if canonical == "" {
		return false
	}
	for _, assignment := range s.listAssignedRoles(userID) {
		if canonicalRoleName(assignment.RoleName) == canonical {
			return true
		}
	}
	return false
}

func (s *RBACService) HasScopedRole(userID uint, roleName string, scopeType string, scopeID uint) bool {
	canonical := canonicalRoleName(roleName)
	if canonical == "" {
		return false
	}

	if scopeType == "global" {
		if canonicalPlatformRole(roleName) != "" {
			var user model.User
			if err := s.db.Select("platform_role").Where("id = ?", userID).First(&user).Error; err == nil {
				if canonicalPlatformRole(user.PlatformRole) == canonical {
					return true
				}
			}
		}
	}

	if scopeType == "project" && canonicalProjectRole(roleName) != "" {
		var count int64
		s.db.Model(&model.ProjectMember{}).
			Where("user_id = ? AND project_id = ? AND role IN ?", userID, scopeID, projectRoleAliases(canonical)).
			Count(&count)
		if count > 0 {
			return true
		}
	}

	for _, assignment := range s.listAssignedRoles(userID) {
		if canonicalRoleName(assignment.RoleName) != canonical {
			continue
		}
		if scopeType == "global" && assignment.ScopeType == "global" {
			return true
		}
		if scopeType == "project" {
			if assignment.ScopeType == "global" {
				return true
			}
			if assignment.ScopeType == "project" && assignment.ScopeID == scopeID {
				return true
			}
		}
	}

	return false
}

func (s *RBACService) IsAdmin(userID uint) bool {
	var user model.User
	if err := s.db.Select("platform_role").Where("id = ?", userID).First(&user).Error; err != nil {
		logger.Errorf("[RBAC] IsAdmin: query user failed (userID=%d): %v", userID, err)
	} else if role := canonicalPlatformRole(user.PlatformRole); role == "super_admin" || role == "admin" {
		return true
	}

	var projectAdminCount int64
	s.db.Model(&model.ProjectMember{}).
		Where("user_id = ? AND role IN ?", userID, projectRoleAliases("project_admin")).
		Count(&projectAdminCount)
	if projectAdminCount > 0 {
		return true
	}

	for _, assignment := range s.listAssignedRoles(userID) {
		switch canonicalRoleName(assignment.RoleName) {
		case "super_admin", "admin", "project_admin":
			return true
		}
	}
	return false
}

func (s *RBACService) GetUserPermissions(userID uint) []model.Permission {
	s.cacheMu.RLock()
	if entry, ok := s.cache[userID]; ok && time.Now().Before(entry.expiredAt) {
		cached := make([]model.Permission, len(entry.perms))
		copy(cached, entry.perms)
		s.cacheMu.RUnlock()
		return cached
	}
	s.cacheMu.RUnlock()

	codeSet := make(map[string]struct{})
	needAll := false

	var user model.User
	if err := s.db.Select("platform_role").Where("id = ?", userID).First(&user).Error; err == nil {
		if role := canonicalPlatformRole(user.PlatformRole); role != "" {
			addPermissionCodes(codeSet, platformRolePermissions[role], &needAll)
		}
	}

	var memberRoles []string
	s.db.Model(&model.ProjectMember{}).
		Distinct("role").
		Where("user_id = ?", userID).
		Pluck("role", &memberRoles)
	for _, role := range memberRoles {
		canonical := canonicalProjectRole(role)
		if canonical == "" {
			continue
		}
		addPermissionCodes(codeSet, projectRolePermissions[canonical], &needAll)
	}

	for _, assignment := range s.listAssignedRoles(userID) {
		addRolePermissionsByName(codeSet, &needAll, assignment.RoleName)
	}

	perms := s.loadPermissionsByCodes(codeSet, needAll)
	sort.Slice(perms, func(i, j int) bool {
		if perms[i].Module == perms[j].Module {
			return perms[i].Code < perms[j].Code
		}
		return perms[i].Module < perms[j].Module
	})

	s.cacheMu.Lock()
	if len(s.cache) >= maxCacheSize {
		oldestID := uint(0)
		oldestTime := time.Now()
		for uid, entry := range s.cache {
			if entry.expiredAt.Before(oldestTime) {
				oldestTime = entry.expiredAt
				oldestID = uid
			}
		}
		if oldestID != 0 {
			delete(s.cache, oldestID)
		}
	}
	cachePerms := make([]model.Permission, len(perms))
	copy(cachePerms, perms)
	s.cache[userID] = &cacheEntry{
		perms:     cachePerms,
		expiredAt: time.Now().Add(cacheTTL),
	}
	s.cacheMu.Unlock()

	return perms
}

func (s *RBACService) GetUserRoles(userID uint) []model.Role {
	roleByName := make(map[string]model.Role)

	var user model.User
	if err := s.db.Select("platform_role").Where("id = ?", userID).First(&user).Error; err == nil {
		if role := canonicalPlatformRole(user.PlatformRole); role != "" {
			roleByName[role] = model.Role{
				Name:        role,
				DisplayName: roleDisplayName[role],
				IsSystem:    true,
			}
		}
	}

	var memberRoles []string
	s.db.Model(&model.ProjectMember{}).
		Distinct("role").
		Where("user_id = ?", userID).
		Pluck("role", &memberRoles)
	for _, role := range memberRoles {
		canonical := canonicalProjectRole(role)
		if canonical == "" {
			continue
		}
		roleByName[canonical] = model.Role{
			Name:        canonical,
			DisplayName: roleDisplayName[canonical],
			IsSystem:    true,
		}
	}

	for _, assignment := range s.listAssignedRoles(userID) {
		canonical := canonicalRoleName(assignment.RoleName)
		if canonical == "" {
			continue
		}
		roleByName[canonical] = model.Role{
			Name:        canonical,
			DisplayName: roleDisplayName[canonical],
			IsSystem:    true,
		}
	}

	roles := make([]model.Role, 0, len(roleByName))
	for _, role := range roleByName {
		roles = append(roles, role)
	}
	sort.Slice(roles, func(i, j int) bool {
		return roles[i].Name < roles[j].Name
	})
	return roles
}

func (s *RBACService) AssignRole(userID uint, roleID uint, scopeType string, scopeID uint, assignedBy uint) error {
	if scopeType == "" {
		scopeType = "global"
	}

	var role model.Role
	if err := s.db.Select("id, name").First(&role, roleID).Error; err != nil {
		return err
	}

	if canonical := canonicalPlatformRole(role.Name); canonical != "" {
		if scopeType != "global" {
			return errors.New("platform role only supports global scope")
		}
		if err := s.db.Model(&model.User{}).Where("id = ?", userID).Update("platform_role", canonical).Error; err != nil {
			return err
		}
		s.InvalidateCache(userID)
		return nil
	}

	if canonical := canonicalProjectRole(role.Name); canonical != "" {
		switch scopeType {
		case "project":
			if scopeID == 0 {
				return errors.New("project role requires project scope id")
			}
			var member model.ProjectMember
			err := s.db.Where("project_id = ? AND user_id = ?", scopeID, userID).First(&member).Error
			if errors.Is(err, gorm.ErrRecordNotFound) {
				member = model.ProjectMember{ProjectID: scopeID, UserID: userID, Role: canonical}
				if err := s.db.Create(&member).Error; err != nil {
					return err
				}
			} else if err != nil {
				return err
			} else {
				member.Role = canonical
				if err := s.db.Save(&member).Error; err != nil {
					return err
				}
			}
		case "global":
			var userRole model.UserRole
			err := s.db.Where("user_id = ? AND role_id = ?", userID, roleID).First(&userRole).Error
			if errors.Is(err, gorm.ErrRecordNotFound) {
				userRole = model.UserRole{
					UserID:    userID,
					RoleID:    roleID,
					ScopeType: "global",
					ScopeID:   0,
				}
				if assignedBy > 0 {
					userRole.AssignedBy = &assignedBy
				}
				if err := s.db.Create(&userRole).Error; err != nil {
					return err
				}
			} else if err != nil {
				return err
			} else {
				userRole.ScopeType = "global"
				userRole.ScopeID = 0
				if assignedBy > 0 {
					userRole.AssignedBy = &assignedBy
				}
				if err := s.db.Save(&userRole).Error; err != nil {
					return err
				}
			}
		default:
			return errors.New("unsupported scope type")
		}

		s.InvalidateCache(userID)
		return nil
	}

	return errors.New("unsupported role")
}

func (s *RBACService) RemoveRole(userID uint, roleID uint, scopeType string, scopeID uint) error {
	var role model.Role
	if err := s.db.Select("id, name").First(&role, roleID).Error; err != nil {
		return err
	}

	if canonical := canonicalPlatformRole(role.Name); canonical != "" {
		var user model.User
		if err := s.db.Select("platform_role").Where("id = ?", userID).First(&user).Error; err == nil {
			if canonicalPlatformRole(user.PlatformRole) == canonical {
				if err := s.db.Model(&model.User{}).Where("id = ?", userID).Update("platform_role", "member").Error; err != nil {
					logger.Errorf("db operation failed: %v", err)
				}
			}
		}
		if err := s.db.Where("user_id = ? AND role_id = ?", userID, roleID).Delete(&model.UserRole{}).Error; err != nil {
			logger.Errorf("db operation failed: %v", err)
		}
		s.InvalidateCache(userID)
		return nil
	}

	if canonical := canonicalProjectRole(role.Name); canonical != "" {
		if scopeType == "project" && scopeID > 0 {
			if err := s.db.Where("project_id = ? AND user_id = ? AND role IN ?", scopeID, userID, projectRoleAliases(canonical)).
				Delete(&model.ProjectMember{}).Error; err != nil {
				logger.Errorf("[RBAC] delete project member: %v", err)
			}
		} else {
			if err := s.db.Where("user_id = ? AND role_id = ?", userID, roleID).Delete(&model.UserRole{}).Error; err != nil {
				logger.Errorf("db operation failed: %v", err)
			}
		}
		s.InvalidateCache(userID)
		return nil
	}

	return errors.New("unsupported role")
}

func (s *RBACService) InvalidateCache(userID uint) {
	s.cacheMu.Lock()
	delete(s.cache, userID)
	s.cacheMu.Unlock()
}

func (s *RBACService) GetRolesByScope(scopeType string) []model.Role {
	var roles []model.Role
	query := s.db.Where("is_system = ?", true)
	switch scopeType {
	case "global":
		query = query.Where("name IN ('super_admin', 'admin', 'member')")
	case "project":
		query = query.Where("name IN ('project_admin', 'developer', 'tester', 'viewer')")
	case "org":
		query = query.Where("1 = 0")
	}
	if err := query.Find(&roles).Error; err != nil {
		logger.Errorf("查询角色列表失败: %v", err)
	}
	return roles
}

func (s *RBACService) GetAllPermissions() map[string][]model.Permission {
	var perms []model.Permission
	if err := s.db.Order("module, code").Find(&perms).Error; err != nil {
		logger.Errorf("查询权限列表失败: %v", err)
	}

	result := make(map[string][]model.Permission)
	for _, p := range perms {
		result[p.Module] = append(result[p.Module], p)
	}
	return result
}

func (s *RBACService) HasProjectPermission(userID uint, projectID uint, permissionCode string) bool {
	if projectID == 0 {
		return s.HasPermission(userID, permissionCode)
	}

	var user model.User
	if err := s.db.Select("platform_role").Where("id = ?", userID).First(&user).Error; err == nil {
		if role := canonicalPlatformRole(user.PlatformRole); role != "" {
			if hasPermissionInCodes(platformRolePermissions[role], permissionCode) {
				return true
			}
		}
	}

	var member model.ProjectMember
	if err := s.db.Select("role").Where("user_id = ? AND project_id = ?", userID, projectID).First(&member).Error; err == nil {
		if role := canonicalProjectRole(member.Role); role != "" {
			if hasPermissionInCodes(projectRolePermissions[role], permissionCode) {
				return true
			}
		}
	}

	for _, assignment := range s.listAssignedRoles(userID) {
		roleName := canonicalRoleName(assignment.RoleName)
		if roleName == "" {
			continue
		}
		if platform := canonicalPlatformRole(roleName); platform != "" {
			if hasPermissionInCodes(platformRolePermissions[platform], permissionCode) {
				return true
			}
			continue
		}

		if assignment.ScopeType != "global" && !(assignment.ScopeType == "project" && assignment.ScopeID == projectID) {
			continue
		}
		if project := canonicalProjectRole(roleName); project != "" {
			if hasPermissionInCodes(projectRolePermissions[project], permissionCode) {
				return true
			}
		}
	}

	return false
}

func addPermissionCodes(set map[string]struct{}, codes []string, needAll *bool) {
	for _, code := range codes {
		if code == "*" {
			*needAll = true
			continue
		}
		set[code] = struct{}{}
	}
}

func addRolePermissionsByName(set map[string]struct{}, needAll *bool, roleName string) {
	if platformRole := canonicalPlatformRole(roleName); platformRole != "" {
		addPermissionCodes(set, platformRolePermissions[platformRole], needAll)
		return
	}
	if projectRole := canonicalProjectRole(roleName); projectRole != "" {
		addPermissionCodes(set, projectRolePermissions[projectRole], needAll)
	}
}

func canonicalRoleName(role string) string {
	if canonical := canonicalPlatformRole(role); canonical != "" {
		return canonical
	}
	return canonicalProjectRole(role)
}

func (s *RBACService) listAssignedRoles(userID uint) []userRoleAssignment {
	var assignments []userRoleAssignment
	if err := s.db.Table("user_roles").
		Select("roles.name AS role_name, user_roles.scope_type, user_roles.scope_id").
		Joins("JOIN roles ON user_roles.role_id = roles.id").
		Where("user_roles.user_id = ?", userID).
		Scan(&assignments).Error; err != nil {
		logger.Errorf("[RBAC] listAssignedRoles failed: %v", err)
	}
	return assignments
}

func hasPermissionInPermissions(perms []model.Permission, permissionCode string) bool {
	for _, perm := range perms {
		if perm.Code == permissionCode || perm.Code == "*" {
			return true
		}
	}
	return false
}

func hasPermissionInCodes(codes []string, permissionCode string) bool {
	for _, code := range codes {
		if code == "*" || code == permissionCode {
			return true
		}
	}
	return false
}

func canonicalPlatformRole(role string) string {
	return platformRoleAliasToCanonical[strings.ToLower(strings.TrimSpace(role))]
}

func canonicalProjectRole(role string) string {
	return projectRoleAliasToCanonical[strings.ToLower(strings.TrimSpace(role))]
}

func projectRoleAliases(canonical string) []string {
	result := make([]string, 0, 3)
	for alias, value := range projectRoleAliasToCanonical {
		if value == canonical {
			result = append(result, alias)
		}
	}
	return result
}

func (s *RBACService) loadPermissionsByCodes(codeSet map[string]struct{}, needAll bool) []model.Permission {
	if needAll {
		var all []model.Permission
		if err := s.db.Order("module, code").Find(&all).Error; err != nil {
			logger.Errorf("查询所有权限失败: %v", err)
		}
		return all
	}

	if len(codeSet) == 0 {
		return []model.Permission{}
	}

	codes := make([]string, 0, len(codeSet))
	for code := range codeSet {
		codes = append(codes, code)
	}

	var perms []model.Permission
	if err := s.db.Where("code IN ?", codes).Find(&perms).Error; err != nil {
		logger.Errorf("查询权限失败: %v", err)
	}

	exists := make(map[string]struct{}, len(perms))
	for _, perm := range perms {
		exists[perm.Code] = struct{}{}
	}
	for _, code := range codes {
		if _, ok := exists[code]; ok {
			continue
		}
		module := code
		if idx := strings.Index(code, ":"); idx > 0 {
			module = code[:idx]
		}
		perms = append(perms, model.Permission{
			Code:   code,
			Name:   code,
			Module: module,
		})
	}
	return perms
}
