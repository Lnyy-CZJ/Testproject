package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"testing"
)

func TestRBACService_HasPermission_FromPlatformRole(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewRBACService(db)
	user := testutil.CreateTestUser(t, db, "rbac_platform_user")

	if err := db.Model(&model.User{}).Where("id = ?", user.ID).Update("platform_role", "admin").Error; err != nil {
		t.Fatalf("failed to update platform role: %v", err)
	}

	if !svc.HasPermission(user.ID, "users:read") {
		t.Fatal("admin should have users:read from platform role")
	}
	if svc.HasPermission(user.ID, "defects:delete") {
		t.Fatal("admin should not have project-scoped defects:delete by default")
	}
}

func TestRBACService_HasProjectPermission_FromProjectRole(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewRBACService(db)
	user := testutil.CreateTestUser(t, db, "rbac_project_user")
	p1 := testutil.CreateTestProject(t, db, "RBACP1", "RBCP1")
	p2 := testutil.CreateTestProject(t, db, "RBACP2", "RBCP2")

	if err := db.Create(&model.ProjectMember{ProjectID: p1.ID, UserID: user.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("failed to add p1 member: %v", err)
	}
	if err := db.Create(&model.ProjectMember{ProjectID: p2.ID, UserID: user.ID, Role: "viewer"}).Error; err != nil {
		t.Fatalf("failed to add p2 member: %v", err)
	}

	if !svc.HasProjectPermission(user.ID, p1.ID, "defects:update") {
		t.Fatal("developer should have defects:update in project 1")
	}
	if svc.HasProjectPermission(user.ID, p2.ID, "defects:update") {
		t.Fatal("viewer should not have defects:update in project 2")
	}
	if !svc.HasProjectPermission(user.ID, p2.ID, "defects:read") {
		t.Fatal("viewer should have defects:read in project 2")
	}
}

func TestRBACService_GetUserRoles_IncludesSimplifiedRoles(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewRBACService(db)
	user := testutil.CreateTestUser(t, db, "rbac_role_user")
	project := testutil.CreateTestProject(t, db, "RBACRoleProject", "RBCR")

	if err := db.Model(&model.User{}).Where("id = ?", user.ID).Update("platform_role", "member").Error; err != nil {
		t.Fatalf("failed to set platform role: %v", err)
	}
	if err := db.Create(&model.ProjectMember{ProjectID: project.ID, UserID: user.ID, Role: "project_admin"}).Error; err != nil {
		t.Fatalf("failed to add project member: %v", err)
	}

	roles := svc.GetUserRoles(user.ID)
	hit := map[string]bool{}
	for _, role := range roles {
		hit[role.Name] = true
	}
	if !hit["member"] {
		t.Fatal("expected member role in GetUserRoles")
	}
	if !hit["project_admin"] {
		t.Fatal("expected project_admin role in GetUserRoles")
	}
}
