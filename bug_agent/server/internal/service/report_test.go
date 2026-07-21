package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestReportService_Dashboard(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user := testutil.CreateTestUser(t, db, "report_user")
	testutil.CreateTestDefect(t, db, "report-dash", user.ID)

	t.Run("dashboard returns summary", func(t *testing.T) {
		summary, err := svc.GetDashboard(0)
		assert.NoError(t, err)
		assert.NotNil(t, summary)
		assert.GreaterOrEqual(t, summary.TotalDefects, int64(1))
		assert.NotNil(t, summary.StatusDistribution)
		assert.NotNil(t, summary.SeverityDistribution)
		assert.NotNil(t, summary.WeeklyTrend)
		assert.Len(t, summary.WeeklyTrend, 7)
	})
}

func TestReportService_Trend(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user := testutil.CreateTestUser(t, db, "report_trend_user")

	for i := 0; i < 3; i++ {
		testutil.CreateTestDefect(t, db, fmt.Sprintf("trend-%d", i), user.ID)
	}

	t.Run("7 day trend", func(t *testing.T) {
		points, err := svc.GetTrend(7, "day", 0)
		assert.NoError(t, err)
		assert.Len(t, points, 7)
		for _, p := range points {
			assert.NotEmpty(t, p.Date)
			assert.GreaterOrEqual(t, p.Count, 0)
		}
	})

	t.Run("30 day trend", func(t *testing.T) {
		points, err := svc.GetTrend(30, "day", 0)
		assert.NoError(t, err)
		assert.Len(t, points, 30)
	})
}

func TestReportService_StatusDistribution(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user := testutil.CreateTestUser(t, db, "report_status_user")

	testutil.CreateTestDefect(t, db, "status-dist-1", user.ID)
	testutil.CreateTestDefect(t, db, "status-dist-2", user.ID)

	dist, err := svc.GetStatusDistribution(0)
	assert.NoError(t, err)
	assert.NotEmpty(t, dist)
	total := 0
	for _, d := range dist {
		assert.NotEmpty(t, d.Status)
		assert.Greater(t, d.Count, 0)
		total += d.Count
	}
	assert.GreaterOrEqual(t, total, 2)
}

func TestReportService_SeverityDistribution(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user := testutil.CreateTestUser(t, db, "report_sev_user")

	d1 := testutil.CreateTestDefect(t, db, "sev-dist-1", user.ID)
	db.Model(&d1).Update("severity", "critical")

	d2 := testutil.CreateTestDefect(t, db, "sev-dist-2", user.ID)
	db.Model(&d2).Update("severity", "normal")

	dist, err := svc.GetSeverityDistribution(0)
	assert.NoError(t, err)
	assert.NotEmpty(t, dist)

	sevMap := make(map[string]int)
	for _, d := range dist {
		sevMap[d.Severity] = d.Count
	}
	assert.Contains(t, sevMap, "critical")
	assert.Contains(t, sevMap, "normal")
}

func TestReportService_TeamMetrics(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user1 := testutil.CreateTestUser(t, db, "team_user1")
	user2 := testutil.CreateTestUser(t, db, "team_user2")

	d1 := testutil.CreateTestDefect(t, db, "team-metric-1", user1.ID)
	db.Model(&d1).Update("assignee_id", user2.ID)

	d2 := testutil.CreateTestDefect(t, db, "team-metric-2", user1.ID)
	db.Model(&d2).Update("assignee_id", user2.ID)
	db.Model(&d2).Update("status", model.DefectStatusCompleted)

	metrics, err := svc.GetTeamMetrics(0)
	assert.NoError(t, err)
	if len(metrics) > 0 {
		m := metrics[0]
		assert.Greater(t, m.Total, 0)
	}
}

func TestReportService_ExportCSV(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user := testutil.CreateTestUser(t, db, "export_csv_user")
	testutil.CreateTestDefect(t, db, "export-csv-defect", user.ID)

	csvData, err := svc.ExportCSV(0, "all")
	assert.NoError(t, err)
	assert.NotEmpty(t, csvData)
	assert.True(t, strings.HasPrefix(csvData, "Code,Title"))
	assert.Contains(t, csvData, "export-csv-defect")
}

func TestReportService_ExportJSON(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user := testutil.CreateTestUser(t, db, "export_json_user")
	testutil.CreateTestDefect(t, db, "export-json-defect", user.ID)

	jsonData, err := svc.ExportJSON(0, "all")
	assert.NoError(t, err)
	assert.NotEmpty(t, jsonData)
}

func TestReportService_ExportWithFilter(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewReportService(db)
	user := testutil.CreateTestUser(t, db, "export_filter_user")

	d1 := testutil.CreateTestDefect(t, db, "filter-new", user.ID)
	db.Model(&d1).Update("status", model.DefectStatusNew)

	d2 := testutil.CreateTestDefect(t, db, "filter-completed", user.ID)
	db.Model(&d2).Update("status", model.DefectStatusCompleted)

	csvAll, _ := svc.ExportCSV(0, "all")
	csvNew, _ := svc.ExportCSV(0, model.DefectStatusNew)

	linesAll := strings.Count(csvAll, "\n")
	linesNew := strings.Count(csvNew, "\n")

	assert.Greater(t, linesAll, linesNew)
	assert.Contains(t, csvNew, "filter-new")
	assert.NotContains(t, csvNew, "filter-completed")
}
