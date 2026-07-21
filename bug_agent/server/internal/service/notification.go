package service

import (
	"bug-agent/pkg/logger"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/smtp"
	"strconv"
	"strings"
	"text/template"
	"time"

	"gorm.io/gorm"
)

type NotificationService struct {
	db              *gorm.DB
	smtpCfg         *model.NotificationConfig
	tmplMap         map[string]*template.Template
	prefSvc         *NotificationPrefService
	userWebhookSvc  *UserWebhookService
	projectNotifSvc *ProjectNotificationService
}

func NewNotificationService(db *gorm.DB, cfg *model.NotificationConfig) *NotificationService {
	svc := &NotificationService{
		db:              db,
		smtpCfg:         cfg,
		tmplMap:         make(map[string]*template.Template),
		prefSvc:         NewNotificationPrefService(db),
		userWebhookSvc:  NewUserWebhookService(db),
		projectNotifSvc: NewProjectNotificationService(db),
	}
	svc.registerBuiltinTemplates()
	return svc
}

type NotifyRequest struct {
	UserIDs   []uint                 `json:"userIds"`
	Title     string                 `json:"title"`
	Content   string                 `json:"content"`
	Type      string                 `json:"type"`     // email, webhook, in_app
	Category  string                 `json:"category"` // defect_assigned, defect_status_change, defect_mention, system_announce...
	ProjectID uint                   `json:"projectId"`
	RelatedID uint                   `json:"relatedId"`
	Metadata  map[string]interface{} `json:"metadata"`
}

type DefectNotifyContext struct {
	DefectCode  string
	DefectTitle string
	FromStatus  string
	ToStatus    string
	ChangedBy   string
	Comment     string
	ProjectName string
	URL         string
}

func (s *NotificationService) Send(req *NotifyRequest) ([]*model.Notification, error) {
	var notifications []*model.Notification
	var projectWebhook *model.ProjectWebhook
	cfg := s.resolveNotificationConfig()

	if req.ProjectID > 0 && req.Category != "" && req.Type != "" && s.projectNotifSvc != nil {
		if !s.projectNotifSvc.IsChannelEnabled(req.ProjectID, req.Category, req.Type) {
			return notifications, nil
		}
		hook, err := s.projectNotifSvc.GetSelectedWebhook(req.ProjectID, req.Category)
		if err == nil {
			projectWebhook = hook
		}
	}

	for _, userID := range req.UserIDs {
		if req.Category != "" && req.Type != "" && s.prefSvc != nil {
			if !s.prefSvc.IsEnabled(userID, req.Category, req.Type) {
				continue
			}
		}

		n := &model.Notification{
			UserID:    userID,
			Title:     req.Title,
			Content:   req.Content,
			Type:      req.Type,
			Category:  req.Category,
			Read:      false,
			RelatedID: req.RelatedID,
			CreatedAt: time.Now(),
		}
		if req.Metadata != nil {
			metaBytes, err := json.Marshal(req.Metadata)
			if err != nil {
				logger.Errorf("[Notification] marshal metadata failed: %v", err)
				metaBytes = []byte("null")
			}
			n.Metadata = string(metaBytes)
		} else {
			n.Metadata = "null"
		}

		notifications = append(notifications, n)
	}

	if len(notifications) > 0 {
		if err := s.db.CreateInBatches(notifications, 100).Error; err != nil {
			return nil, fmt.Errorf("failed to create notifications: %w", err)
		}
	}

	if req.Type == "email" && cfg != nil && cfg.SMTPHost != "" {
		asyncx.Go(func() {
			defer func() {
				if r := recover(); r != nil {
					logger.Errorf("[Notification] sendEmailAsync panic: %v", r)
				}
			}()
			s.sendEmailAsync(cfg, notifications)
		})
	}

	if req.Type == "in_app" {
		asyncx.Go(func() {
			defer func() {
				if r := recover(); r != nil {
					logger.Errorf("[Notification] dispatchUserWebhookMirrorAsync panic: %v", r)
				}
			}()
			s.dispatchUserWebhookMirrorAsync(notifications, req)
		})
	}

	if req.Type == "webhook" {
		asyncx.Go(func() {
			defer func() {
				if r := recover(); r != nil {
					logger.Errorf("[Notification] dispatchWebhookAsync panic: %v", r)
				}
			}()
			s.dispatchWebhookAsync(req)
		})
	}

	if projectWebhook != nil {
		asyncx.Go(func() {
			defer func() {
				if r := recover(); r != nil {
					logger.Errorf("[Notification] dispatchProjectWebhookAsync panic: %v", r)
				}
			}()
			s.dispatchProjectWebhookAsync(projectWebhook, req)
		})
	}

	return notifications, nil
}

func (s *NotificationService) SendDefectStatusChange(ctx *DefectNotifyContext, userIDs []uint) ([]*model.Notification, error) {
	subject := fmt.Sprintf("[BugAgent] 缺陷 %s 状态变更: %s → %s", ctx.DefectCode, ctx.FromStatus, ctx.ToStatus)
	body := s.renderTemplate("defect_status_change", ctx)
	if body == "" {
		body = fmt.Sprintf("缺陷 [%s] %s 已从 \"%s\" 变更为 \"%s\"，操作人: %s\n\n备注: %s",
			ctx.DefectCode, ctx.DefectTitle, ctx.FromStatus, ctx.ToStatus, ctx.ChangedBy, ctx.Comment)
	}

	req := &NotifyRequest{
		UserIDs:  userIDs,
		Title:    subject,
		Content:  body,
		Type:     "email",
		Category: "defect_status_change",
		Metadata: map[string]interface{}{
			"defect_code": ctx.DefectCode,
			"from_status": ctx.FromStatus,
			"to_status":   ctx.ToStatus,
			"changed_by":  ctx.ChangedBy,
		},
	}

	if ctx.DefectCode != "" {
		req.RelatedID = parseDefectID(ctx.DefectCode)
	}

	return s.Send(req)
}

func (s *NotificationService) SendAssignment(assigneeID uint, assignerName string, defectCode, defectTitle string) (*model.Notification, error) {
	subject := fmt.Sprintf("[BugAgent] 您被指派了新缺陷: %s", defectCode)
	body := fmt.Sprintf("%s 将缺陷 [%s] %s 指派给您处理，请及时查看。",
		assignerName, defectCode, defectTitle)

	req := &NotifyRequest{
		UserIDs:  []uint{assigneeID},
		Title:    subject,
		Content:  body,
		Type:     "in_app",
		Category: "defect_assigned",
		Metadata: map[string]interface{}{
			"defect_code": defectCode,
			"assigner":    assignerName,
		},
	}

	result, err := s.Send(req)
	if err != nil || len(result) == 0 {
		return nil, err
	}
	return result[0], nil
}

func (s *NotificationService) GetByUser(userID uint, page, pageSize int) ([]model.Notification, int64, error) {
	if pageSize > 100 {
		pageSize = 100
	}
	var total int64
	var list []model.Notification

	if err := s.db.Model(&model.Notification{}).Where("user_id = ?", userID).Count(&total).Error; err != nil {
		return nil, 0, fmt.Errorf("查询通知总数失败: %w", err)
	}

	offset := (page - 1) * pageSize
	err := s.db.Where("user_id = ?", userID).
		Order("created_at desc").
		Limit(pageSize).
		Offset(offset).
		Find(&list).Error

	return list, total, err
}

func (s *NotificationService) MarkRead(userID uint, notificationIDs []uint) (int64, error) {
	result := s.db.Model(&model.Notification{}).
		Where("user_id = ? AND id IN ? AND read = ?", userID, notificationIDs, false).
		Update("read", true)
	return result.RowsAffected, result.Error
}

func (s *NotificationService) MarkAllRead(userID uint) (int64, error) {
	result := s.db.Model(&model.Notification{}).
		Where("user_id = ? AND read = ?", userID, false).
		Update("read", true)
	return result.RowsAffected, result.Error
}

func (s *NotificationService) GetUnreadCount(userID uint) (int64, error) {
	var count int64
	err := s.db.Model(&model.Notification{}).
		Where("user_id = ? AND read = ?", userID, false).
		Count(&count).Error
	return count, err
}

func (s *NotificationService) sendEmailAsync(cfg *model.NotificationConfig, notifications []*model.Notification) {
	for _, n := range notifications {
		var user model.User
		if err := s.db.First(&user, n.UserID).Error; err != nil {
			logger.Errorf("[Notification] find user %d failed: %v", n.UserID, err)
			continue
		}
		if user.Email == "" {
			continue
		}

		if err := sendSMTPEmail(cfg, user.Email, n.Title, n.Content); err != nil {
			metaBytes, _ := json.Marshal(map[string]string{"send_error": err.Error()})
			if err := s.db.Model(n).Update("metadata", string(metaBytes)).Error; err != nil {
				logger.Errorf("update failed: %v", err)
			}
		} else {
			if err := s.db.Model(n).Update("email_sent_at", time.Now()).Error; err != nil {
				logger.Errorf("update email_sent_at failed: %v", err)
			}
		}
	}
}

func (s *NotificationService) resolveNotificationConfig() *model.NotificationConfig {
	base := cloneNotificationConfig(s.smtpCfg)
	if s.db == nil {
		return base
	}

	platformCfg, found, err := NewPlatformSettingsService(s.db).GetEmailNotificationConfig()
	if err != nil || !found || platformCfg == nil {
		return base
	}

	if base == nil {
		base = &model.NotificationConfig{}
	}
	if strings.TrimSpace(platformCfg.SMTPHost) != "" {
		base.SMTPHost = platformCfg.SMTPHost
	}
	if platformCfg.SMTPPort > 0 {
		base.SMTPPort = platformCfg.SMTPPort
	}
	if strings.TrimSpace(platformCfg.SMTPUser) != "" {
		base.SMTPUser = platformCfg.SMTPUser
	}
	if strings.TrimSpace(platformCfg.SMTPPassword) != "" {
		base.SMTPPassword = platformCfg.SMTPPassword
	}
	if strings.TrimSpace(platformCfg.SMTPFrom) != "" {
		base.SMTPFrom = platformCfg.SMTPFrom
	}
	return base
}

func (s *NotificationService) dispatchUserWebhookMirrorAsync(notifications []*model.Notification, req *NotifyRequest) {
	if s.userWebhookSvc == nil {
		return
	}
	for _, n := range notifications {
		resolved, found, err := s.userWebhookSvc.Resolve(n.UserID)
		if err != nil || !found || resolved == nil {
			continue
		}
		_ = dispatchWebhookRequest(resolved.URL, resolved.Secret, map[string]interface{}{
			"event":           req.Category,
			"title":           n.Title,
			"content":         n.Content,
			"user_id":         n.UserID,
			"notification_id": n.ID,
			"project_id":      req.ProjectID,
			"related_id":      req.RelatedID,
			"metadata":        req.Metadata,
			"timestamp":       time.Now().Unix(),
		})
	}
}

func (s *NotificationService) dispatchWebhookAsync(req *NotifyRequest) {
	if s.smtpCfg == nil || s.smtpCfg.WebhookURL == "" {
		return
	}

		_ = dispatchWebhookRequest(s.smtpCfg.WebhookURL, s.smtpCfg.WebhookSecret, map[string]interface{}{
			"event":     req.Category,
			"title":     req.Title,
			"content":   req.Content,
			"userIds":   req.UserIDs,
			"metadata":  req.Metadata,
			"timestamp": time.Now().Unix(),
		})
}

func (s *NotificationService) dispatchProjectWebhookAsync(hook *model.ProjectWebhook, req *NotifyRequest) {
	if hook == nil || !hook.Enabled {
		return
	}

	_ = dispatchWebhookRequest(hook.URL, hook.Secret, map[string]interface{}{
		"event":      req.Category,
		"title":      req.Title,
		"content":    req.Content,
		"user_ids":   req.UserIDs,
		"project_id": req.ProjectID,
		"related_id": req.RelatedID,
		"metadata":   req.Metadata,
		"timestamp":  time.Now().Unix(),
	})
}

func (s *NotificationService) renderTemplate(name string, data interface{}) string {
	tmpl, ok := s.tmplMap[name]
	if !ok {
		return ""
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return ""
	}
	return buf.String()
}

func (s *NotificationService) registerBuiltinTemplates() {
	s.tmplMap["defect_status_change"] = template.Must(template.New("defect_status").Parse(
		`<h2>BugAgent 缺陷状态变更通知</h2>
<p>缺陷 <strong>{{.DefectCode}}</strong>: {{.DefectTitle}}</p>
<table>
<tr><td>状态变更</td><td>{{.FromStatus}} → {{.ToStatus}}</td></tr>
<tr><td>操作人</td><td>{{.ChangedBy}}</td></tr>
{{if .Comment}}<tr><td>备注</td><td>{{.Comment}}</td></tr>{{end}}
</table>
<p><a href="{{.URL}}">查看详情</a></p>`))

	s.tmplMap["defect_assigned"] = template.Must(template.New("defect_assigned").Parse(
		`<h2>BugAgent 缺陷指派通知</h2>
<p>您被指派处理缺陷 <strong>{{.DefectCode}}</strong>: {{.DefectTitle}}</p>
<p>请及时登录系统查看并处理。</p>`))
}

func buildEmailMessage(from, to, subject, body string) string {
	var msg bytes.Buffer
	msg.WriteString(fmt.Sprintf("From: %s\r\n", from))
	msg.WriteString(fmt.Sprintf("To: %s\r\n", to))
	msg.WriteString(fmt.Sprintf("Subject: %s\r\n", subject))
	msg.WriteString("MIME-Version: 1.0\r\n")
	msg.WriteString("Content-Type: text/html; charset=UTF-8\r\n")
	msg.WriteString("\r\n")
	msg.WriteString(body)
	return msg.String()
}

func cloneNotificationConfig(cfg *model.NotificationConfig) *model.NotificationConfig {
	if cfg == nil {
		return nil
	}
	cloned := *cfg
	return &cloned
}

func sendSMTPEmail(cfg *model.NotificationConfig, to, subject, body string) error {
	if cfg == nil || strings.TrimSpace(cfg.SMTPHost) == "" {
		return errors.New("smtp host is required")
	}
	if strings.TrimSpace(to) == "" {
		return errors.New("recipient email is required")
	}

	from := strings.TrimSpace(cfg.SMTPFrom)
	if from == "" {
		from = strings.TrimSpace(cfg.SMTPUser)
	}
	if from == "" {
		return errors.New("smtp from is required")
	}

	var auth smtp.Auth
	if strings.TrimSpace(cfg.SMTPUser) != "" || strings.TrimSpace(cfg.SMTPPassword) != "" {
		if cfg.SMTPPort != 465 && cfg.SMTPPort != 587 && cfg.SMTPPort != 25 {
			logger.Warnf("[SMTP] port %d is not standard SMTPS/STARTTLS port, credentials may be sent in plaintext", cfg.SMTPPort)
		}
		auth = smtp.PlainAuth("", cfg.SMTPUser, cfg.SMTPPassword, cfg.SMTPHost)
	}

	addr := fmt.Sprintf("%s:%d", cfg.SMTPHost, cfg.SMTPPort)
	msg := buildEmailMessage(from, to, subject, body)
	return smtp.SendMail(addr, auth, from, []string{to}, []byte(msg))
}

func parseDefectID(code string) uint {
	parts := strings.Split(code, "-")
	if len(parts) >= 4 {
		id, err := strconv.ParseUint(parts[len(parts)-1], 10, 64)
		if err == nil {
			return uint(id)
		}
	}
	return 0
}

var EmailCategories = []string{
	"defect_assigned",
	"defect_status_change",
	"defect_mention",
	"defect_due_soon",
	"iteration_end",
	"system_announce",
}
var NotificationTypes = []string{"in_app", "email", "webhook"}
