package cache

import (
	"context"
	"testing"
	"time"
)

func TestRateLimiter_Allow_UnderLimit(t *testing.T) {
	if RDB == nil {
		t.Skip("Redis not available")
	}
	rl := NewRateLimiter(100, 10)
	for i := 0; i < 5; i++ {
		allowed, _, err := rl.Allow(context.Background(), "test-under-limit")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if !allowed {
			t.Fatalf("Expected allowed at iteration %d", i)
		}
	}
}

func TestRateLimiter_Allow_OverLimit(t *testing.T) {
	if RDB == nil {
		t.Skip("Redis not available")
	}
	rl := NewRateLimiter(1000, 3)
	for i := 0; i < 3; i++ {
		rl.Allow(context.Background(), "test-over-limit")
	}
	allowed, retryAfter, _ := rl.Allow(context.Background(), "test-over-limit")
	if allowed {
		t.Error("Expected denied when over burst limit")
	}
	if retryAfter <= 0 {
		t.Errorf("Expected positive retryAfter, got %f", retryAfter)
	}
}

func TestDistributedLock_TryAcquire(t *testing.T) {
	if RDB == nil {
		t.Skip("Redis not available")
	}
	lock1 := NewLock("test-resource", 5*time.Second)
	lock2 := NewLock("test-resource", 5*time.Second)

	ctx := context.Background()
	acquired1 := lock1.TryAcquire(ctx)
	if !acquired1 {
		t.Fatal("First lock should be acquired")
	}

	acquired2 := lock2.TryAcquire(ctx)
	if acquired2 {
		t.Error("Second lock should fail when first holds it")
	}

	err := lock1.Release(ctx)
	if err != nil {
		t.Fatalf("Release failed: %v", err)
	}

	acquired3 := lock2.TryAcquire(ctx)
	if !acquired3 {
		t.Error("Third lock should succeed after first released")
	}
	lock2.Release(ctx)
}

func TestDistributedLock_Extend(t *testing.T) {
	if RDB == nil {
		t.Skip("Redis not available")
	}
	lock := NewLock("test-extend", 1*time.Second)
	ctx := context.Background()

	lock.TryAcquire(ctx)
	time.Sleep(500 * time.Millisecond)
	extended := lock.Extend(ctx, 2*time.Second)
	if !extended {
		t.Error("Extend should succeed while holding the lock")
	}
	lock.Release(ctx)
}

func TestSessionStore_CRUD(t *testing.T) {
	if RDB == nil {
		t.Skip("Redis not available")
	}
	store := NewSessionStore(1 * time.Hour)
	ctx := context.Background()

	data := map[string]interface{}{"user_id": 42, "role": "admin"}
	err := store.Set(ctx, 999, data)
	if err != nil {
		t.Fatalf("Set failed: %v", err)
	}

	retrieved, err := store.Get(ctx, 999)
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	if retrieved == nil {
		t.Fatal("Expected session data, got nil")
	}

	err = store.Delete(ctx, 999)
	if err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	afterDelete, _ := store.Get(ctx, 999)
	if afterDelete != nil {
		t.Error("Expected nil after delete")
	}
}

func TestCacheHelper_JSON(t *testing.T) {
	if RDB == nil {
		t.Skip("Redis not available")
	}
	helper := NewCacheHelper("test:", 10*time.Second)
	ctx := context.Background()

	type TestStruct struct{ Name string }
	val := TestStruct{Name: "hello"}
	helper.SetJSON(ctx, "key1", val)

	var result TestStruct
	err := helper.GetJSON(ctx, "key1", &result)
	if err != nil {
		t.Fatalf("GetJSON failed: %v", err)
	}
	if result.Name != "hello" {
		t.Errorf("Expected name=hello, got %s", result.Name)
	}

	helper.Invalidate(ctx, "key1")

	var empty TestStruct
	err = helper.GetJSON(ctx, "key1", &empty)
	if err != ErrCacheMiss {
		t.Errorf("Expected ErrCacheMiss after invalidate, got %v", err)
	}
}
