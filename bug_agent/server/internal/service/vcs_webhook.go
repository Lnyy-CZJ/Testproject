package service

import (
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"bug-agent/pkg/logger"
	"strings"
	"time"

	"gorm.io/gorm"
)

type VCSWebhookService struct {
	db            *gorm.DB
	memoryService *AgentMemoryService
}

func NewVCSWebhookService(db *gorm.DB) *VCSWebhookService {
	return &VCSWebhookService{
		db:            db,
		memoryService: NewAgentMemoryService(db),
	}
}

func (s *VCSWebhookService) HandleWebhook(provider string, payload []byte, signature string, gitlabToken string) error {
	switch strings.ToLower(provider) {
	case "github":
		if signature == "" {
			return fmt.Errorf("GitHub webhook signature is required (X-Hub-Signature-256)")
		}
		if err := s.verifyGitHubSignature(payload, signature); err != nil {
			return fmt.Errorf("GitHub webhook signature verification failed: %w", err)
		}
		return s.handleGitHubPREvent(payload)
	case "gitlab":
		if gitlabToken == "" {
			return fmt.Errorf("GitLab webhook token is required (X-Gitlab-Token)")
		}
		if err := s.verifyGitLabToken(payload, gitlabToken); err != nil {
			return fmt.Errorf("GitLab webhook token verification failed: %w", err)
		}
		return s.handleGitLabMREvent(payload)
	default:
		return fmt.Errorf("unsupported VCS provider: %s", provider)
	}
}

func (s *VCSWebhookService) verifyGitHubSignature(payload []byte, signature string) error {
	var event struct {
		Repository struct {
			FullName string `json:"full_name"`
		} `json:"repository"`
	}
	if err := json.Unmarshal(payload, &event); err != nil {
		return fmt.Errorf("invalid payload")
	}
	if event.Repository.FullName == "" {
		return fmt.Errorf("no repository info in payload")
	}

	repoPath := ExtractRepoPath(event.Repository.FullName)
	var repos []model.ProjectRepo
	if err := s.db.Where("source_type = ? AND webhook_secret != '' AND (repo_url LIKE ? OR repo_url LIKE ?)",
		"github",
		"%/"+escapeLike(repoPath),
		"%/"+escapeLike(repoPath)+".git",
	).Find(&repos).Error; err != nil {
		return fmt.Errorf("query repos failed: %w", err)
	}

	var matched []model.ProjectRepo
	for _, repo := range repos {
		if ExtractRepoPath(repo.RepoURL) != repoPath {
			continue
		}
		matched = append(matched, repo)
	}

	if len(matched) == 0 {
		return fmt.Errorf("no GitHub repos with webhook_secret configured for %s, cannot verify signature", event.Repository.FullName)
	}
	for _, repo := range matched {
		if repo.WebhookSecret == "" {
			continue
		}
		mac := hmac.New(sha256.New, []byte(repo.WebhookSecret))
		mac.Write(payload)
		expected := "sha256=" + hex.EncodeToString(mac.Sum(nil))
		if hmac.Equal([]byte(signature), []byte(expected)) {
			return nil
		}
	}
	return fmt.Errorf("signature does not match any configured webhook secret")
}

func (s *VCSWebhookService) verifyGitLabToken(payload []byte, token string) error {
	var event struct {
		Project struct {
			PathWithNamespace string `json:"path_with_namespace"`
		} `json:"project"`
	}
	if err := json.Unmarshal(payload, &event); err != nil {
		return fmt.Errorf("invalid payload")
	}
	if event.Project.PathWithNamespace == "" {
		return fmt.Errorf("no project info in payload")
	}

	repoPath := ExtractRepoPath(event.Project.PathWithNamespace)
	var repos []model.ProjectRepo
	if err := s.db.Where("source_type = ? AND webhook_secret != '' AND (repo_url LIKE ? OR repo_url LIKE ?)",
		"gitlab",
		"%/"+escapeLike(repoPath),
		"%/"+escapeLike(repoPath)+".git",
	).Find(&repos).Error; err != nil {
		return fmt.Errorf("query repos failed: %w", err)
	}

	var matched []model.ProjectRepo
	for _, repo := range repos {
		if ExtractRepoPath(repo.RepoURL) != repoPath {
			continue
		}
		matched = append(matched, repo)
	}

	if len(matched) == 0 {
		return fmt.Errorf("no GitLab repos with webhook_secret configured for %s, cannot verify token", event.Project.PathWithNamespace)
	}
	for _, repo := range matched {
		if hmac.Equal([]byte(repo.WebhookSecret), []byte(token)) {
			return nil
		}
	}
	return fmt.Errorf("token does not match any configured webhook secret")
}

type githubPREvent struct {
	Action      string `json:"action"`
	PullRequest struct {
		Number  int    `json:"number"`
		HTMLURL string `json:"html_url"`
		Merged  bool   `json:"merged"`
		State   string `json:"state"`
		User    struct {
			Login string `json:"login"`
		} `json:"user"`
		Body  string `json:"body"`
		Base  struct {
			Repo struct {
				HTMLURL string `json:"html_url"`
				CloneURL string `json:"clone_url"`
			} `json:"repo"`
		} `json:"base"`
	} `json:"pull_request"`
}

func (s *VCSWebhookService) handleGitHubPREvent(payload []byte) error {
	var event githubPREvent
	if err := json.Unmarshal(payload, &event); err != nil {
		return fmt.Errorf("parse GitHub PR event failed: %w", err)
	}

	if event.Action != "closed" {
		return nil
	}

	repoURL := event.PullRequest.Base.Repo.HTMLURL
	if repoURL == "" {
		repoURL = event.PullRequest.Base.Repo.CloneURL
	}
	prNumber := fmt.Sprintf("%d", event.PullRequest.Number)

	fixTask, err := s.findFixTaskByPR(repoURL, prNumber)
	if err != nil {
		logger.Infof("[VCSWebhook] GitHub PR event: no matching FixTask found (repo=%s pr=%s): %v", repoURL, prNumber, err)
		return nil
	}

	if event.PullRequest.Merged {
		return s.handlePRMerged(*fixTask)
	}

	reason := event.PullRequest.Body
	if reason == "" {
		reason = "PR closed without merge"
	}

	return s.handlePRRejected(*fixTask, prNumber, event.PullRequest.User.Login, reason, "github")
}

type gitLabMREvent struct {
	ObjectAttributes struct {
		IID    int    `json:"iid"`
		State  string `json:"state"`
		Merged bool   `json:"merged"`
		URL    string `json:"url"`
		Action string `json:"action"`
	} `json:"object_attributes"`
	User struct {
		Username string `json:"username"`
	} `json:"user"`
	Project struct {
		WebURL  string `json:"web_url"`
		GitHTTPURL string `json:"git_http_url"`
	} `json:"project"`
}

func (s *VCSWebhookService) handleGitLabMREvent(payload []byte) error {
	var event gitLabMREvent
	if err := json.Unmarshal(payload, &event); err != nil {
		return fmt.Errorf("parse GitLab MR event failed: %w", err)
	}

	state := event.ObjectAttributes.State
	if state != "closed" && state != "merged" {
		return nil
	}

	repoURL := event.Project.WebURL
	if repoURL == "" {
		repoURL = event.Project.GitHTTPURL
	}
	prNumber := fmt.Sprintf("%d", event.ObjectAttributes.IID)

	fixTask, err := s.findFixTaskByPR(repoURL, prNumber)
	if err != nil {
		logger.Infof("[VCSWebhook] GitLab MR event: no matching FixTask found (repo=%s mr=%s): %v", repoURL, prNumber, err)
		return nil
	}

	if state == "merged" || event.ObjectAttributes.Merged {
		return s.handlePRMerged(*fixTask)
	}

	return s.handlePRRejected(*fixTask, prNumber, event.User.Username, "MR closed without merge", "gitlab")
}

func (s *VCSWebhookService) findFixTaskByPR(repoURL, prNumber string) (*model.FixTask, error) {
	repoPath := ExtractRepoPath(repoURL)
	var fixTask model.FixTask
	err := s.db.Where("pr_number = ? AND repo_path = ?", prNumber, repoPath).
		Order("created_at DESC").
		First(&fixTask).Error
	if err != nil {
		err = s.db.Where("pr_number = ? AND pr_url LIKE ?", prNumber, "%"+escapeLike(repoPath)+"%").
			Order("created_at DESC").
			First(&fixTask).Error
		if err != nil {
			return nil, err
		}
	}
	return &fixTask, nil
}

func ExtractRepoPath(repoURL string) string {
	repoURL = strings.TrimRight(repoURL, "/")
	repoURL = strings.TrimSuffix(repoURL, ".git")
	parts := strings.Split(repoURL, "/")
	if len(parts) >= 2 {
		return parts[len(parts)-2] + "/" + parts[len(parts)-1]
	}
	return repoURL
}

func (s *VCSWebhookService) handlePRRejected(fixTask model.FixTask, prNumber, rejectedBy, reason, provider string) error {
	rejection := model.PRRejection{
		FixTaskID:    fixTask.ID,
		PRNumber:     prNumber,
		PRURL:        fixTask.PRURL,
		RejectedBy:   rejectedBy,
		RejectReason: reason,
		VCSProvider:  provider,
		CreatedAt:    time.Now(),
	}

	var defect model.Defect

	err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&rejection).Error; err != nil {
			return err
		}
		if err := tx.Model(&model.FixTask{}).Where("id = ?", fixTask.ID).Update("PRStatus", "rejected").Error; err != nil {
			return err
		}
		if err := tx.Preload("Iteration").First(&defect, fixTask.DefectID).Error; err != nil {
			return err
		}
		fromStatus := defect.Status
		result := tx.Model(&model.Defect{}).Where("id = ? AND status IN ?", defect.ID, []string{
			model.DefectStatusPendingVerify, model.DefectStatusFixing, model.DefectStatusManualFixing,
		}).Update("status", model.DefectStatusPendingFix)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("缺陷状态已变更，无法回退到待修复")
		}
		return tx.Create(&model.StatusChange{
			DefectID:   defect.ID,
			FromStatus: fromStatus,
			ToStatus:   model.DefectStatusPendingFix,
			Comment:    fmt.Sprintf("PR #%s 被拒绝，原因：%s", prNumber, reason),
			CreatedAt:  time.Now(),
		}).Error
	})

	if err != nil {
		logger.Errorf("[VCSWebhook] handlePRRejected 事务失败: %v", err)
		return err
	}

	s.publishPRRejectedComment(defect, prNumber, reason)

	if s.memoryService != nil && defect.Iteration.ProjectID > 0 {
		asyncx.Go(func() {
			if err := s.memoryService.ExtractMemoryFromPRRejection(rejection, fixTask, defect.Iteration.ProjectID); err != nil {
				logger.Errorf("[VCSWebhook] 自动沉淀 PR 拒绝记忆失败: %v", err)
			}
		})
	}

	return nil
}

func (s *VCSWebhookService) handlePRMerged(fixTask model.FixTask) error {
	var defect model.Defect

	err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Model(&model.FixTask{}).Where("id = ?", fixTask.ID).Update("PRStatus", "merged").Error; err != nil {
			return err
		}
		if err := tx.Preload("Iteration").First(&defect, fixTask.DefectID).Error; err != nil {
			return err
		}
		fromStatus := defect.Status
		result := tx.Model(&model.Defect{}).Where("id = ? AND status IN ?", defect.ID, []string{
			model.DefectStatusPendingVerify, model.DefectStatusFixing, model.DefectStatusManualFixing,
		}).Update("status", model.DefectStatusFixed)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("缺陷状态已变更，无法标记为已修复")
		}
		return tx.Create(&model.StatusChange{
			DefectID:   defect.ID,
			FromStatus: fromStatus,
			ToStatus:   model.DefectStatusFixed,
			Comment:    "PR 已合并",
			CreatedAt:  time.Now(),
		}).Error
	})

	if err != nil {
		logger.Errorf("[VCSWebhook] handlePRMerged 事务失败: %v", err)
		return err
	}

	s.publishPRMergedComment(defect, fixTask.PRNumber)
	return nil
}

func (s *VCSWebhookService) publishPRRejectedComment(defect model.Defect, prNumber, reason string) {
	content := fmt.Sprintf("⚠️ **PR 被拒绝**\n\n**PR编号**: #%s\n**拒绝原因**: %s\n\n缺陷状态已回退到待修复。",
		prNumber, reason)

	comment := model.Comment{
		DefectID:       defect.ID,
		Content:        sanitizeCommentContent(content),
		IsAgentMessage: true,
	}
	comment.UserID = resolveCommentUserID(defect)
	if !ensureCommentUserExists(s.db, comment.UserID) {
		return
	}
	if err := s.db.Create(&comment).Error; err != nil {
		logger.Errorf("db operation failed: %v", err)
	}
}

func (s *VCSWebhookService) publishPRMergedComment(defect model.Defect, prNumber string) {
	content := fmt.Sprintf("✅ **PR 已合并**\n\n**PR编号**: #%s\n\n缺陷状态已推进到已修复。",
		prNumber)

	comment := model.Comment{
		DefectID:       defect.ID,
		Content:        sanitizeCommentContent(content),
		IsAgentMessage: true,
	}
	comment.UserID = resolveCommentUserID(defect)
	if !ensureCommentUserExists(s.db, comment.UserID) {
		return
	}
	if err := s.db.Create(&comment).Error; err != nil {
		logger.Errorf("db operation failed: %v", err)
	}
}

func (s *VCSWebhookService) HandleManualPRRejected(fixTask model.FixTask, rejectedBy, reason string) error {
	prNumber := fixTask.PRNumber
	if prNumber == "" {
		prNumber = "unknown"
	}

	rejection := model.PRRejection{
		FixTaskID:    fixTask.ID,
		PRNumber:     prNumber,
		PRURL:        fixTask.PRURL,
		RejectedBy:   rejectedBy,
		RejectReason: reason,
		VCSProvider:  "manual",
		CreatedAt:    time.Now(),
	}

	var defect model.Defect

	err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&rejection).Error; err != nil {
			return fmt.Errorf("创建 PRRejection 记录失败: %w", err)
		}
		if err := tx.Model(&model.FixTask{}).Where("id = ?", fixTask.ID).Update("PRStatus", "rejected").Error; err != nil {
			return err
		}
		if err := tx.Preload("Iteration").First(&defect, fixTask.DefectID).Error; err != nil {
			return err
		}
		fromStatus := defect.Status
		result := tx.Model(&model.Defect{}).Where("id = ? AND status IN ?", defect.ID, []string{
			model.DefectStatusPendingVerify, model.DefectStatusFixing, model.DefectStatusManualFixing,
		}).Update("status", model.DefectStatusPendingFix)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("缺陷状态已变更，无法回退到待修复")
		}
		return tx.Create(&model.StatusChange{
			DefectID:   defect.ID,
			FromStatus: fromStatus,
			ToStatus:   model.DefectStatusPendingFix,
			Comment:    fmt.Sprintf("PR #%s 被手动标记拒绝，原因：%s", prNumber, reason),
			CreatedAt:  time.Now(),
		}).Error
	})

	if err != nil {
		logger.Errorf("[VCSWebhook] HandleManualPRRejected 事务失败: %v", err)
		return err
	}

	s.publishPRRejectedComment(defect, prNumber, reason)

	if s.memoryService != nil && defect.Iteration.ProjectID > 0 {
		asyncx.Go(func() {
			if err := s.memoryService.ExtractMemoryFromPRRejection(rejection, fixTask, defect.Iteration.ProjectID); err != nil {
				logger.Errorf("[VCSWebhook] 手动拒绝 PR 记忆提取失败: %v", err)
			}
		})
	}

	return nil
}

func (s *VCSWebhookService) HandleManualPRMerged(fixTask model.FixTask) error {
	var defect model.Defect

	err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Model(&model.FixTask{}).Where("id = ?", fixTask.ID).Update("PRStatus", "merged").Error; err != nil {
			return err
		}
		if err := tx.Preload("Iteration").First(&defect, fixTask.DefectID).Error; err != nil {
			return err
		}
		fromStatus := defect.Status
		result := tx.Model(&model.Defect{}).Where("id = ? AND status IN ?", defect.ID, []string{
			model.DefectStatusPendingVerify, model.DefectStatusFixing, model.DefectStatusManualFixing,
		}).Update("status", model.DefectStatusFixed)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("缺陷状态已变更，无法标记为已修复")
		}
		return tx.Create(&model.StatusChange{
			DefectID:   defect.ID,
			FromStatus: fromStatus,
			ToStatus:   model.DefectStatusFixed,
			Comment:    "PR 被手动标记为已合并",
			CreatedAt:  time.Now(),
		}).Error
	})

	if err != nil {
		logger.Errorf("[VCSWebhook] HandleManualPRMerged 事务失败: %v", err)
		return err
	}

	s.publishPRMergedComment(defect, fixTask.PRNumber)
	return nil
}
