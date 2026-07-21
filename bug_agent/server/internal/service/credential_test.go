package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
)

func TestCredentialService_List(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_list")

	cred1, err := svc.Create(user.ID, "GitHub Token", "pat", "github", "ghp_test123")
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}
	_ = cred1
	cred2, err := svc.Create(user.ID, "GitLab Token", "pat", "gitlab", "glpat_test456")
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	creds, err := svc.List(user.ID)
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}
	if len(creds) != 2 {
		t.Fatalf("Expected 2 credentials, got %d", len(creds))
	}
	if creds[0].ID != cred2.ID {
		t.Errorf("Expected newest first, got ID %d then %d", creds[0].ID, creds[1].ID)
	}
}

func TestCredentialService_GetByID(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_get")

	created, err := svc.Create(user.ID, "Test Cred", "pat", "github", "ghp_test")
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	found, err := svc.GetByID(created.ID, user.ID)
	if err != nil {
		t.Fatalf("GetByID failed: %v", err)
	}
	if found.ID != created.ID {
		t.Errorf("ID mismatch: %d vs %d", found.ID, created.ID)
	}
	if found.Content == "" {
		t.Error("Content should be encrypted (not empty)")
	}
}

func TestCredentialService_GetByID_NotFound(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_notfound")

	_, err := svc.GetByID(999, user.ID)
	if err != ErrCredentialNotFound {
		t.Fatalf("Expected ErrCredentialNotFound, got %v", err)
	}
}

func TestCredentialService_Create(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_create")

	cred, err := svc.Create(user.ID, "GitHub Token", "pat", "github", "ghp_1234567890abcdef")
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}
	if cred.ID == 0 {
		t.Error("ID should be set")
	}
	if cred.UserID != user.ID {
		t.Errorf("UserID mismatch: %d vs %d", cred.UserID, user.ID)
	}
	if cred.Name != "GitHub Token" {
		t.Errorf("Name mismatch: %s", cred.Name)
	}
	if cred.Type != "pat" {
		t.Errorf("Type mismatch: %s", cred.Type)
	}
	if cred.Provider != "github" {
		t.Errorf("Provider mismatch: %s", cred.Provider)
	}
	if cred.Content == "" {
		t.Error("Content should be encrypted (not empty)")
	}
	if !strings.Contains(cred.MaskedValue, "****") {
		t.Errorf("MaskedValue should contain asterisks: %s", cred.MaskedValue)
	}
}

func TestCredentialService_ExtraConfig(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_extra_config")

	initialExtra := `{"organizationId":"org-1","endpoint":"https://openapi-rdc.aliyuncs.com"}`
	cred, err := svc.Create(user.ID, "Yunxiao Token", "pat", "yunxiao", "token-abc", initialExtra)
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}
	if cred.ExtraConfig != initialExtra {
		t.Fatalf("ExtraConfig mismatch: got %q want %q", cred.ExtraConfig, initialExtra)
	}

	nextExtra := `{"organizationId":"org-2","workspaceId":"space-1"}`
	updated, err := svc.Update(cred.ID, user.ID, "", "", "", "", &nextExtra)
	if err != nil {
		t.Fatalf("Update failed: %v", err)
	}
	if updated.ExtraConfig != nextExtra {
		t.Fatalf("ExtraConfig not updated: got %q want %q", updated.ExtraConfig, nextExtra)
	}

	empty := ""
	updated, err = svc.Update(cred.ID, user.ID, "", "", "", "", &empty)
	if err != nil {
		t.Fatalf("Clear extra config failed: %v", err)
	}
	if updated.ExtraConfig != "" {
		t.Fatalf("ExtraConfig should be empty after clear, got %q", updated.ExtraConfig)
	}
}

func TestCredentialService_Update(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_update")

	created, err := svc.Create(user.ID, "Old Name", "pat", "github", "ghp_old")
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	updated, err := svc.Update(created.ID, user.ID, "New Name", "ssh_key", "gitlab", "ghp_new")
	if err != nil {
		t.Fatalf("Update failed: %v", err)
	}
	if updated.Name != "New Name" {
		t.Errorf("Name not updated: %s", updated.Name)
	}
	if updated.Type != "ssh_key" {
		t.Errorf("Type not updated: %s", updated.Type)
	}
	if updated.Provider != "gitlab" {
		t.Errorf("Provider not updated: %s", updated.Provider)
	}
}

func TestCredentialService_Delete(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_delete")

	created, err := svc.Create(user.ID, "To Delete", "pat", "github", "ghp_del")
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	err = svc.Delete(created.ID, user.ID)
	if err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	_, err = svc.GetByID(created.ID, user.ID)
	if err != ErrCredentialNotFound {
		t.Errorf("Expected ErrCredentialNotFound after delete, got %v", err)
	}
}

func TestCredentialService_GetDecryptedContent(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_decrypt")

	original := "ghp_1234567890abcdef"
	created, err := svc.Create(user.ID, "Test", "pat", "github", original)
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	decrypted, err := svc.GetDecryptedContent(created.ID, user.ID)
	if err != nil {
		t.Fatalf("GetDecryptedContent failed: %v", err)
	}
	if decrypted != original {
		t.Errorf("Decrypted content mismatch: %s vs %s", decrypted, original)
	}
}

func TestCredentialService_TouchLastUsed(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)
	user := testutil.CreateTestUser(t, db, "cred_touch")

	created, err := svc.Create(user.ID, "Test", "pat", "github", "ghp_test")
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	err = svc.TouchLastUsed(created.ID)
	if err != nil {
		t.Fatalf("TouchLastUsed failed: %v", err)
	}

	var cred model.RepoCredential
	if err := db.First(&cred, created.ID).Error; err != nil {
		t.Fatalf("Failed to reload credential: %v", err)
	}
	if cred.LastUsedAt == nil {
		t.Error("LastUsedAt should be set")
	}
}

func TestCredentialService_ValidateConnection(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)

	repoURL := createLocalGitRepoURL(t)
	tests := []struct {
		name     string
		provider string
		repoURL  string
		wantOK   bool
	}{
		{"Local Generic", "generic", repoURL, true},
		{"Invalid URL", "generic", "https://example.invalid/not-found.git", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := svc.ValidateConnection(tt.provider, tt.repoURL, "")
			if result["success"].(bool) != tt.wantOK {
				t.Errorf("ValidateConnection() success = %v, want %v", result["success"], tt.wantOK)
			}
		})
	}
}

func TestCredentialService_EncryptDecrypt(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewCredentialService(db)

	plaintext := "test_secret_12345"
	encrypted, err := svc.encrypt(plaintext)
	if err != nil {
		t.Fatalf("encrypt failed: %v", err)
	}
	if encrypted == plaintext {
		t.Error("encrypted should differ from plaintext")
	}

	decrypted, err := svc.decrypt(encrypted)
	if err != nil {
		t.Fatalf("decrypt failed: %v", err)
	}
	if decrypted != plaintext {
		t.Errorf("decrypted = %s, want %s", decrypted, plaintext)
	}
}

func createLocalGitRepoURL(t *testing.T) string {
	t.Helper()

	dir := t.TempDir()
	repo, err := git.PlainInit(dir, false)
	if err != nil {
		t.Fatalf("init local git repo failed: %v", err)
	}

	readmePath := filepath.Join(dir, "README.md")
	if err := os.WriteFile(readmePath, []byte("# local repo\n"), 0644); err != nil {
		t.Fatalf("write readme failed: %v", err)
	}

	worktree, err := repo.Worktree()
	if err != nil {
		t.Fatalf("get worktree failed: %v", err)
	}
	if _, err := worktree.Add("README.md"); err != nil {
		t.Fatalf("git add failed: %v", err)
	}
	if _, err := worktree.Commit("init", &git.CommitOptions{
		Author: &object.Signature{Name: "tester", Email: "tester@example.com", When: time.Now()},
	}); err != nil {
		t.Fatalf("git commit failed: %v", err)
	}

	return "file://" + dir
}
