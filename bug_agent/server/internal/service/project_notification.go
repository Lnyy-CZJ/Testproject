package service

import (
	"bug-agent/internal/model"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"
)

var ErrProjectNotificationWebhookNotFound = errors.New("project notification webhook not found")
var ErrInvalidProjectNotificationParams = errors.New("invalid project notification params")

var defaultProjectNotificationPolicies = []struct {
	category     string
	inAppEnabled bool
	emailEnabled bool
}{
	{category: "defect_assigned", inAppEnabled: true, emailEnabled: true},
	{category: "defect_status_change", inAppEnabled: true, emailEnabled: true},
	{category: "defect_mention", inAppEnabled: true, emailEnabled: true},
	{category: "defect_due_soon", inAppEnabled: true, emailEnabled: true},
	{category: "iteration_start", inAppEnabled: true, emailEnabled: false},
	{category: "iteration_end", inAppEnabled: true, emailEnabled: true},
	{category: "collaboration_complete", inAppEnabled: true, emailEnabled: false},
}

var projectNotificationCategoryOrder = func() map[string]int {
	order := make(map[string]int, len(defaultProjectNotificationPolicies))
	for i, item := range defaultProjectNotificationPolicies {
		order[item.category] = i
	}
	return order
}()

type ProjectNotificationPolicyInput struct {
	Category     string
	InAppEnabled bool
	EmailEnabled bool
	WebhookID    *uint
}

type ProjectWebhookInput struct {
	Name    string
	URL     string
	Secret  string
	Enabled bool
}

type ProjectNotificationService struct {
	db *gorm.DB
}

func NewProjectNotificationService(db *gorm.DB) *ProjectNotificationService {
	return &ProjectNotificationService{db: db}
}

func (s *ProjectNotificationService) GetPolicies(projectID uint) ([]model.ProjectNotificationPolicy, error) {
	if err := s.ensureDefaultPolicies(projectID); err != nil {
		return nil, err
	}

	var policies []model.ProjectNotificationPolicy
	if err := s.db.Preload("Webhook").
		Where("project_id = ?", projectID).
		Find(&policies).Error; err != nil {
		return nil, err
	}
	return sortProjectPolicies(policies), nil
}

func (s *ProjectNotificationService) BatchUpdatePolicies(projectID uint, inputs []ProjectNotificationPolicyInput) ([]model.ProjectNotificationPolicy, error) {
	if err := s.ensureDefaultPolicies(projectID); err != nil {
		return nil, err
	}

	err := s.db.Transaction(func(tx *gorm.DB) error {
		for _, input := range inputs {
			category := strings.TrimSpace(input.Category)
			if !isProjectNotificationCategory(category) {
				return ErrInvalidNotificationCategory
			}

			if input.WebhookID != nil {
				if _, err := s.getWebhook(tx, projectID, *input.WebhookID); err != nil {
					return err
				}
			}

			var policy model.ProjectNotificationPolicy
			if err := tx.Where("project_id = ? AND category = ?", projectID, category).
				Attrs(model.ProjectNotificationPolicy{
					ProjectID:    projectID,
					Category:     category,
					InAppEnabled: defaultProjectPolicyFor(category).inAppEnabled,
					EmailEnabled: defaultProjectPolicyFor(category).emailEnabled,
				}).
				FirstOrCreate(&policy).Error; err != nil {
				return err
			}

			policy.InAppEnabled = input.InAppEnabled
			policy.EmailEnabled = input.EmailEnabled
			policy.WebhookID = normalizeOptionalUint(input.WebhookID)
			if err := tx.Save(&policy).Error; err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}

	return s.GetPolicies(projectID)
}

func (s *ProjectNotificationService) ListWebhooks(projectID uint) ([]model.ProjectWebhook, error) {
	var hooks []model.ProjectWebhook
	if err := s.db.Where("project_id = ?", projectID).Order("created_at desc, id desc").Find(&hooks).Error; err != nil {
		return nil, err
	}
	for i := range hooks {
		hooks[i].HasSecret = strings.TrimSpace(hooks[i].Secret) != ""
	}
	return hooks, nil
}

func (s *ProjectNotificationService) CreateWebhook(projectID uint, input ProjectWebhookInput) (*model.ProjectWebhook, error) {
	hook := &model.ProjectWebhook{
		ProjectID: projectID,
		Name:      strings.TrimSpace(input.Name),
		URL:       strings.TrimSpace(input.URL),
		Secret:    strings.TrimSpace(input.Secret),
		Enabled:   input.Enabled,
	}
	if hook.Name == "" || hook.URL == "" {
		return nil, ErrInvalidProjectNotificationParams
	}
	if err := s.db.Create(hook).Error; err != nil {
		return nil, err
	}
	hook.HasSecret = strings.TrimSpace(hook.Secret) != ""
	return hook, nil
}

func (s *ProjectNotificationService) UpdateWebhook(projectID, webhookID uint, input ProjectWebhookInput) (*model.ProjectWebhook, error) {
	hook, err := s.getWebhook(s.db, projectID, webhookID)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(input.Name) == "" || strings.TrimSpace(input.URL) == "" {
		return nil, ErrInvalidProjectNotificationParams
	}
	hook.Name = strings.TrimSpace(input.Name)
	hook.URL = strings.TrimSpace(input.URL)
	hook.Secret = strings.TrimSpace(input.Secret)
	hook.Enabled = input.Enabled
	if err := s.db.Save(hook).Error; err != nil {
		return nil, err
	}
	hook.HasSecret = strings.TrimSpace(hook.Secret) != ""
	return hook, nil
}

func (s *ProjectNotificationService) DeleteWebhook(projectID, webhookID uint) error {
	return s.db.Transaction(func(tx *gorm.DB) error {
		if _, err := s.getWebhook(tx, projectID, webhookID); err != nil {
			return err
		}
		if err := tx.Model(&model.ProjectNotificationPolicy{}).
			Where("project_id = ? AND webhook_id = ?", projectID, webhookID).
			Update("webhook_id", nil).Error; err != nil {
			return err
		}
		return tx.Delete(&model.ProjectWebhook{}, webhookID).Error
	})
}

func (s *ProjectNotificationService) TestWebhook(projectID, webhookID uint, event string) error {
	hook, err := s.getWebhook(s.db, projectID, webhookID)
	if err != nil {
		return err
	}

	if strings.TrimSpace(event) == "" {
		event = "project_notification_test"
	}

	return dispatchWebhookRequest(hook.URL, hook.Secret, map[string]interface{}{
		"event":     event,
		"title":     "BugAgent 项目通知测试",
		"content":   "项目通知 Webhook 联通性测试成功",
		"projectId": projectID,
		"timestamp": time.Now().Unix(),
	})
}

func (s *ProjectNotificationService) IsChannelEnabled(projectID uint, category, channel string) bool {
	category = strings.TrimSpace(category)
	channel = strings.TrimSpace(channel)
	if projectID == 0 || !isProjectNotificationCategory(category) {
		return true
	}

	policy, err := s.lookupPolicy(projectID, category)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			def := defaultProjectPolicyFor(category)
			switch channel {
			case "in_app":
				return def.inAppEnabled
			case "email":
				return def.emailEnabled
			case "webhook":
				return false
			default:
				return true
			}
		}
		return true
	}

	switch channel {
	case "in_app":
		return policy.InAppEnabled
	case "email":
		return policy.EmailEnabled
	case "webhook":
		return policy.WebhookID != nil && policy.Webhook != nil && policy.Webhook.Enabled
	default:
		return true
	}
}

func (s *ProjectNotificationService) GetSelectedWebhook(projectID uint, category string) (*model.ProjectWebhook, error) {
	if projectID == 0 || !isProjectNotificationCategory(category) {
		return nil, nil
	}

	policy, err := s.lookupPolicy(projectID, category)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, nil
		}
		return nil, err
	}
	if policy.WebhookID == nil {
		return nil, nil
	}
	hook, err := s.getWebhook(s.db, projectID, *policy.WebhookID)
	if err != nil {
		return nil, err
	}
	if !hook.Enabled {
		return nil, nil
	}
	return hook, nil
}

func (s *ProjectNotificationService) ensureDefaultPolicies(projectID uint) error {
	for _, item := range defaultProjectNotificationPolicies {
		var policy model.ProjectNotificationPolicy
		if err := s.db.Where("project_id = ? AND category = ?", projectID, item.category).
			Attrs(model.ProjectNotificationPolicy{
				ProjectID:    projectID,
				Category:     item.category,
				InAppEnabled: item.inAppEnabled,
				EmailEnabled: item.emailEnabled,
			}).
			FirstOrCreate(&policy).Error; err != nil {
			return err
		}
	}
	return nil
}

func (s *ProjectNotificationService) getPolicy(projectID uint, category string) (*model.ProjectNotificationPolicy, error) {
	if err := s.ensureDefaultPolicies(projectID); err != nil {
		return nil, err
	}

	return s.lookupPolicy(projectID, category)
}

func (s *ProjectNotificationService) lookupPolicy(projectID uint, category string) (*model.ProjectNotificationPolicy, error) {
	var policy model.ProjectNotificationPolicy
	if err := s.db.Preload("Webhook").
		Where("project_id = ? AND category = ?", projectID, strings.TrimSpace(category)).
		First(&policy).Error; err != nil {
		return nil, err
	}
	return &policy, nil
}

func (s *ProjectNotificationService) getWebhook(db *gorm.DB, projectID, webhookID uint) (*model.ProjectWebhook, error) {
	var hook model.ProjectWebhook
	if err := db.Where("id = ? AND project_id = ?", webhookID, projectID).First(&hook).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrProjectNotificationWebhookNotFound
		}
		return nil, err
	}
	return &hook, nil
}

var safeWebhookClient = &http.Client{
	Timeout: 10 * time.Second,
	CheckRedirect: func(req *http.Request, via []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

func isPrivateIP(host string) bool {
	ip := net.ParseIP(host)
	if ip == nil {
		return false
	}
	privateRanges := []struct {
		network *net.IPNet
	}{
		{mustParseCIDR("10.0.0.0/8")},
		{mustParseCIDR("172.16.0.0/12")},
		{mustParseCIDR("192.168.0.0/16")},
		{mustParseCIDR("127.0.0.0/8")},
		{mustParseCIDR("::1/128")},
		{mustParseCIDR("fc00::/7")},
	}
	for _, r := range privateRanges {
		if r.network.Contains(ip) {
			return true
		}
	}
	return false
}

func mustParseCIDR(s string) *net.IPNet {
	_, network, err := net.ParseCIDR(s)
	if err != nil {
		panic(err)
	}
	return network
}

func dispatchWebhookRequest(rawURL, secret string, payload map[string]interface{}) error {
	parsedURL, err := url.Parse(rawURL)
	if err != nil {
		return fmt.Errorf("invalid webhook URL: %w", err)
	}
	hostname := parsedURL.Hostname()
	if isPrivateIP(hostname) {
		return fmt.Errorf("webhook URL points to private IP: %s", hostname)
	}
	if parsedURL.Scheme != "https" && parsedURL.Scheme != "http" {
		return fmt.Errorf("webhook URL must use http or https scheme")
	}
	if parsedURL.Scheme == "http" && strings.TrimSpace(secret) != "" {
		return fmt.Errorf("webhook URL must use https when secret is configured")
	}

	bodyBytes, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	req, err := http.NewRequest(http.MethodPost, rawURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if strings.TrimSpace(secret) != "" {
		req.Header.Set("X-Webhook-Secret", secret)
	}

	resp, err := safeWebhookClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("webhook returned status %d", resp.StatusCode)
	}
	return nil
}

func sortProjectPolicies(items []model.ProjectNotificationPolicy) []model.ProjectNotificationPolicy {
	sorted := make([]model.ProjectNotificationPolicy, len(items))
	copy(sorted, items)
	sort.SliceStable(sorted, func(i, j int) bool {
		oi, iok := projectNotificationCategoryOrder[sorted[i].Category]
		oj, jok := projectNotificationCategoryOrder[sorted[j].Category]
		if iok && jok {
			return oi < oj
		}
		if iok {
			return true
		}
		if jok {
			return false
		}
		return sorted[i].Category < sorted[j].Category
	})
	return sorted
}

func isProjectNotificationCategory(category string) bool {
	_, ok := projectNotificationCategoryOrder[strings.TrimSpace(category)]
	return ok
}

func defaultProjectPolicyFor(category string) struct {
	category     string
	inAppEnabled bool
	emailEnabled bool
} {
	for _, item := range defaultProjectNotificationPolicies {
		if item.category == category {
			return item
		}
	}
	return struct {
		category     string
		inAppEnabled bool
		emailEnabled bool
	}{category: category, inAppEnabled: true, emailEnabled: true}
}

func normalizeOptionalUint(id *uint) *uint {
	if id == nil || *id == 0 {
		return nil
	}
	return id
}
