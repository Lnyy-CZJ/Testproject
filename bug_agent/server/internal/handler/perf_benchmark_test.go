package handler

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func initPerfRouter(userID uint, register func(r *gin.Engine)) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userID", userID)
		c.Next()
	})
	register(r)
	return r
}

func seedDefectListBenchmarkData(b *testing.B, db *gorm.DB) (uint, uint) {
	b.Helper()

	user := testutil.CreateTestUser(b, db, "perf_defect_user")
	project := testutil.CreateTestProject(b, db, "Perf Defect Project", "PDEF")

	if err := db.Create(&model.ProjectMember{
		ProjectID: project.ID,
		UserID:    user.ID,
		Role:      "developer",
	}).Error; err != nil {
		b.Fatalf("create project member: %v", err)
	}

	iterations := make([]model.Iteration, 0, 20)
	now := time.Now()
	for i := 0; i < 20; i++ {
		iterations = append(iterations, model.Iteration{
			ProjectID: project.ID,
			Name:      fmt.Sprintf("Perf Iter %d", i+1),
			Status:    "active",
			StartDate: now.AddDate(0, 0, -14*(i+1)),
			EndDate:   now.AddDate(0, 0, 14*(i+1)),
		})
	}
	if err := db.CreateInBatches(iterations, 100).Error; err != nil {
		b.Fatalf("create iterations: %v", err)
	}

	statuses := []string{
		model.DefectStatusPendingAssign,
		model.DefectStatusPendingAnalysis,
		model.DefectStatusAnalyzing,
		model.DefectStatusPendingFix,
		model.DefectStatusFixing,
		model.DefectStatusPendingVerify,
		model.DefectStatusFixed,
		model.DefectStatusCompleted,
	}
	severities := []string{
		model.SeverityFatal,
		model.SeverityMajor,
		model.SeverityNormal,
		model.SeverityMinor,
	}
	priorities := []string{
		model.PriorityP0,
		model.PriorityP1,
		model.PriorityP2,
		model.PriorityP3,
	}
	types := []string{
		model.DefectTypeFunctional,
		model.DefectTypeUI,
		model.DefectTypePerformance,
		model.DefectTypeSecurity,
	}

	defects := make([]model.Defect, 0, 20000)
	for i := 0; i < 20000; i++ {
		iter := iterations[i%len(iterations)]
		defects = append(defects, model.Defect{
			Code:        fmt.Sprintf("PERF-DEF-%05d", i),
			IterationID: iter.ID,
			Title:       fmt.Sprintf("Performance defect %d", i),
			Description: "benchmark payload",
			Severity:    severities[i%len(severities)],
			Priority:    priorities[i%len(priorities)],
			Type:        types[i%len(types)],
			Status:      statuses[i%len(statuses)],
			ReporterID:  user.ID,
			Tags:        "perf,benchmark",
			CreatedAt:   now.Add(-time.Duration(i) * time.Minute),
			UpdatedAt:   now.Add(-time.Duration(i) * time.Minute),
		})
	}
	if err := db.CreateInBatches(defects, 1000).Error; err != nil {
		b.Fatalf("create defects: %v", err)
	}

	return user.ID, project.ID
}

func seedUserProjectsBenchmarkData(b *testing.B, db *gorm.DB) uint {
	b.Helper()

	owner := testutil.CreateTestUser(b, db, "perf_project_owner")

	extraUsers := make([]model.User, 0, 30)
	for i := 0; i < 30; i++ {
		extraUsers = append(extraUsers, model.User{
			Username: fmt.Sprintf("perf_member_%d", i),
			Email:    fmt.Sprintf("perf_member_%d@test.com", i),
			Password: "hashed_password",
			Nickname: fmt.Sprintf("成员%d", i),
		})
	}
	if err := db.CreateInBatches(extraUsers, 200).Error; err != nil {
		b.Fatalf("create extra users: %v", err)
	}

	projects := make([]model.Project, 0, 400)
	for i := 0; i < 400; i++ {
		projects = append(projects, model.Project{
			Name:   fmt.Sprintf("Perf Project %03d", i),
			Code:   fmt.Sprintf("PP%03d", i),
			Status: "active",
		})
	}
	if err := db.CreateInBatches(projects, 200).Error; err != nil {
		b.Fatalf("create projects: %v", err)
	}

	members := make([]model.ProjectMember, 0, 400*6)
	for i, p := range projects {
		members = append(members, model.ProjectMember{
			ProjectID: p.ID,
			UserID:    owner.ID,
			Role:      "developer",
		})
		for j := 0; j < 5; j++ {
			u := extraUsers[(i+j)%len(extraUsers)]
			members = append(members, model.ProjectMember{
				ProjectID: p.ID,
				UserID:    u.ID,
				Role:      "developer",
			})
		}
	}
	if err := db.CreateInBatches(members, 1000).Error; err != nil {
		b.Fatalf("create members: %v", err)
	}

	now := time.Now()
	iterations := make([]model.Iteration, 0, len(projects)*3)
	for _, p := range projects {
		for j := 0; j < 3; j++ {
			iterations = append(iterations, model.Iteration{
				ProjectID: p.ID,
				Name:      fmt.Sprintf("Sprint-%d", j+1),
				Status:    "active",
				StartDate: now.AddDate(0, 0, -14*(j+1)),
				EndDate:   now.AddDate(0, 0, 14*(j+1)),
			})
		}
	}
	if err := db.CreateInBatches(iterations, 1000).Error; err != nil {
		b.Fatalf("create iterations: %v", err)
	}

	statuses := []string{
		model.DefectStatusPendingAssign,
		model.DefectStatusPendingAnalysis,
		model.DefectStatusAnalyzing,
		model.DefectStatusPendingFix,
		model.DefectStatusFixing,
		model.DefectStatusPendingVerify,
		model.DefectStatusFixed,
		model.DefectStatusCompleted,
	}
	defects := make([]model.Defect, 0, len(iterations)*20)
	for i, iter := range iterations {
		for j := 0; j < 20; j++ {
			idx := i*20 + j
			defects = append(defects, model.Defect{
				Code:        fmt.Sprintf("PERF-PROJ-%06d", idx),
				IterationID: iter.ID,
				Title:       fmt.Sprintf("Project list defect %d", idx),
				Description: "benchmark payload",
				Severity:    model.SeverityNormal,
				Priority:    model.PriorityP2,
				Type:        model.DefectTypeFunctional,
				Status:      statuses[idx%len(statuses)],
				ReporterID:  owner.ID,
				CreatedAt:   now.Add(-time.Duration(idx) * time.Minute),
				UpdatedAt:   now.Add(-time.Duration(idx) * time.Minute),
			})
		}
	}
	if err := db.CreateInBatches(defects, 2000).Error; err != nil {
		b.Fatalf("create defects: %v", err)
	}

	var ownerProjectCount int64
	if err := db.Model(&model.ProjectMember{}).Where("user_id = ?", owner.ID).Count(&ownerProjectCount).Error; err != nil {
		b.Fatalf("verify owner projects: %v", err)
	}
	if ownerProjectCount != int64(len(projects)) {
		b.Fatalf("unexpected owner project count: got=%d want=%d", ownerProjectCount, len(projects))
	}

	return owner.ID
}

func seedCollaborationPollingBenchmarkData(b *testing.B, db *gorm.DB) (uint, uint) {
	b.Helper()

	user := testutil.CreateTestUser(b, db, "perf_collab_user")
	defect := testutil.CreateTestDefect(b, db, "perf-collab-defect", user.ID)

	task := model.CollaborationTask{
		DefectID:      defect.ID,
		TriggerUserID: user.ID,
		Status:        model.CollaborationStatusRunning,
		AgentTypes:    "frontend,backend,test,ui,product,client",
	}
	if err := db.Create(&task).Error; err != nil {
		b.Fatalf("create task: %v", err)
	}

	reports := make([]model.CollaborationReport, 0, 600)
	agentTypes := []string{"frontend", "backend", "test", "ui", "product", "client"}
	for i := 0; i < 600; i++ {
		reports = append(reports, model.CollaborationReport{
			TaskID:    task.ID,
			AgentType: agentTypes[i%len(agentTypes)],
			Status:    model.CollabReportStatusAnalyzing,
		})
	}
	if err := db.CreateInBatches(reports, 1000).Error; err != nil {
		b.Fatalf("create reports: %v", err)
	}

	return user.ID, task.ID
}

func BenchmarkDefectHandler_ListDefects_LargeDataset(b *testing.B) {
	db := testutil.SetupTestDB(b)
	userID, projectID := seedDefectListBenchmarkData(b, db)
	h := NewDefectHandler(model.DB)

	router := initPerfRouter(userID, func(r *gin.Engine) {
		r.GET("/defects", h.ListDefects)
	})

	url := fmt.Sprintf("/defects?projectId=%d&status=pending_assign,pending_analysis,analyzing&page=1&size=20&sortBy=created_at&orderBy=desc", projectID)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		router.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			b.Fatalf("unexpected status: %d body=%s", w.Code, w.Body.String())
		}
	}
}

func BenchmarkUserProjectsHandler_ListUserProjects_LargeDataset(b *testing.B) {
	db := testutil.SetupTestDB(b)
	userID := seedUserProjectsBenchmarkData(b, db)
	h := NewUserProjectsHandler(model.DB)

	router := initPerfRouter(userID, func(r *gin.Engine) {
		r.GET("/user/projects", h.ListUserProjects)
	})

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, "/user/projects", nil)
		router.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			b.Fatalf("unexpected status: %d body=%s", w.Code, w.Body.String())
		}
	}
}

func BenchmarkCollaborationHandler_GetCollaborationTask_Polling(b *testing.B) {
	db := testutil.SetupTestDB(b)
	userID, taskID := seedCollaborationPollingBenchmarkData(b, db)
	h := NewCollaborationHandler(db, nil)

	router := initPerfRouter(userID, func(r *gin.Engine) {
		r.GET("/collaborations/:taskId", h.GetCollaborationTask)
	})

	url := fmt.Sprintf("/collaborations/%d", taskID)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		router.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			b.Fatalf("unexpected status: %d body=%s", w.Code, w.Body.String())
		}
	}
}
