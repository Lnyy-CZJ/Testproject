package service

import (
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"gorm.io/gorm"
)

type ReportService struct {
	db *gorm.DB
}

func NewReportService(db *gorm.DB) *ReportService {
	return &ReportService{db: db}
}

type TrendPoint struct {
	Date  string `json:"date"`
	Count int    `json:"count"`
}

type StatusDistribution struct {
	Status string `json:"status"`
	Count  int    `json:"count"`
}

type SeverityDistribution struct {
	Severity string `json:"severity"`
	Count    int    `json:"count"`
}

type TeamMetric struct {
	UserID     uint    `json:"userId"`
	Username   string  `json:"username"`
	Total      int     `json:"total"`
	Resolved   int     `json:"resolved"`
	Pending    int     `json:"pending"`
	AvgResolve float64 `json:"avgResolveHours"`
}

type DashboardSummary struct {
	TotalDefects         int64                  `json:"totalDefects"`
	NewToday             int64                  `json:"newToday"`
	ResolvedToday        int64                  `json:"resolvedToday"`
	OpenDefects          int64                  `json:"openDefects"`
	CriticalOpen         int64                  `json:"criticalOpen"`
	StatusDistribution   []StatusDistribution   `json:"statusDistribution"`
	SeverityDistribution []SeverityDistribution `json:"severityDistribution"`
	WeeklyTrend          []TrendPoint           `json:"weeklyTrend"`
}

func (s *ReportService) GetDashboard(projectID uint) (*DashboardSummary, error) {
	var summary DashboardSummary
	todayStr := time.Now().Truncate(24 * time.Hour).Format("2006-01-02")
	openStatuses := []string{
		model.DefectStatusNew, model.DefectStatusPendingAssign,
		model.DefectStatusPendingAnalysis, model.DefectStatusAnalyzing,
		model.DefectStatusPendingFix, model.DefectStatusFixing,
		model.DefectStatusManualFixing,
		model.DefectStatusPendingVerify, model.DefectStatusReopened, model.DefectStatusSuspended,
	}

	baseQuery := s.db.Model(&model.Defect{})
	if projectID > 0 {
		baseQuery = baseQuery.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	if err := baseQuery.Count(&summary.TotalDefects).Error; err != nil {
		logger.Errorf("查询缺陷总数失败: %v", err)
	}

	newTodayQ := s.db.Model(&model.Defect{}).Where("created_at::date = ?", todayStr)
	if projectID > 0 {
		newTodayQ = newTodayQ.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	if err := newTodayQ.Count(&summary.NewToday).Error; err != nil {
		logger.Errorf("查询今日新增缺陷失败: %v", err)
	}
	resolvedTodayQ := s.db.Model(&model.Defect{}).Where("updated_at::date = ? AND status IN ?", todayStr, []string{"completed", "rejected"})
	if projectID > 0 {
		resolvedTodayQ = resolvedTodayQ.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	if err := resolvedTodayQ.Count(&summary.ResolvedToday).Error; err != nil {
		logger.Errorf("查询今日解决缺陷失败: %v", err)
	}

	openQ := s.db.Model(&model.Defect{}).Where("status IN ?", openStatuses)
	if projectID > 0 {
		openQ = openQ.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	if err := openQ.Count(&summary.OpenDefects).Error; err != nil {
		logger.Errorf("查询开放缺陷失败: %v", err)
	}

	critQ := s.db.Model(&model.Defect{}).Where("status IN ? AND severity IN ?", openStatuses, []string{"critical", "urgent"})
	if projectID > 0 {
		critQ = critQ.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	if err := critQ.Count(&summary.CriticalOpen).Error; err != nil {
		logger.Errorf("查询严重开放缺陷失败: %v", err)
	}

	statusDist, _ := s.GetStatusDistribution(projectID)
	summary.StatusDistribution = statusDist
	sevDist, _ := s.GetSeverityDistribution(projectID)
	summary.SeverityDistribution = sevDist
	weeklyTrend, _ := s.GetTrend(7, "day", projectID)
	summary.WeeklyTrend = weeklyTrend
	return &summary, nil
}

func (s *ReportService) GetTrend(days int, interval string, projectID uint) ([]TrendPoint, error) {
	var results []struct {
		Date  string
		Count int
	}
	now := time.Now()
	since := now.AddDate(0, 0, -days).Format("2006-01-02")
	query := s.db.Model(&model.Defect{}).
		Select("created_at::date as date, COUNT(*) as count").
		Where("created_at >= ?", since).
		Group("date").Order("date")
	if projectID > 0 {
		query = query.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	err := query.Scan(&results).Error
	if err != nil {
		return nil, err
	}
	pointMap := make(map[string]int)
	for _, r := range results {
		pointMap[r.Date] = r.Count
	}
	var points []TrendPoint
	for i := days - 1; i >= 0; i-- {
		d := now.AddDate(0, 0, -i).Format("2006-01-02")
		points = append(points, TrendPoint{Date: d, Count: pointMap[d]})
	}
	return points, nil
}

func (s *ReportService) GetStatusDistribution(projectID uint) ([]StatusDistribution, error) {
	var results []struct {
		Status string
		Count  int
	}
	query := s.db.Model(&model.Defect{}).
		Select("status, COUNT(*) as count").
		Group("status").Order("count DESC")
	if projectID > 0 {
		query = query.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	err := query.Scan(&results).Error
	if err != nil {
		return nil, err
	}
	dist := make([]StatusDistribution, len(results))
	for i, r := range results {
		dist[i] = StatusDistribution{Status: r.Status, Count: r.Count}
	}
	return dist, nil
}

func (s *ReportService) GetSeverityDistribution(projectID uint) ([]SeverityDistribution, error) {
	var results []struct {
		Severity string
		Count    int
	}
	query := s.db.Model(&model.Defect{}).
		Select("severity, COUNT(*) as count").
		Group("severity").Order("count DESC")
	if projectID > 0 {
		query = query.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	err := query.Scan(&results).Error
	if err != nil {
		return nil, err
	}
	dist := make([]SeverityDistribution, len(results))
	for i, r := range results {
		dist[i] = SeverityDistribution{Severity: r.Severity, Count: r.Count}
	}
	return dist, nil
}

func (s *ReportService) GetTeamMetrics(projectID uint) ([]TeamMetric, error) {
	var results []struct {
		UserID   uint
		Username string
		Total    int64
		Resolved int64
	}
	query := s.db.Table("defects d").
		Select("d.assignee_id as user_id, u.username, COUNT(*) as total, " +
			"SUM(CASE WHEN d.status IN ('completed','rejected') THEN 1 ELSE 0 END)::int as resolved").
		Joins("LEFT JOIN users u ON u.id = d.assignee_id").
		Where("d.assignee_id IS NOT NULL").
		Group("d.assignee_id, u.username")
	if projectID > 0 {
		query = query.Joins("JOIN iterations i ON i.id = d.iteration_id").Where("i.project_id = ?", projectID)
	}
	err := query.Scan(&results).Error
	if err != nil {
		return nil, err
	}
	metrics := make([]TeamMetric, len(results))
	for i, r := range results {
		metrics[i] = TeamMetric{
			UserID:   r.UserID,
			Username: r.Username,
			Total:    int(r.Total),
			Resolved: int(r.Resolved),
			Pending:  int(r.Total - r.Resolved),
		}
	}
	return metrics, nil
}

func (s *ReportService) ExportCSV(projectID uint, status string) (string, error) {
	var defects []model.Defect
	query := s.db.Model(&model.Defect{}).Order("id asc").Limit(10000)
	if projectID > 0 {
		query = query.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	if status != "" && status != "all" {
		query = query.Where("status = ?", status)
	}
	err := query.Find(&defects).Error
	if err != nil {
		return "", err
	}
	var buf strings.Builder
	w := csv.NewWriter(&buf)
	w.Write([]string{"Code", "Title", "Severity", "Priority", "Type", "Status", "ReporterID", "AssigneeID", "IterationID", "CreatedAt", "UpdatedAt"})
	for _, d := range defects {
		assigneeStr := "0"
		if d.AssigneeID != nil {
			assigneeStr = fmt.Sprintf("%d", *d.AssigneeID)
		}
		w.Write([]string{
			d.Code, d.Title, d.Severity, d.Priority,
			d.Type, d.Status, fmt.Sprintf("%d", d.ReporterID), assigneeStr,
			fmt.Sprintf("%d", d.IterationID),
			d.CreatedAt.Format("2006-01-02 15:04"),
			d.UpdatedAt.Format("2006-01-02 15:04"),
		})
	}
	w.Flush()
	return buf.String(), nil
}

func (s *ReportService) ExportJSON(projectID uint, status string) (string, error) {
	query := s.db.Model(&model.Defect{}).Order("id asc").Limit(10000)
	if projectID > 0 {
		query = query.Joins("Iteration").Where("Iteration.project_id = ?", projectID)
	}
	if status != "" && status != "all" {
		query = query.Where("status = ?", status)
	}
	var defects []model.Defect
	err := query.Find(&defects).Error
	if err != nil {
		return "", err
	}
	data, err := json.MarshalIndent(defects, "", "  ")
	if err != nil {
		return "", err
	}
	return string(data), nil
}
