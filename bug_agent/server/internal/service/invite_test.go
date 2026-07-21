package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"encoding/base64"
	"testing"
	"time"
)

func TestInviteService_GenerateCode(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_gen")

	invite, err := svc.GenerateCode(user.ID, 0, nil)
	if err != nil {
		t.Fatalf("GenerateCode failed: %v", err)
	}
	if invite.Code == "" {
		t.Error("Code should not be empty")
	}
	if len(invite.Code) != 64 {
		t.Errorf("Code should be 64 chars (signed token), got %d", len(invite.Code))
	}
	decoded, err := base64.RawURLEncoding.DecodeString(invite.Code)
	if err != nil || len(decoded) != 48 {
		t.Errorf("Code should decode to 48 bytes payload, err=%v len=%d", err, len(decoded))
	}
	if invite.InviterID != user.ID {
		t.Errorf("InviterID mismatch: %d vs %d", invite.InviterID, user.ID)
	}
	if invite.MaxUses != 0 {
		t.Errorf("MaxUses should be 0 (unlimited), got %d", invite.MaxUses)
	}
	if invite.UsedCount != 0 {
		t.Error("UsedCount should start at 0")
	}
}

func TestInviteService_GenerateWithExpiry(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_expiry")

	future := time.Now().Add(24 * time.Hour)
	invite, _ := svc.GenerateCode(user.ID, 10, &future)

	if invite.ExpiresAt == nil {
		t.Error("ExpiresAt should be set")
	}
	if invite.MaxUses != 10 {
		t.Errorf("MaxUses should be 10, got %d", invite.MaxUses)
	}
}

func TestInviteService_ListCodes(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_list")

	svc.GenerateCode(user.ID, 5, nil)
	svc.GenerateCode(user.ID, 3, nil)

	codes, err := svc.ListCodes(user.ID)
	if err != nil {
		t.Fatalf("ListCodes failed: %v", err)
	}
	if len(codes) != 2 {
		t.Errorf("Expected 2 codes, got %d", len(codes))
	}
}

func TestInviteService_ListCodes_OtherUserEmpty(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	userA := testutil.CreateTestUser(t, db, "inv_a")
	userB := testutil.CreateTestUser(t, db, "inv_b")

	svc.GenerateCode(userA.ID, 0, nil)

	codesB, _ := svc.ListCodes(userB.ID)
	if len(codesB) != 0 {
		t.Errorf("User B should see 0 codes, got %d", len(codesB))
	}
}

func TestInviteService_AcceptCode(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	inviter := testutil.CreateTestUser(t, db, "inv_inviter")
	acceptor := testutil.CreateTestUser(t, db, "inv_acceptor")

	invite, _ := svc.GenerateCode(inviter.ID, 1, nil)

	err := svc.AcceptCode(invite.Code, acceptor.ID)
	if err != nil {
		t.Fatalf("AcceptCode failed: %v", err)
	}

	var updated model.User
	db.First(&updated, acceptor.ID)
	if updated.InvitedBy == nil || *updated.InvitedBy != inviter.ID {
		t.Errorf("InvitedBy should be set to inviter ID %d", inviter.ID)
	}

	var reloaded model.InviteCode
	db.First(&reloaded, invite.ID)
	if reloaded.UsedCount != 1 {
		t.Errorf("UsedCount should be 1, got %d", reloaded.UsedCount)
	}
}

func TestInviteService_AcceptExpiredCode(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_exp")
	past := time.Now().Add(-1 * time.Hour)

	invite, _ := svc.GenerateCode(user.ID, 0, &past)

	err := svc.AcceptCode(invite.Code, user.ID)
	if err == nil {
		t.Error("Should reject expired code")
	}
}

func TestInviteService_AcceptExhaustedCode(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_exhaust")

	invite, _ := svc.GenerateCode(user.ID, 1, nil)
	svc.AcceptCode(invite.Code, user.ID)

	user2 := testutil.CreateTestUser(t, db, "inv_exhaust2")
	err := svc.AcceptCode(invite.Code, user2.ID)
	if err == nil {
		t.Error("Should reject exhausted code")
	}
}

func TestInviteService_AcceptNonexistent(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_nonexist")

	err := svc.AcceptCode("nonexistent_code_1234567890abcdef", user.ID)
	if err == nil {
		t.Error("Should reject nonexistent code")
	}
}

func TestInviteService_AcceptTamperedCode(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_tamper")
	invite, _ := svc.GenerateCode(user.ID, 0, nil)

	tampered := invite.Code[:len(invite.Code)-1] + "A"
	if invite.Code[len(invite.Code)-1] == 'A' {
		tampered = invite.Code[:len(invite.Code)-1] + "B"
	}

	err := svc.AcceptCode(tampered, user.ID)
	if err == nil {
		t.Error("Should reject tampered code")
	}
}

func TestInviteService_ValidateCode(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_validate")

	invite, _ := svc.GenerateCode(user.ID, 0, nil)

	validated, err := svc.ValidateCode(invite.Code)
	if err != nil {
		t.Fatalf("ValidateCode failed for valid code: %v", err)
	}
	if validated.ID != invite.ID {
		t.Error("Should return same invite")
	}
}

func TestInviteService_UniqueCodes(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewInviteService(db)
	user := testutil.CreateTestUser(t, db, "inv_unique")

	code1, _ := svc.GenerateCode(user.ID, 0, nil)
	code2, _ := svc.GenerateCode(user.ID, 0, nil)

	if code1.Code == code2.Code {
		t.Error("Codes should be unique")
	}
}
