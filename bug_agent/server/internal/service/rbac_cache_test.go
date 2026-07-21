package service

import (
	"testing"

	"bug-agent/testutil"
)

func TestRBACService_GetUserPermissions_CachePreservesPermissionFields(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewRBACService(db)

	user := testutil.CreateTestUser(t, db, "rbac_cache_user")
	roleMap := testutil.CreateTestRoles(t, db)
	testutil.AssignRoleToUser(t, db, user.ID, "developer", roleMap)

	first := svc.GetUserPermissions(user.ID)
	if len(first) == 0 {
		t.Fatalf("expected at least 1 permission from database")
	}

	second := svc.GetUserPermissions(user.ID)
	if len(second) == 0 {
		t.Fatalf("expected cached permissions")
	}

	for _, p := range second {
		if p.Code == "" {
			t.Fatalf("cached permission code should not be empty")
		}
		if p.Name == "" || p.Module == "" {
			t.Fatalf("cached permission should preserve fields, got %+v", p)
		}
	}
}
