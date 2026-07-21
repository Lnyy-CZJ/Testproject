package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"errors"
	"testing"
)

func TestNotificationPrefService_GetPreferences_Defaults(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_default")

	prefs, err := svc.GetPreferences(user.ID)
	if err != nil {
		t.Fatalf("GetPreferences failed: %v", err)
	}
	if len(prefs) != 8 {
		t.Fatalf("Expected 8 default preferences, got %d", len(prefs))
	}

	categories := make(map[string]bool)
	for _, p := range prefs {
		categories[p.Category] = true
		if p.UserID != user.ID {
			t.Errorf("UserID mismatch: %d vs %d", p.UserID, user.ID)
		}
	}

	expectedCats := []string{
		"defect_assigned",
		"defect_status_change",
		"defect_mention",
		"defect_due_soon",
		"iteration_start",
		"iteration_end",
		"collaboration_complete",
		"system_announce",
	}
	for _, cat := range expectedCats {
		if !categories[cat] {
			t.Errorf("Missing default category: %s", cat)
		}
	}
}

func TestNotificationPrefService_GetPreferences_Existing(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_existing")

	prefs1, _ := svc.GetPreferences(user.ID)
	if len(prefs1) == 0 {
		t.Fatal("Expected defaults to be created")
	}

	prefs2, err := svc.GetPreferences(user.ID)
	if err != nil {
		t.Fatalf("Second call failed: %v", err)
	}
	if len(prefs2) != len(prefs1) {
		t.Errorf("Should return same count on second call: %d vs %d", len(prefs2), len(prefs1))
	}
}

func TestNotificationPrefService_UpdatePreference(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_update")

	prefs, err := svc.GetPreferences(user.ID)
	if err != nil {
		t.Fatalf("GetPreferences failed: %v", err)
	}

	targetPref := prefs[0]
	oldChannels := targetPref.Channels

	updated, err := svc.UpdatePreference(user.ID, targetPref.ID, "in_app,email,webhook")
	if err != nil {
		t.Fatalf("UpdatePreference failed: %v", err)
	}
	if updated.Channels != "in_app,email,webhook" {
		t.Errorf("Channels not updated: %s", updated.Channels)
	}
	if updated.Channels == oldChannels && oldChannels != "in_app,email,webhook" {
		t.Error("Channels should have changed")
	}
}

func TestNotificationPrefService_UpdatePreference_NotFound(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_notfound")

	_, err := svc.UpdatePreference(user.ID, 99999, "in_app")
	if err == nil {
		t.Error("Should return error for non-existent preference")
	}
}

func TestNotificationPrefService_BatchUpdate(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_batch")

	updates := map[string]string{
		"defect_status_change": "in_app",
		"defect_assigned":      "email",
		"defect_mention":       "",
	}

	err := svc.BatchUpdate(user.ID, updates)
	if err != nil {
		t.Fatalf("BatchUpdate failed: %v", err)
	}

	prefs, err := svc.GetPreferences(user.ID)
	if err != nil {
		t.Fatalf("GetPreferences after batch update failed: %v", err)
	}

	prefMap := make(map[string]model.NotificationPreference)
	for _, p := range prefs {
		prefMap[p.Category] = p
	}

	if prefMap["defect_status_change"].Channels != "in_app" {
		t.Errorf("defect_status_change channels: got %s, want in_app", prefMap["defect_status_change"].Channels)
	}
	if prefMap["defect_assigned"].Channels != "email" {
		t.Errorf("defect_assigned channels: got %s, want email", prefMap["defect_assigned"].Channels)
	}
	if prefMap["defect_mention"].Channels != "" {
		t.Errorf("defect_mention channels: got %s, want empty", prefMap["defect_mention"].Channels)
	}
}

func TestNotificationPrefService_BatchUpdate_RejectUnsupportedCategory(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_new_cat")

	updates := map[string]string{
		"custom_category": "in_app",
	}

	err := svc.BatchUpdate(user.ID, updates)
	if !errors.Is(err, ErrInvalidNotificationCategory) {
		t.Fatalf("Expected ErrInvalidNotificationCategory, got %v", err)
	}
}

func TestNotificationPrefService_BatchUpdate_RejectUnsupportedChannel(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_bad_channel")

	err := svc.BatchUpdate(user.ID, map[string]string{
		"defect_assigned": "sms",
	})
	if !errors.Is(err, ErrInvalidNotificationChannels) {
		t.Fatalf("Expected ErrInvalidNotificationChannels, got %v", err)
	}
}

func TestNotificationPrefService_IsEnabled(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	user := testutil.CreateTestUser(t, db, "pref_enabled")

	svc.GetPreferences(user.ID) // ensure defaults exist

	tests := []struct {
		category string
		channel  string
		want     bool
	}{
		{"defect_status_change", "in_app", true},
		{"defect_status_change", "email", true},
		{"defect_status_change", "webhook", false},
		{"defect_mention", "in_app", true},
		{"defect_mention", "email", true},
		{"nonexistent", "in_app", true},
	}

	for _, tt := range tests {
		got := svc.IsEnabled(user.ID, tt.category, tt.channel)
		if got != tt.want {
			t.Errorf("IsEnabled(%s, %s) = %v, want %v", tt.category, tt.channel, got, tt.want)
		}
	}
}

func TestNotificationPrefService_UserIsolation(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewNotificationPrefService(db)
	userA := testutil.CreateTestUser(t, db, "pref_user_a")
	userB := testutil.CreateTestUser(t, db, "pref_user_b")

	prefsA, _ := svc.GetPreferences(userA.ID)
	prefsB, _ := svc.GetPreferences(userB.ID)

	if len(prefsA) != len(prefsB) {
		t.Errorf("Both users should get same number of defaults")
	}

	_, err := svc.UpdatePreference(userA.ID, prefsA[0].ID, "webhook")
	if err != nil {
		t.Fatalf("Update A's pref failed: %v", err)
	}

	prefsA2, _ := svc.GetPreferences(userA.ID)
	prefsB2, _ := svc.GetPreferences(userB.ID)

	for _, pa := range prefsA2 {
		if pa.Category == prefsA[0].Category {
			if pa.Channels != "webhook" {
				t.Errorf("User A's pref should be updated to webhook, got %s", pa.Channels)
			}
		}
	}
	for _, pb := range prefsB2 {
		if pb.Category == prefsA[0].Category {
			if pb.Channels == "webhook" {
				t.Error("User B's pref should NOT be affected by User A's update")
			}
		}
	}
}
