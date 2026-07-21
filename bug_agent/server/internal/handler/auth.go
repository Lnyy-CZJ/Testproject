package handler

import (
	"bug-agent/pkg/logger"
	"bug-agent/internal/config"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"crypto/rand"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type AuthHandler struct {
	db *gorm.DB
}

func NewAuthHandler(db *gorm.DB) *AuthHandler { return &AuthHandler{db: db} }

type RegisterRequest struct {
	Username string `json:"username" binding:"required,min=2,max=50"`
	Email    string `json:"email" binding:"required,email"`
	Password string `json:"password" binding:"required,min=8,max=50"`
	Nickname string `json:"nickname"`
}

type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

const (
	adminCreatedPasswordMinLen     = 8
	adminCreatedPasswordDefaultLen = 16
)

func (h *AuthHandler) Register(c *gin.Context) {
	var req RegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	hashed, err := model.HashPassword(req.Password)
	if err != nil {
		response.ServerError(c, "密码加密失败")
		return
	}

	user := model.User{
		Username: req.Username,
		Email:    req.Email,
		Password: hashed,
		Nickname: req.Nickname,
	}

	var existing int64
	h.db.Model(&model.User{}).Where("username = ?", req.Username).Count(&existing)
	if existing > 0 {
		response.BadRequest(c, "用户名已存在")
		return
	}
	if req.Email != "" {
		h.db.Model(&model.User{}).Where("email = ?", req.Email).Count(&existing)
		if existing > 0 {
			response.BadRequest(c, "邮箱已存在")
			return
		}
	}

	if result := h.db.Create(&user); result.Error != nil {
		if strings.Contains(strings.ToLower(result.Error.Error()), "duplicate") || strings.Contains(strings.ToLower(result.Error.Error()), "unique") {
			response.BadRequest(c, "用户名或邮箱已存在")
		} else {
			response.ServerError(c, "创建用户失败")
		}
		return
	}

	token, err := model.GenerateToken(user.ID, user.Username, config.C.JWT.Secret, config.C.JWT.ExpireHour)
	if err != nil {
		response.ServerError(c, "token生成失败")
		return
	}

	response.Created(c, gin.H{"token": token, "user": user.PublicUser()})
}

// Login
func (h *AuthHandler) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var user model.User
	if err := h.db.Where("username = ? OR email = ?", req.Username, req.Username).First(&user).Error; err != nil {
		response.Unauthorized(c, "用户名或密码错误")
		return
	}

	if !model.CheckPassword(req.Password, user.Password) {
		response.Unauthorized(c, "用户名或密码错误")
		return
	}

	now := time.Now()
	if err := h.db.Model(&model.User{}).Where("id = ?", user.ID).Update("last_login_at", now).Error; err != nil {
		logger.Errorf("update last_login_at failed: %v", err)
	}
	user.LastLoginAt = &now

	token, err := model.GenerateToken(user.ID, user.Username, config.C.JWT.Secret, config.C.JWT.ExpireHour)
	if err != nil {
		response.ServerError(c, "token生成失败")
		return
	}

	response.Success(c, gin.H{"token": token, "user": user.PublicUser()})
}

// Logout revokes the current token by adding its JTI to the blacklist
func (h *AuthHandler) Logout(c *gin.Context) {
	jtiStr, _ := c.Get("jti")
	jti, ok := jtiStr.(string)
	if !ok || jti == "" {
		response.Success(c, nil)
		return
	}
	// Get exp from claims
	expStr, _ := c.Get("exp")
	var expiresAt time.Time
	if exp, ok := expStr.(int64); ok {
		expiresAt = time.Unix(exp, 0)
	} else {
		expiresAt = time.Now().Add(72 * time.Hour) // fallback
	}
	middleware.RevokeToken(jti, expiresAt)
	response.Success(c, nil)
}

func (h *AuthHandler) GetProfile(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var user model.User
	if err := h.db.First(&user, userID).Error; err != nil {
		response.NotFound(c, "用户不存在")
		return
	}
	response.Success(c, user.PublicUser())
}

func (h *AuthHandler) UpdateProfile(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req struct {
		Nickname   string `json:"nickname"`
		Avatar     string `json:"avatar"`
		AgentTypes string `json:"agentTypes"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	updates := map[string]interface{}{}
	if req.Nickname != "" {
		updates["nickname"] = req.Nickname
	}
	if req.Avatar != "" {
		updates["avatar"] = req.Avatar
	}
	if req.AgentTypes != "" {
		agentTypesStr, err := normalizeAgentTypes(parseAgentTypesCSV(req.AgentTypes))
		if err != nil {
			response.BadRequest(c, err.Error())
			return
		}
		updates["agent_types"] = agentTypesStr
	}

	if len(updates) > 0 {
		if err := h.db.Model(&model.User{}).Where("id = ?", userID).Updates(updates).Error; err != nil {
			response.ServerError(c, "更新用户信息失败")
			return
		}
	}

	var user model.User
	if err := h.db.First(&user, userID).Error; err != nil {
		response.ServerError(c, "查询用户信息失败")
		return
	}
	response.Success(c, user.PublicUser())
}

func (h *AuthHandler) ChangeMyPassword(c *gin.Context) {
	userID := middleware.GetUserID(c)
	if userID == 0 {
		response.Unauthorized(c, "未登录")
		return
	}

	var req struct {
		CurrentPassword string `json:"currentPassword" binding:"required"`
		NewPassword     string `json:"newPassword" binding:"required,min=8,max=50"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	if req.CurrentPassword == req.NewPassword {
		response.BadRequest(c, "新密码不能与当前密码相同")
		return
	}

	var user model.User
	if err := h.db.First(&user, userID).Error; err != nil {
		response.NotFound(c, "用户不存在")
		return
	}
	if !model.CheckPassword(req.CurrentPassword, user.Password) {
		response.BadRequest(c, "当前密码错误")
		return
	}

	hashed, err := model.HashPassword(req.NewPassword)
	if err != nil {
		response.ServerError(c, "密码加密失败")
		return
	}
	if err := h.db.Model(&model.User{}).Where("id = ?", userID).Update("password", hashed).Error; err != nil {
		response.ServerError(c, "修改密码失败")
		return
	}
	if err := h.db.Model(&model.User{}).Where("id = ?", userID).Update("must_change_password", false).Error; err != nil {
		response.ServerError(c, "修改密码失败")
		return
	}

	response.Success(c, gin.H{"success": true})
}

func (h *AuthHandler) UploadAvatar(c *gin.Context) {
	userID := middleware.GetUserID(c)
	if userID == 0 {
		response.Unauthorized(c, "未登录")
		return
	}

	file, err := c.FormFile("file")
	if err != nil {
		response.BadRequest(c, "请上传头像文件")
		return
	}
	if file.Size > 5*1024*1024 {
		response.BadRequest(c, "头像文件不能超过5MB")
		return
	}

	ext := strings.ToLower(filepath.Ext(file.Filename))
	allowedExt := map[string]bool{
		".jpg":  true,
		".jpeg": true,
		".png":  true,
		".gif":  true,
		".webp": true,
	}
	if !allowedExt[ext] {
		response.BadRequest(c, "仅支持 jpg/jpeg/png/gif/webp 格式")
		return
	}

	saveDir := filepath.Join(config.C.Server.UploadDir, "avatars")
	if err := os.MkdirAll(saveDir, 0755); err != nil {
		response.ServerError(c, "创建头像目录失败")
		return
	}

	filename := fmt.Sprintf("avatar_%d_%d%s", userID, time.Now().UnixNano(), ext)
	savePath := filepath.Join(saveDir, filename)
	if err := c.SaveUploadedFile(file, savePath); err != nil {
		response.ServerError(c, "保存头像失败")
		return
	}

	avatarURL := "/uploads/avatars/" + filename
	if err := h.db.Model(&model.User{}).Where("id = ?", userID).Update("avatar", avatarURL).Error; err != nil {
		response.ServerError(c, "更新头像失败")
		return
	}

	response.Success(c, gin.H{"avatar": avatarURL})
}

func (h *AuthHandler) ListUsers(c *gin.Context) {
	var users []model.User
	query := h.db.Model(&model.User{})

	if keyword := c.Query("keyword"); keyword != "" {
		query = query.Where("username LIKE ? OR nickname LIKE ? OR email LIKE ?",
			"%"+EscapeLike(keyword)+"%", "%"+EscapeLike(keyword)+"%", "%"+EscapeLike(keyword)+"%")
	}

	// 按AGENT类型筛选
	if agentType := c.Query("agentType"); agentType != "" {
		escaped := EscapeLike(agentType)
		query = query.Where(
			"agent_types = ? OR agent_types LIKE ? OR agent_types LIKE ? OR agent_types LIKE ?",
			escaped,
			escaped+",%",
			"%,"+escaped+",%",
			"%,"+escaped,
		)
	}
	if projectIDStr := strings.TrimSpace(c.Query("projectId")); projectIDStr != "" {
		projectID, err := strconv.ParseUint(projectIDStr, 10, 64)
		if err != nil || projectID == 0 {
			response.BadRequest(c, "无效的项目ID")
			return
		}
		subQuery := h.db.Model(&model.ProjectMember{}).
			Select("user_id").
			Where("project_id = ?", uint(projectID))
		query = query.Where("id IN (?)", subQuery)
	}

	page, size := parsePagination(c, 100)

	var total int64
	if err := query.Count(&total).Error; err != nil {
		response.ServerError(c, "查询用户总数失败")
		return
	}
	if err := query.Select("id, username, email, nickname, avatar, agent_types, platform_role, must_change_password, last_login_at, created_at, updated_at").Offset((page - 1) * size).Limit(size).Find(&users).Error; err != nil {
		response.ServerError(c, "查询用户列表失败")
		return
	}

	publicUsers := make([]map[string]interface{}, 0, len(users))
	for _, u := range users {
		publicUsers = append(publicUsers, u.PublicUser())
	}

	response.SuccessPage(c, publicUsers, total, page, size)
}

// UpdateUserAgentTypes 为用户分配AGENT身份（管理员接口）
func (h *AuthHandler) UpdateUserAgentTypes(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的用户ID")
		return
	}

	var req struct {
		AgentTypes []string `json:"agentTypes" binding:"required,min=1"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	agentTypesStr, err := normalizeAgentTypes(req.AgentTypes)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var user model.User
	if err := h.db.First(&user, id).Error; err != nil {
		response.NotFound(c, "用户不存在")
		return
	}

	// 使用 snake_case 字段名更新
	if err := h.db.Model(&model.User{}).Where("id = ?", id).Update("agent_types", agentTypesStr).Error; err != nil {
		response.ServerError(c, "更新AGENT身份失败")
		return
	}

	if err := h.db.First(&user, id).Error; err != nil {
		response.ServerError(c, "查询用户失败")
		return
	}
	response.Success(c, user.PublicUser())
}

// UpdateMyAgentTypes 更新当前用户的AGENT身份
func (h *AuthHandler) UpdateMyAgentTypes(c *gin.Context) {
	userID := middleware.GetUserID(c)
	if userID == 0 {
		response.Unauthorized(c, "未登录")
		return
	}

	var req struct {
		AgentTypes []string `json:"agentTypes" binding:"required,min=1"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	agentTypesStr, err := normalizeAgentTypes(req.AgentTypes)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	if err := h.db.Model(&model.User{}).Where("id = ?", userID).Update("agent_types", agentTypesStr).Error; err != nil {
		response.ServerError(c, "更新AGENT身份失败")
		return
	}

	var user model.User
	if err := h.db.First(&user, userID).Error; err != nil {
		response.ServerError(c, "查询用户失败")
		return
	}
	response.Success(c, user.PublicUser())
}

func (h *AuthHandler) GetUser(c *gin.Context) {
	id, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	var user model.User
	if err := h.db.First(&user, id).Error; err != nil {
		response.NotFound(c, "用户不存在")
		return
	}
	response.Success(c, user.PublicUser())
}

func (h *AuthHandler) CreateUser(c *gin.Context) {
	currentUserID := getUserID(c)
	if !isPlatformAdmin(h.db, currentUserID) {
		response.Forbidden(c, "仅管理员可创建用户")
		return
	}

	var req struct {
		Username     string `json:"username" binding:"required,min=2,max=50"`
		Email        string `json:"email" binding:"required,email"`
		Password     string `json:"password"`
		Nickname     string `json:"nickname"`
		PlatformRole string `json:"platformRole"`
		ProjectIDs   []uint `json:"projectIds"`
		ProjectRole  string `json:"projectRole"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	platformRole := req.PlatformRole
	if platformRole == "" {
		platformRole = "member"
	}
	validPlatformRoles := map[string]bool{
		"super_admin": true,
		"admin":       true,
		"member":      true,
	}
	if !validPlatformRoles[platformRole] {
		response.BadRequest(c, "无效的平台角色")
		return
	}

	projectRole := req.ProjectRole
	if projectRole == "" {
		projectRole = "developer"
	}
	projectRole, ok := normalizeProjectRole(projectRole)
	if !ok {
		response.BadRequest(c, "无效的项目角色")
		return
	}

	plainPassword := strings.TrimSpace(req.Password)
	generatedPassword := ""
	if plainPassword == "" {
		pw, genErr := generateSecurePassword(adminCreatedPasswordDefaultLen)
		if genErr != nil {
			response.ServerError(c, "生成随机密码失败")
			return
		}
		plainPassword = pw
		generatedPassword = pw
	} else if len(plainPassword) < adminCreatedPasswordMinLen {
		response.BadRequest(c, "管理员创建用户密码长度至少8位，或留空自动生成")
		return
	}

	hashed, err := model.HashPassword(plainPassword)
	if err != nil {
		response.ServerError(c, "密码加密失败")
		return
	}

	user := model.User{
		Username:           req.Username,
		Email:              req.Email,
		Password:           hashed,
		Nickname:           req.Nickname,
		PlatformRole:       platformRole,
		MustChangePassword: generatedPassword != "",
	}

	err = h.db.Transaction(func(tx *gorm.DB) error {
		var existing int64
		tx.Model(&model.User{}).Where("username = ?", req.Username).Count(&existing)
		if existing > 0 {
			return fmt.Errorf("用户名已存在")
		}
		if req.Email != "" {
			tx.Model(&model.User{}).Where("email = ?", req.Email).Count(&existing)
			if existing > 0 {
				return fmt.Errorf("邮箱已存在")
			}
		}

		if result := tx.Create(&user); result.Error != nil {
			if strings.Contains(strings.ToLower(result.Error.Error()), "duplicate") || strings.Contains(strings.ToLower(result.Error.Error()), "unique") {
				return fmt.Errorf("用户名或邮箱已存在")
			}
			return result.Error
		}

		if len(req.ProjectIDs) > 0 {
			uniqueProjectIDs := make([]uint, 0, len(req.ProjectIDs))
			seen := make(map[uint]bool)
			for _, pid := range req.ProjectIDs {
				if pid == 0 || seen[pid] {
					continue
				}
				seen[pid] = true
				uniqueProjectIDs = append(uniqueProjectIDs, pid)
			}

			if len(uniqueProjectIDs) > 0 {
				var count int64
				if err := tx.Model(&model.Project{}).Where("id IN ?", uniqueProjectIDs).Count(&count).Error; err != nil {
					return fmt.Errorf("校验项目失败: %w", err)
				}
				if count != int64(len(uniqueProjectIDs)) {
					return fmt.Errorf("包含不存在的项目")
				}

				for _, projectID := range uniqueProjectIDs {
					member := model.ProjectMember{
						ProjectID: projectID,
						UserID:    user.ID,
						Role:      projectRole,
					}
					if err := tx.Create(&member).Error; err != nil {
						return fmt.Errorf("分配项目失败: %w", err)
					}
				}
			}
		}
		return nil
	})
	if err != nil {
		if strings.Contains(err.Error(), "已存在") || strings.Contains(err.Error(), "不存在") {
			response.BadRequest(c, err.Error())
		} else {
			response.ServerError(c, "创建用户失败")
		}
		return
	}

	data := gin.H{
		"id":           user.ID,
		"username":     user.Username,
		"email":        user.Email,
		"nickname":     user.Nickname,
		"avatar":       user.Avatar,
		"agentTypes":   user.AgentTypes,
		"platformRole": user.PlatformRole,
		"invitedBy":    user.InvitedBy,
		"createdAt":    user.CreatedAt,
		"updatedAt":    user.UpdatedAt,
	}
	if generatedPassword != "" {
		data["temporaryPassword"] = generatedPassword
	}

	sendWelcomeNotification(h.db, user, generatedPassword)

	response.Created(c, data)
}

func (h *AuthHandler) ResetUserPassword(c *gin.Context) {
	currentUserID := getUserID(c)
	if !isPlatformAdmin(h.db, currentUserID) {
		response.Forbidden(c, "仅管理员可重置密码")
		return
	}

	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || id == 0 {
		response.BadRequest(c, "无效的用户ID")
		return
	}

	var user model.User
	if err := h.db.First(&user, uint(id)).Error; err != nil {
		response.NotFound(c, "用户不存在")
		return
	}

	temporaryPassword, err := generateSecurePassword(adminCreatedPasswordDefaultLen)
	if err != nil {
		response.ServerError(c, "生成随机密码失败")
		return
	}
	hashed, err := model.HashPassword(temporaryPassword)
	if err != nil {
		response.ServerError(c, "密码加密失败")
		return
	}

	if err := h.db.Model(&model.User{}).Where("id = ?", user.ID).Updates(map[string]interface{}{
		"password":             hashed,
		"must_change_password": true,
	}).Error; err != nil {
		response.ServerError(c, "重置密码失败")
		return
	}

	sendPasswordResetNotification(h.db, user, temporaryPassword)

	response.Success(c, gin.H{
		"id":                 user.ID,
		"mustChangePassword": true,
	})
}

func sendSystemNotification(db *gorm.DB, user model.User, title, content, source string) {
	notifyCfg := &model.NotificationConfig{
		SMTPHost:      config.C.Notification.SMTPHost,
		SMTPPort:      config.C.Notification.SMTPPort,
		SMTPUser:      config.C.Notification.SMTPUser,
		SMTPPassword:  config.C.Notification.SMTPPassword,
		SMTPFrom:      config.C.Notification.SMTPFrom,
		WebhookURL:    config.C.Notification.WebhookURL,
		WebhookSecret: config.C.Notification.WebhookSecret,
	}
	notifySvc := service.NewNotificationService(db, notifyCfg)

	reqBase := &service.NotifyRequest{
		UserIDs:  []uint{user.ID},
		Title:    title,
		Content:  content,
		Category: "system_announce",
		Metadata: map[string]interface{}{
			"userId":   user.ID,
			"username": user.Username,
			"source":   source,
		},
	}

	inAppReq := *reqBase
	inAppReq.Type = "in_app"
	_, _ = notifySvc.Send(&inAppReq)

	emailReq := *reqBase
	emailReq.Type = "email"
	_, _ = notifySvc.Send(&emailReq)
}

func sendPasswordResetNotification(db *gorm.DB, user model.User, temporaryPassword string) {
	title := "密码已重置"
	content := fmt.Sprintf("你的密码已被管理员重置，请尽快登录并修改密码。")
	sendSystemNotification(db, user, title, content, "admin_reset_password")
}

func sendWelcomeNotification(db *gorm.DB, user model.User, temporaryPassword string) {
	title := "欢迎加入 BugAgent"
	content := fmt.Sprintf("管理员已为你创建账号：%s。请尽快登录并修改密码。", user.Username)
	if temporaryPassword != "" {
		content += "你的初始密码已由管理员通过安全渠道发放。"
	}
	sendSystemNotification(db, user, title, content, "admin_create_user")
}

func generateSecurePassword(length int) (string, error) {
	if length < adminCreatedPasswordMinLen {
		length = adminCreatedPasswordMinLen
	}

	lowers := "abcdefghijkmnopqrstuvwxyz"
	uppers := "ABCDEFGHJKLMNPQRSTUVWXYZ"
	digits := "23456789"
	symbols := "!@#$%^&*_-"

	requiredSets := []string{lowers, uppers, digits, symbols}
	all := strings.Join(requiredSets, "")
	password := make([]byte, 0, length)

	for _, set := range requiredSets {
		idx, err := randomInt(len(set))
		if err != nil {
			return "", err
		}
		password = append(password, set[idx])
	}

	for len(password) < length {
		idx, err := randomInt(len(all))
		if err != nil {
			return "", err
		}
		password = append(password, all[idx])
	}

	for i := len(password) - 1; i > 0; i-- {
		j, err := randomInt(i + 1)
		if err != nil {
			return "", err
		}
		password[i], password[j] = password[j], password[i]
	}

	return string(password), nil
}

func randomInt(max int) (int, error) {
	n, err := rand.Int(rand.Reader, big.NewInt(int64(max)))
	if err != nil {
		return 0, err
	}
	return int(n.Int64()), nil
}

func normalizeAgentTypes(agentTypes []string) (string, error) {
	seen := make(map[string]struct{}, len(agentTypes))
	normalized := make([]string, 0, len(agentTypes))

	for _, t := range agentTypes {
		value := strings.ToLower(strings.TrimSpace(t))
		if value == "" {
			continue
		}
		if !allowedAgentTypeSet[value] {
			return "", fmt.Errorf("无效的AGENT类型: %s", value)
		}
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		normalized = append(normalized, value)
	}

	if len(normalized) == 0 {
		return "", fmt.Errorf("请至少选择一个AGENT类型")
	}
	return strings.Join(normalized, ","), nil
}

func parseAgentTypesCSV(raw string) []string {
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		value := strings.TrimSpace(part)
		if value == "" {
			continue
		}
		result = append(result, value)
	}
	return result
}

func (h *AuthHandler) UpdateUserPlatformRole(c *gin.Context) {
	currentUserID := getUserID(c)
	if !isPlatformAdmin(h.db, currentUserID) {
		response.Forbidden(c, "仅管理员可修改平台角色")
		return
	}

	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的用户ID")
		return
	}
	var req struct {
		PlatformRole string `json:"platformRole" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	validRoles := map[string]bool{"super_admin": true, "admin": true, "member": true}
	if !validRoles[req.PlatformRole] {
		response.BadRequest(c, "无效的平台角色")
		return
	}
	result := h.db.Model(&model.User{}).Where("id = ?", id).Update("platform_role", req.PlatformRole)
	if result.Error != nil {
		response.ServerError(c, "更新平台角色失败")
		return
	}
	if result.RowsAffected == 0 {
		response.NotFound(c, "用户不存在")
		return
	}
	middleware.InvalidateRBACCache(uint(id))
	response.Success(c, gin.H{"message": "平台角色已更新"})
}
