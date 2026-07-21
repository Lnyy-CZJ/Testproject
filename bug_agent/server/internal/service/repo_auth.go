package service

import (
	"bug-agent/internal/git"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"fmt"

	"gorm.io/gorm"
)

func ResolveRepositoryAuth(db *gorm.DB, projectID uint, repo model.ProjectRepo, agentType string, operatorID uint) (*git.Auth, *uint, error) {
	credSvc := NewCredentialService(db)

	tryCredential := func(credentialID uint) (*git.Auth, *uint, bool) {
		auth, _, err := LoadGitAuthFromCredential(db, credentialID)
		if err != nil {
			logger.Infof("[RepoAuth] skip invalid credential %d: %v", credentialID, err)
			return nil, nil, false
		}
		_ = credSvc.TouchLastUsed(credentialID)
		id := credentialID
		return auth, &id, true
	}

	if repo.CredentialID != nil && matchAgentType(repo.AgentTypes, agentType) {
		if auth, id, ok := tryCredential(*repo.CredentialID); ok {
			return auth, id, nil
		}
	}

	var projectDefault model.ProjectRepo
	if err := db.
		Where("project_id = ? AND source_type = ? AND credential_id IS NOT NULL", projectID, repo.SourceType).
		Order("id ASC").
		First(&projectDefault).Error; err == nil && projectDefault.CredentialID != nil {
		if auth, id, ok := tryCredential(*projectDefault.CredentialID); ok {
			return auth, id, nil
		}
	}

	if operatorID > 0 {
		providers := sourceTypeProviders(repo.SourceType)
		var personal model.RepoCredential
		if err := db.
			Where("user_id = ? AND provider IN ?", operatorID, providers).
			Order("COALESCE(last_used_at, created_at) DESC").
			First(&personal).Error; err == nil {
			if auth, id, ok := tryCredential(personal.ID); ok {
				return auth, id, nil
			}
		}
	}

	return nil, nil, nil
}

func LoadGitAuthFromCredential(db *gorm.DB, credentialID uint) (*git.Auth, *model.RepoCredential, error) {
	var cred model.RepoCredential
	if err := db.First(&cred, credentialID).Error; err != nil {
		return nil, nil, err
	}

	credSvc := NewCredentialService(db)
	content, err := credSvc.GetDecryptedContentByID(cred.ID)
	if err != nil {
		return nil, nil, err
	}

	auth, err := buildGitAuthFromCredential(cred.Type, content)
	if err != nil {
		return nil, nil, err
	}

	return &auth, &cred, nil
}

func buildGitAuthFromCredential(credType, content string) (git.Auth, error) {
	switch credType {
	case "ssh_key":
		return git.Auth{}, fmt.Errorf("ssh_key credential is not supported")
	case "username_password":
		username, password := parseUsernamePassword(content)
		if username == "" || password == "" {
			return git.Auth{}, fmt.Errorf("invalid username_password credential content")
		}
		return git.Auth{Username: username, Password: password}, nil
	default:
		if content == "" {
			return git.Auth{}, fmt.Errorf("empty token credential")
		}
		return git.Auth{
			Username: "oauth2",
			Password: content,
			Token:    content,
		}, nil
	}
}
