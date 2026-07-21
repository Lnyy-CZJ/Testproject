package service

import (
	"bug-agent/internal/model"
	"fmt"
	"os"
	"sync"
	"testing"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func benchEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getBenchDSN() string {
	host := benchEnv("TEST_DB_HOST", "pgm-3ns6x7d1v7134cd24o.rwlb.rds.aliyuncs.com")
	port := benchEnv("TEST_DB_PORT", "5432")
	user := benchEnv("TEST_DB_USER", "skmsadmin")
	password := benchEnv("TEST_DB_PASSWORD", "skmsadmin@3c")
	dbname := benchEnv("TEST_DB_NAME", "hi_claw_test")

	return fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s search_path=public sslmode=disable",
		host, port, user, password, dbname)
}

func setupBenchmarkDB(b *testing.B) *gorm.DB {
	b.Helper()
	db, err := gorm.Open(postgres.Open(getBenchDSN()), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		b.Fatalf("Failed to connect test database: %v", err)
	}
	err = db.AutoMigrate(
		&model.User{}, &model.Role{}, &model.Permission{},
		&model.RolePermission{}, &model.UserRole{}, &model.AuditLog{},
	)
	if err != nil {
		b.Fatalf("Failed to migrate: %v", err)
	}
	return db
}

func createBenchUser(b *testing.B, db *gorm.DB, username string) model.User {
	suffix := fmt.Sprintf("_%d", time.Now().UnixNano())
	user := model.User{Username: username + suffix, Email: username + suffix + "@test.com", Password: "hash", Nickname: "Bench " + username}
	if err := db.Create(&user).Error; err != nil {
		b.Fatalf("Failed to create user: %v", err)
	}
	return user
}

func createBenchRoles(b *testing.B, db *gorm.DB) map[string]model.Role {
	roles := []model.Role{
		{Name: "super_admin", DisplayName: "Super Admin", IsSystem: true},
		{Name: "developer", DisplayName: "Developer", IsSystem: true},
	}
	for i := range roles {
		if err := db.Create(&roles[i]).Error; err != nil {
			b.Fatalf("Failed to create role: %v", err)
		}
	}
	perms := []model.Permission{
		{Code: "defects:create", Name: "Create Defect", Module: "defects"},
		{Code: "defects:read", Name: "Read Defect", Module: "defects"},
		{Code: "users:read", Name: "Read Users", Module: "users"},
	}
	for i := range perms {
		db.Create(&perms[i])
	}
	roleMap := make(map[string]model.Role)
	for _, r := range roles {
		roleMap[r.Name] = r
	}
	return roleMap
}

func assignBenchRole(b *testing.B, db *gorm.DB, userID uint, roleName string, roleMap map[string]model.Role) {
	role := roleMap[roleName]
	ur := model.UserRole{UserID: userID, RoleID: role.ID, ScopeType: "global"}
	if err := db.Create(&ur).Error; err != nil {
		b.Fatalf("Failed to assign role: %v", err)
	}
}

func BenchmarkRBAC_CacheHit(b *testing.B) {
	db := setupBenchmarkDB(b)
	rbacSvc := NewRBACService(db)
	user := createBenchUser(b, db, "bench_user")
	roleMap := createBenchRoles(b, db)
	assignBenchRole(b, db, user.ID, "super_admin", roleMap)
	rbacSvc.GetUserPermissions(user.ID)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		rbacSvc.HasPermission(user.ID, "defects:create")
	}
}

func BenchmarkRBAC_CacheMiss(b *testing.B) {
	db := setupBenchmarkDB(b)
	rbacSvc := NewRBACService(db)
	user := createBenchUser(b, db, "bench_miss_user")
	roleMap := createBenchRoles(b, db)
	assignBenchRole(b, db, user.ID, "developer", roleMap)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		rbacSvc.InvalidateCache(user.ID)
		rbacSvc.HasPermission(user.ID, "defects:create")
	}
}

func BenchmarkRBAC_ConcurrentLookup(b *testing.B) {
	db := setupBenchmarkDB(b)
	rbacSvc := NewRBACService(db)
	user := createBenchUser(b, db, "bench_concurrent_user")
	roleMap := createBenchRoles(b, db)
	assignBenchRole(b, db, user.ID, "super_admin", roleMap)
	rbacSvc.GetUserPermissions(user.ID)

	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			rbacSvc.HasPermission(user.ID, "defects:create")
			rbacSvc.HasPermission(user.ID, "users:read")
			rbacSvc.IsAdmin(user.ID)
		}
	})
}

func BenchmarkAudit_LogAction_Throughput(b *testing.B) {
	db := setupBenchmarkDB(b)
	auditSvc := NewAuditService(db)
	defer auditSvc.Stop()

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		auditSvc.LogAction(model.AuditLog{
			UserID:     1,
			Username:   "bench_user",
			Action:     fmt.Sprintf("bench_action_%d", i),
			TargetType: "benchmark",
			StatusCode: 200,
			DurationMs: 1,
			OldValue:   "null",
			NewValue:   "null",
		})
	}
}

func BenchmarkAudit_HighThroughput_Burst(b *testing.B) {
	db := setupBenchmarkDB(b)
	auditSvc := NewAuditService(db)
	defer auditSvc.Stop()

	batchSize := 50
	b.ResetTimer()

	for i := 0; i < b.N; i += batchSize {
		var wg sync.WaitGroup
		for j := 0; j < batchSize && i+j < b.N; j++ {
			wg.Add(1)
			go func(idx int) {
				defer wg.Done()
				auditSvc.LogAction(model.AuditLog{
					UserID:     uint(idx % 10),
					Username:   fmt.Sprintf("user_%d", idx%10),
					Action:     "burst_action",
					TargetType: "burst_test",
					StatusCode: 200,
					OldValue:   "null",
					NewValue:   "null",
				})
			}(i + j)
		}
		wg.Wait()
	}
}
