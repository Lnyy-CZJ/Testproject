package service

import (
	"bug-agent/internal/config"
	gitrepo "bug-agent/internal/git"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	"gorm.io/gorm"
)

const credentialTestTimeout = 12 * time.Second

var (
	ErrCredentialNotFound     = errors.New("credential not found")
	ErrCredentialForbidden    = errors.New("credential forbidden")
	ErrCredentialInactive     = errors.New("credential inactive")
	ErrPlatformCredentialOnly = errors.New("platform credential only")
)

const (
	CredentialScopePersonal = "personal"
	CredentialScopePlatform = "platform"

	CredentialStatusActive   = "active"
	CredentialStatusInactive = "inactive"
)

type CredentialService struct {
	db     *gorm.DB
	key    []byte
	keyErr error
}

func NewCredentialService(db *gorm.DB) *CredentialService {
	key, err := loadCredentialKey()
	return &CredentialService{
		db:     db,
		key:    key,
		keyErr: err,
	}
}

func loadCredentialKey() ([]byte, error) {
	raw := config.C.Secrets.CredentialEncryptKey
	if raw == "" {
		return nil, errors.New("secrets.credential_encrypt_key is required in config")
	}

	if decoded, err := base64.StdEncoding.DecodeString(raw); err == nil {
		if len(decoded) == 32 {
			return decoded, nil
		}
	}

	if len(raw) == 32 {
		return []byte(raw), nil
	}

	return nil, errors.New("secrets.credential_encrypt_key must be 32-byte raw string or base64-encoded 32-byte value")
}

func (s *CredentialService) ensureKey() error {
	if s.keyErr != nil {
		return s.keyErr
	}
	if len(s.key) != 32 {
		return errors.New("invalid credential encryption key length")
	}
	return nil
}

func (s *CredentialService) encrypt(plaintext string) (string, error) {
	if err := s.ensureKey(); err != nil {
		return "", err
	}

	block, err := aes.NewCipher(s.key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

func (s *CredentialService) decrypt(encoded string) (string, error) {
	if err := s.ensureKey(); err != nil {
		return "", err
	}

	ciphertext, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return "", err
	}
	block, err := aes.NewCipher(s.key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonceSize := gcm.NonceSize()
	if len(ciphertext) < nonceSize {
		return "", errors.New("ciphertext too short")
	}
	nonce, body := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, body, nil)
	if err != nil {
		return "", err
	}
	return string(plaintext), nil
}

func maskValue(content string) string {
	runes := []rune(content)
	if len(runes) <= 8 {
		return "****"
	}
	return string(runes[:4]) + "****" + string(runes[len(runes)-4:])
}

func (s *CredentialService) List(userID uint) ([]model.RepoCredential, error) {
	var creds []model.RepoCredential
	err := s.db.
		Where("user_id = ? AND (scope = ? OR scope = '')", userID, CredentialScopePersonal).
		Order("created_at desc").
		Find(&creds).Error
	if err != nil {
		return nil, err
	}
	s.applyDefaults(creds)
	return creds, nil
}

func (s *CredentialService) GetByID(id, userID uint) (*model.RepoCredential, error) {
	var cred model.RepoCredential
	err := s.db.
		Where("id = ? AND user_id = ? AND (scope = ? OR scope = '')", id, userID, CredentialScopePersonal).
		First(&cred).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrCredentialNotFound
		}
		return nil, err
	}
	s.applyDefault(&cred)
	return &cred, nil
}

func (s *CredentialService) Create(userID uint, name, credType, provider, content string, extraConfig ...string) (*model.RepoCredential, error) {
	return s.createCredential(userID, name, credType, provider, content, extraConfigOrEmpty(extraConfig), CredentialScopePersonal, CredentialStatusActive, nil)
}

func (s *CredentialService) CreatePlatform(userID uint, name, credType, provider, content, extraConfig, status string, allowedProjectIDs []uint) (*model.RepoCredential, error) {
	status = normalizeCredentialStatus(status)
	return s.createCredential(userID, name, credType, provider, content, extraConfig, CredentialScopePlatform, status, allowedProjectIDs)
}

func (s *CredentialService) createCredential(userID uint, name, credType, provider, content, extraConfig, scope, status string, allowedProjectIDs []uint) (*model.RepoCredential, error) {
	encrypted, err := s.encrypt(content)
	if err != nil {
		return nil, fmt.Errorf("encrypt failed: %w", err)
	}

	cred := model.RepoCredential{
		UserID:      userID,
		Name:        strings.TrimSpace(name),
		Type:        strings.TrimSpace(credType),
		Provider:    strings.TrimSpace(provider),
		Scope:       normalizeCredentialScope(scope),
		Status:      normalizeCredentialStatus(status),
		Content:     encrypted,
		ExtraConfig: strings.TrimSpace(extraConfig),
		MaskedValue: maskValue(content),
	}

	allowedProjectIDs = uniqueUintIDs(allowedProjectIDs)
	if err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&cred).Error; err != nil {
			return err
		}
		if cred.Scope == CredentialScopePlatform {
			if err := replacePlatformCredentialProjects(tx, cred.ID, allowedProjectIDs); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		return nil, err
	}
	cred.AllowedProjectIDs = allowedProjectIDs
	s.applyDefault(&cred)
	return &cred, nil
}

func (s *CredentialService) Update(id, userID uint, name, credType, provider, content string, extraConfig ...*string) (*model.RepoCredential, error) {
	cred, err := s.GetByID(id, userID)
	if err != nil {
		return nil, err
	}
	if name != "" {
		cred.Name = name
	}
	if credType != "" {
		cred.Type = credType
	}
	if provider != "" {
		cred.Provider = provider
	}
	if content != "" {
		encrypted, err := s.encrypt(content)
		if err != nil {
			return nil, fmt.Errorf("encrypt failed: %w", err)
		}
		cred.Content = encrypted
		cred.MaskedValue = maskValue(content)
	}
	if len(extraConfig) > 0 && extraConfig[0] != nil {
		cred.ExtraConfig = strings.TrimSpace(*extraConfig[0])
	}
	if err := s.db.Save(cred).Error; err != nil {
		return nil, err
	}
	s.applyDefault(cred)
	return cred, nil
}

func (s *CredentialService) Delete(id, userID uint) error {
	result := s.db.Where("id = ? AND user_id = ? AND (scope = ? OR scope = '')", id, userID, CredentialScopePersonal).Delete(&model.RepoCredential{})
	if result.RowsAffected == 0 {
		return ErrCredentialNotFound
	}
	return result.Error
}

func (s *CredentialService) ListPlatform() ([]model.RepoCredential, error) {
	var creds []model.RepoCredential
	if err := s.db.
		Where("scope = ?", CredentialScopePlatform).
		Order("created_at desc").
		Find(&creds).Error; err != nil {
		return nil, err
	}
	s.applyDefaults(creds)
	if err := s.attachAllowedProjectIDs(creds); err != nil {
		return nil, err
	}
	return creds, nil
}

func (s *CredentialService) ListForProject(userID, projectID uint) ([]model.RepoCredential, error) {
	personal, err := s.List(userID)
	if err != nil {
		return nil, err
	}

	var platform []model.RepoCredential
	if err := s.db.
		Table("repo_credentials").
		Joins("JOIN platform_credential_projects ON platform_credential_projects.credential_id = repo_credentials.id").
		Where("platform_credential_projects.project_id = ? AND repo_credentials.scope = ? AND (repo_credentials.status = ? OR repo_credentials.status = '')", projectID, CredentialScopePlatform, CredentialStatusActive).
		Order("repo_credentials.created_at desc").
		Find(&platform).Error; err != nil {
		return nil, err
	}
	s.applyDefaults(platform)
	if err := s.attachAllowedProjectIDs(platform); err != nil {
		return nil, err
	}

	combined := make([]model.RepoCredential, 0, len(platform)+len(personal))
	combined = append(combined, platform...)
	combined = append(combined, personal...)
	return combined, nil
}

func (s *CredentialService) UpdatePlatform(id uint, name, credType, provider, content, status string, extraConfig *string, allowedProjectIDs []uint) (*model.RepoCredential, error) {
	cred, err := s.getByIDAny(id)
	if err != nil {
		return nil, err
	}
	if normalizeCredentialScope(cred.Scope) != CredentialScopePlatform {
		return nil, ErrPlatformCredentialOnly
	}

	if trimmed := strings.TrimSpace(name); trimmed != "" {
		cred.Name = trimmed
	}
	if trimmed := strings.TrimSpace(credType); trimmed != "" {
		cred.Type = trimmed
	}
	if trimmed := strings.TrimSpace(provider); trimmed != "" {
		cred.Provider = trimmed
	}
	if trimmed := strings.TrimSpace(status); trimmed != "" {
		cred.Status = normalizeCredentialStatus(trimmed)
	}
	if content != "" {
		encrypted, err := s.encrypt(content)
		if err != nil {
			return nil, fmt.Errorf("encrypt failed: %w", err)
		}
		cred.Content = encrypted
		cred.MaskedValue = maskValue(content)
	}
	if extraConfig != nil {
		cred.ExtraConfig = strings.TrimSpace(*extraConfig)
	}

	allowedProjectIDs = uniqueUintIDs(allowedProjectIDs)
	if err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Save(cred).Error; err != nil {
			return err
		}
		return replacePlatformCredentialProjects(tx, cred.ID, allowedProjectIDs)
	}); err != nil {
		return nil, err
	}
	cred.AllowedProjectIDs = allowedProjectIDs
	s.applyDefault(cred)
	return cred, nil
}

func (s *CredentialService) DeletePlatform(id uint) error {
	return s.db.Transaction(func(tx *gorm.DB) error {
		result := tx.Where("id = ? AND scope = ?", id, CredentialScopePlatform).Delete(&model.RepoCredential{})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return ErrCredentialNotFound
		}
		return tx.Where("credential_id = ?", id).Delete(&model.PlatformCredentialProject{}).Error
	})
}

func (s *CredentialService) GetDecryptedContent(id, userID uint) (string, error) {
	cred, err := s.GetByID(id, userID)
	if err != nil {
		return "", err
	}
	return s.decrypt(cred.Content)
}

func (s *CredentialService) GetDecryptedContentByID(id uint) (string, error) {
	cred, err := s.getByIDAny(id)
	if err != nil {
		return "", err
	}
	return s.decrypt(cred.Content)
}

func (s *CredentialService) ResolveAccessibleCredential(credentialID, userID, projectID uint) (*model.RepoCredential, error) {
	cred, err := s.getByIDAny(credentialID)
	if err != nil {
		return nil, err
	}

	switch normalizeCredentialScope(cred.Scope) {
	case CredentialScopePlatform:
		if normalizeCredentialStatus(cred.Status) != CredentialStatusActive {
			return nil, ErrCredentialInactive
		}
		if projectID == 0 {
			return nil, ErrCredentialForbidden
		}
		allowed, err := s.isPlatformCredentialAllowedForProject(credentialID, projectID)
		if err != nil {
			return nil, err
		}
		if !allowed {
			return nil, ErrCredentialForbidden
		}
		allowedProjectIDs, err := s.getAllowedProjectIDs(credentialID)
		if err != nil {
			return nil, err
		}
		cred.AllowedProjectIDs = allowedProjectIDs
		return cred, nil
	default:
		if cred.UserID != userID {
			return nil, ErrCredentialNotFound
		}
		s.applyDefault(cred)
		return cred, nil
	}
}

func (s *CredentialService) getByIDAny(id uint) (*model.RepoCredential, error) {
	var cred model.RepoCredential
	if err := s.db.First(&cred, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrCredentialNotFound
		}
		return nil, err
	}
	s.applyDefault(&cred)
	return &cred, nil
}

func (s *CredentialService) TouchLastUsed(id uint) error {
	now := time.Now()
	return s.db.Model(&model.RepoCredential{}).Where("id = ?", id).Update("last_used_at", now).Error
}

func (s *CredentialService) isPlatformCredentialAllowedForProject(credentialID, projectID uint) (bool, error) {
	var count int64
	if err := s.db.Model(&model.PlatformCredentialProject{}).
		Where("credential_id = ? AND project_id = ?", credentialID, projectID).
		Count(&count).Error; err != nil {
		return false, err
	}
	return count > 0, nil
}

func (s *CredentialService) getAllowedProjectIDs(credentialID uint) ([]uint, error) {
	var rows []model.PlatformCredentialProject
	if err := s.db.
		Where("credential_id = ?", credentialID).
		Order("project_id asc").
		Find(&rows).Error; err != nil {
		return nil, err
	}
	ids := make([]uint, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.ProjectID)
	}
	return ids, nil
}

func (s *CredentialService) attachAllowedProjectIDs(creds []model.RepoCredential) error {
	if len(creds) == 0 {
		return nil
	}

	credentialIDs := make([]uint, 0, len(creds))
	indexByID := make(map[uint]int, len(creds))
	for i := range creds {
		if normalizeCredentialScope(creds[i].Scope) != CredentialScopePlatform {
			continue
		}
		credentialIDs = append(credentialIDs, creds[i].ID)
		indexByID[creds[i].ID] = i
	}
	if len(credentialIDs) == 0 {
		return nil
	}

	var rows []model.PlatformCredentialProject
	if err := s.db.
		Where("credential_id IN ?", credentialIDs).
		Order("project_id asc").
		Find(&rows).Error; err != nil {
		return err
	}

	for _, row := range rows {
		if idx, ok := indexByID[row.CredentialID]; ok {
			creds[idx].AllowedProjectIDs = append(creds[idx].AllowedProjectIDs, row.ProjectID)
		}
	}
	return nil
}

func (s *CredentialService) applyDefaults(creds []model.RepoCredential) {
	for i := range creds {
		s.applyDefault(&creds[i])
	}
}

func (s *CredentialService) applyDefault(cred *model.RepoCredential) {
	if cred == nil {
		return
	}
	cred.Scope = normalizeCredentialScope(cred.Scope)
	cred.Status = normalizeCredentialStatus(cred.Status)
}

func extraConfigOrEmpty(extraConfig []string) string {
	if len(extraConfig) == 0 {
		return ""
	}
	return strings.TrimSpace(extraConfig[0])
}

func normalizeCredentialScope(scope string) string {
	switch strings.ToLower(strings.TrimSpace(scope)) {
	case CredentialScopePlatform:
		return CredentialScopePlatform
	default:
		return CredentialScopePersonal
	}
}

func normalizeCredentialStatus(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case CredentialStatusInactive:
		return CredentialStatusInactive
	default:
		return CredentialStatusActive
	}
}

func uniqueUintIDs(values []uint) []uint {
	if len(values) == 0 {
		return nil
	}
	seen := make(map[uint]struct{}, len(values))
	out := make([]uint, 0, len(values))
	for _, value := range values {
		if value == 0 {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	return out
}

func replacePlatformCredentialProjects(tx *gorm.DB, credentialID uint, projectIDs []uint) error {
	if err := tx.Where("credential_id = ?", credentialID).Delete(&model.PlatformCredentialProject{}).Error; err != nil {
		return err
	}
	if len(projectIDs) == 0 {
		return nil
	}
	relations := make([]model.PlatformCredentialProject, 0, len(projectIDs))
	for _, projectID := range projectIDs {
		relations = append(relations, model.PlatformCredentialProject{
			CredentialID: credentialID,
			ProjectID:    projectID,
		})
	}
	return tx.Create(&relations).Error
}

func (s *CredentialService) ValidateConnection(provider, repoURL, credContent string) map[string]interface{} {
	provider = strings.ToLower(strings.TrimSpace(provider))
	repoURL = strings.TrimSpace(repoURL)

	result := map[string]interface{}{
		"success":   false,
		"provider":  provider,
		"repoUrl":   repoURL,
		"message":   "连接失败",
		"timestamp": time.Now().Format(time.RFC3339),
	}

	if repoURL == "" {
		result["message"] = "仓库地址不能为空"
		return result
	}

	ctx, cancel := context.WithTimeout(context.Background(), credentialTestTimeout)
	defer cancel()

	auth := buildValidateAuth(credContent)
	repo, err := gitrepo.NewRepository(ctx, gitrepo.CloneOptions{
		URL:          repoURL,
		Auth:         auth,
		Depth:        1,
		SingleBranch: true,
	})
	if err != nil {
		result["message"] = normalizeConnectionError(err)
		return result
	}
	defer repo.Cleanup()

	result["success"] = true
	result["message"] = providerDisplayName(provider) + " 连接成功"
	return result
}

func buildValidateAuth(content string) gitrepo.Auth {
	content = strings.TrimSpace(content)
	if content == "" {
		return gitrepo.Auth{}
	}

	var payload struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Token    string `json:"token"`
	}
	if strings.HasPrefix(content, "{") && json.Unmarshal([]byte(content), &payload) == nil {
		if strings.TrimSpace(payload.Token) != "" {
			username := strings.TrimSpace(payload.Username)
			if username == "" {
				username = "oauth2"
			}
			password := payload.Password
			if password == "" {
				password = payload.Token
			}
			return gitrepo.Auth{Username: username, Password: password, Token: payload.Token}
		}
		if strings.TrimSpace(payload.Username) != "" && payload.Password != "" {
			return gitrepo.Auth{Username: strings.TrimSpace(payload.Username), Password: payload.Password}
		}
	}

	if parts := strings.SplitN(content, ":", 2); len(parts) == 2 && strings.TrimSpace(parts[0]) != "" {
		return gitrepo.Auth{Username: strings.TrimSpace(parts[0]), Password: parts[1]}
	}

	return gitrepo.Auth{
		Username: "oauth2",
		Password: content,
		Token:    content,
	}
}

func normalizeConnectionError(err error) string {
	msg := strings.ToLower(strings.TrimSpace(err.Error()))
	switch {
	case strings.Contains(msg, "authentication"), strings.Contains(msg, "authorization"), strings.Contains(msg, "access denied"):
		return "认证失败，请检查凭证内容与仓库访问权限"
	case strings.Contains(msg, "repository not found"), strings.Contains(msg, "not found"):
		return "仓库不存在，或当前凭证无权限访问"
	case strings.Contains(msg, "context deadline exceeded"), strings.Contains(msg, "timeout"):
		return "连接超时，请检查仓库地址与网络可达性"
	default:
		logger.Errorf("[CredentialService] 连接失败: %v", err)
		return "连接失败，请检查仓库地址和网络"
	}
}

func providerDisplayName(provider string) string {
	switch provider {
	case "github":
		return "GitHub"
	case "gitlab":
		return "GitLab"
	case "gitea":
		return "Gitea"
	case "yunxiao":
		return "云效"
	default:
		return "Git"
	}
}
