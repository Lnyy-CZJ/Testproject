package service

import (
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"sort"
	"strings"

	"gorm.io/gorm"
)

type QualityIssuePoolSummary struct {
	TotalClusters     int `json:"totalClusters"`
	OpenClusters      int `json:"openClusters"`
	ConvertedClusters int `json:"convertedClusters"`
	IgnoredClusters   int `json:"ignoredClusters"`
	TotalSignals      int `json:"totalSignals"`
	AffectedUserCount int `json:"affectedUserCount"`
}

type QualityRegressionSummary struct {
	TotalItems    int `json:"totalItems"`
	OpenItems     int `json:"openItems"`
	VerifiedItems int `json:"verifiedItems"`
	ArchivedItems int `json:"archivedItems"`
}

type QualityReleaseHealthSummary struct {
	BaselineCount     int `json:"baselineCount"`
	NormalCount       int `json:"normalCount"`
	WatchAnomalyCount int `json:"watchAnomalyCount"`
	HighAnomalyCount  int `json:"highAnomalyCount"`
}

type QualityAISummary struct {
	AnalysisCount     int     `json:"analysisCount"`
	FixTaskCount      int     `json:"fixTaskCount"`
	SuccessfulCount   int     `json:"successfulCount"`
	FallbackCount     int     `json:"fallbackCount"`
	FailedCount       int     `json:"failedCount"`
	AverageDurationMs int64   `json:"averageDurationMs"`
	TotalTokens       int     `json:"totalTokens"`
	EstimatedCostUSD  float64 `json:"estimatedCostUsd"`
}

type QualitySourceBreakdown struct {
	SourceType        string `json:"sourceType"`
	SignalCount       int    `json:"signalCount"`
	ClusterCount      int    `json:"clusterCount"`
	AffectedUserCount int    `json:"affectedUserCount"`
}

type QualityModuleHotspot struct {
	ModuleID                *uint  `json:"moduleId,omitempty"`
	ModuleName              string `json:"moduleName"`
	ClusterCount            int    `json:"clusterCount"`
	OpenClusterCount        int    `json:"openClusterCount"`
	ConvertedClusterCount   int    `json:"convertedClusterCount"`
	AffectedUserCount       int    `json:"affectedUserCount"`
	HighAnomalyClusterCount int    `json:"highAnomalyClusterCount"`
}

type QualityInsightsOverview struct {
	IssuePool           QualityIssuePoolSummary     `json:"issuePool"`
	Regression          QualityRegressionSummary    `json:"regression"`
	ReleaseHealth       QualityReleaseHealthSummary `json:"releaseHealth"`
	AI                  QualityAISummary            `json:"ai"`
	SourceBreakdowns    []QualitySourceBreakdown    `json:"sourceBreakdowns"`
	ModuleHotspots      []QualityModuleHotspot      `json:"moduleHotspots"`
	TopReleaseAnomalies []AppReleaseTrendItem       `json:"topReleaseAnomalies"`
}

type QualityInsightsService struct {
	db         *gorm.DB
	routingSvc *ProjectRoutingService
	triageSvc  *SignalTriageService
}

func NewQualityInsightsService(db *gorm.DB) *QualityInsightsService {
	return &QualityInsightsService{
		db:         db,
		routingSvc: NewProjectRoutingService(db),
		triageSvc:  NewSignalTriageService(db),
	}
}

func (s *QualityInsightsService) GetOverview(projectID uint) (*QualityInsightsOverview, error) {
	issuePool, err := s.buildIssuePoolSummaryAgg(projectID)
	if err != nil {
		return nil, err
	}

	regression, err := s.buildRegressionSummaryAgg(projectID)
	if err != nil {
		return nil, err
	}

	releaseTrends, err := s.routingSvc.ListReleaseTrends(projectID)
	if err != nil {
		return nil, err
	}

	sourceBreakdowns, err := s.buildSourceBreakdownsAgg(projectID)
	if err != nil {
		return nil, err
	}

	moduleHotspots, clusterAnomalies, err := s.buildModuleHotspotsAgg(projectID)
	if err != nil {
		return nil, err
	}

	overview := &QualityInsightsOverview{
		IssuePool:           *issuePool,
		Regression:          *regression,
		ReleaseHealth:       buildReleaseHealthSummary(releaseTrends),
		AI:                  buildAISummaryAgg(s.db, projectID),
		SourceBreakdowns:    sourceBreakdowns,
		ModuleHotspots:      moduleHotspots,
		TopReleaseAnomalies: buildTopReleaseAnomalies(releaseTrends),
	}
	_ = clusterAnomalies
	return overview, nil
}

func (s *QualityInsightsService) buildIssuePoolSummaryAgg(projectID uint) (*QualityIssuePoolSummary, error) {
	summary := QualityIssuePoolSummary{}

	type clusterAgg struct {
		OpenCount      int64
		ConvertedCount int64
		IgnoredCount   int64
		TotalCount     int64
		AffectedUsers  int64
	}
	var ca clusterAgg
	if err := s.db.Model(&model.IssueCluster{}).
		Where("project_id = ?", projectID).
		Select(`COUNT(*) as total_count,
			SUM(CASE WHEN status = 'converted' THEN 1 ELSE 0 END) as converted_count,
			SUM(CASE WHEN status IN ('ignored','closed') THEN 1 ELSE 0 END) as ignored_count,
			SUM(CASE WHEN status NOT IN ('converted','ignored','closed') THEN 1 ELSE 0 END) as open_count,
			COALESCE(SUM(affected_user_count), 0) as affected_users`).
		Scan(&ca).Error; err != nil {
		return nil, err
	}

	var signalCount int64
	if err := s.db.Model(&model.IssueSignal{}).Where("project_id = ?", projectID).Count(&signalCount).Error; err != nil {
		return nil, err
	}

	summary.TotalClusters = int(ca.TotalCount)
	summary.OpenClusters = int(ca.OpenCount)
	summary.ConvertedClusters = int(ca.ConvertedCount)
	summary.IgnoredClusters = int(ca.IgnoredCount)
	summary.TotalSignals = int(signalCount)
	summary.AffectedUserCount = int(ca.AffectedUsers)
	return &summary, nil
}

func (s *QualityInsightsService) buildRegressionSummaryAgg(projectID uint) (*QualityRegressionSummary, error) {
	summary := QualityRegressionSummary{}

	type regAgg struct {
		TotalCount    int64
		OpenCount     int64
		VerifiedCount int64
		ArchivedCount int64
	}
	var ra regAgg
	if err := s.db.Model(&model.RegressionItem{}).
		Where("project_id = ?", projectID).
		Select(`COUNT(*) as total_count,
			SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) as verified_count,
			SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) as archived_count,
			SUM(CASE WHEN status NOT IN ('verified','archived') THEN 1 ELSE 0 END) as open_count`).
		Scan(&ra).Error; err != nil {
		return nil, err
	}

	summary.TotalItems = int(ra.TotalCount)
	summary.OpenItems = int(ra.OpenCount)
	summary.VerifiedItems = int(ra.VerifiedCount)
	summary.ArchivedItems = int(ra.ArchivedCount)
	return &summary, nil
}

func (s *QualityInsightsService) buildSourceBreakdownsAgg(projectID uint) ([]QualitySourceBreakdown, error) {
	type srcAgg struct {
		SourceType      string
		SignalCount     int64
		AffectedUserSum int64
		ClusterCount    int64
	}
	var rows []srcAgg
	if err := s.db.Model(&model.IssueSignal{}).
		Where("project_id = ?", projectID).
		Select("source_type, COUNT(*) as signal_count, COALESCE(SUM(affected_user_count), 0) as affected_user_sum, COUNT(DISTINCT cluster_id) as cluster_count").
		Group("source_type").
		Scan(&rows).Error; err != nil {
		return nil, err
	}

	items := make([]QualitySourceBreakdown, 0, len(rows))
	for _, row := range rows {
		items = append(items, QualitySourceBreakdown{
			SourceType:        row.SourceType,
			SignalCount:       int(row.SignalCount),
			ClusterCount:      int(row.ClusterCount),
			AffectedUserCount: int(row.AffectedUserSum),
		})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].SignalCount == items[j].SignalCount {
			return items[i].SourceType < items[j].SourceType
		}
		return items[i].SignalCount > items[j].SignalCount
	})
	return items, nil
}

func (s *QualityInsightsService) buildModuleHotspotsAgg(projectID uint) ([]QualityModuleHotspot, map[uint]string, error) {
	var clusters []model.IssueCluster
	if err := s.db.Preload("Module").
		Where("project_id = ?", projectID).
		Find(&clusters).Error; err != nil {
		return nil, nil, err
	}

	clusterAnomalies, err := s.buildClusterAnomalyLevels(projectID, clusters)
	if err != nil {
		return nil, nil, err
	}
	return buildModuleHotspots(clusters, clusterAnomalies), clusterAnomalies, nil
}

func buildAISummaryAgg(db *gorm.DB, projectID uint) QualityAISummary {
	summary := QualityAISummary{}

	type reportAgg struct {
		TotalCount   int64
		SuccessCount int64
		FailedCount  int64
	}
	var ra reportAgg
	if err := db.Table("analysis_reports").
		Joins("JOIN defects ON defects.id = analysis_reports.defect_id").
		Joins("JOIN iterations ON iterations.id = defects.iteration_id").
		Where("iterations.project_id = ?", projectID).
		Select(`COUNT(*) as total_count,
			SUM(CASE WHEN analysis_reports.status IN ('completed','completed_fallback') THEN 1 ELSE 0 END) as success_count,
			SUM(CASE WHEN analysis_reports.error_message != '' AND analysis_reports.error_message IS NOT NULL THEN 1 ELSE 0 END) as failed_count`).
		Scan(&ra).Error; err != nil {
		logger.Errorf("[QualityInsights] query reports agg: %v", err)
	}

	type taskAgg struct {
		TotalCount   int64
		SuccessCount int64
		FailedCount  int64
	}
	var ta taskAgg
	if err := db.Table("fix_tasks").
		Joins("JOIN defects ON defects.id = fix_tasks.defect_id").
		Joins("JOIN iterations ON iterations.id = defects.iteration_id").
		Where("iterations.project_id = ?", projectID).
		Select(`COUNT(*) as total_count,
			SUM(CASE WHEN fix_tasks.status = 'completed' THEN 1 ELSE 0 END) as success_count,
			SUM(CASE WHEN fix_tasks.status = 'failed' THEN 1 ELSE 0 END) as failed_count`).
		Scan(&ta).Error; err != nil {
		logger.Errorf("[QualityInsights] query fix tasks agg: %v", err)
	}

	type tokenAgg struct {
		FallbackCount int64
		DurationSum   int64
		DurationCount int64
		TokenSum      int64
		CostSum       float64
	}
	var tokens tokenAgg
	if err := db.Table("ai_token_usages").
		Where("project_id = ?", projectID).
		Select(`COUNT(CASE WHEN attempt_index > 0 AND is_final_attempt = true THEN 1 END) as fallback_count,
			COALESCE(SUM(CASE WHEN duration_ms > 0 THEN duration_ms ELSE 0 END), 0) as duration_sum,
			COALESCE(SUM(CASE WHEN duration_ms > 0 THEN 1 ELSE 0 END), 0) as duration_count,
			COALESCE(SUM(total_tokens), 0) as token_sum,
			COALESCE(SUM(estimated_cost_usd), 0) as cost_sum`).
		Scan(&tokens).Error; err != nil {
		logger.Errorf("[QualityInsights] query ai token usage agg: %v", err)
	}

	summary.AnalysisCount = int(ra.TotalCount)
	summary.FixTaskCount = int(ta.TotalCount)
	summary.SuccessfulCount = int(ra.SuccessCount + ta.SuccessCount)
	summary.FallbackCount = int(tokens.FallbackCount)
	summary.FailedCount = int(ra.FailedCount + ta.FailedCount)
	summary.TotalTokens = int(tokens.TokenSum)
	summary.EstimatedCostUSD = tokens.CostSum

	if tokens.DurationCount > 0 {
		summary.AverageDurationMs = tokens.DurationSum / tokens.DurationCount
	}
	return summary
}

func (s *QualityInsightsService) buildClusterAnomalyLevels(projectID uint, clusters []model.IssueCluster) (map[uint]string, error) {
	clusterIDs := make([]uint, 0, len(clusters))
	for _, cluster := range clusters {
		clusterIDs = append(clusterIDs, cluster.ID)
	}
	if len(clusterIDs) == 0 {
		return map[uint]string{}, nil
	}

	triageSvc := s.triageSvc
	ctx, err := triageSvc.loadClusterSignalContext(projectID, clusterIDs)
	if err != nil {
		return nil, err
	}
	releaseAnomalies, err := triageSvc.loadReleaseAnomalyLevels(projectID)
	if err != nil {
		return nil, err
	}
	return buildClusterAnomalyLevels(ctx, releaseAnomalies), nil
}

func buildIssuePoolSummary(clusters []model.IssueCluster, signals []model.IssueSignal) QualityIssuePoolSummary {
	summary := QualityIssuePoolSummary{
		TotalClusters: len(clusters),
		TotalSignals:  len(signals),
	}
	for _, cluster := range clusters {
		summary.AffectedUserCount += cluster.AffectedUserCount
		switch cluster.Status {
		case model.IssueTriageStatusConverted:
			summary.ConvertedClusters++
		case model.IssueTriageStatusIgnored, model.IssueTriageStatusClosed:
			summary.IgnoredClusters++
		default:
			summary.OpenClusters++
		}
	}
	return summary
}

func buildRegressionSummary(items []model.RegressionItem) QualityRegressionSummary {
	summary := QualityRegressionSummary{TotalItems: len(items)}
	for _, item := range items {
		switch item.Status {
		case model.RegressionItemStatusVerified:
			summary.VerifiedItems++
		case model.RegressionItemStatusArchived:
			summary.ArchivedItems++
		default:
			summary.OpenItems++
		}
	}
	return summary
}

func buildReleaseHealthSummary(items []AppReleaseTrendItem) QualityReleaseHealthSummary {
	summary := QualityReleaseHealthSummary{}
	for _, item := range items {
		switch item.AnomalyLevel {
		case "high":
			summary.HighAnomalyCount++
		case "watch":
			summary.WatchAnomalyCount++
		case "normal":
			summary.NormalCount++
		default:
			summary.BaselineCount++
		}
	}
	return summary
}

func buildAISummary(db *gorm.DB, projectID uint) QualityAISummary {
	summary := QualityAISummary{}

	var reports []model.AnalysisReport
	if err := db.Table("analysis_reports").
		Select("analysis_reports.*").
		Joins("JOIN defects ON defects.id = analysis_reports.defect_id").
		Joins("JOIN iterations ON iterations.id = defects.iteration_id").
		Where("iterations.project_id = ?", projectID).
		Find(&reports).Error; err != nil {
		logger.Errorf("[QualityInsights] query reports: %v", err)
	}

	var tasks []model.FixTask
	if err := db.Table("fix_tasks").
		Select("fix_tasks.*").
		Joins("JOIN defects ON defects.id = fix_tasks.defect_id").
		Joins("JOIN iterations ON iterations.id = defects.iteration_id").
		Where("iterations.project_id = ?", projectID).
		Find(&tasks).Error; err != nil {
		logger.Errorf("[QualityInsights] query fix tasks: %v", err)
	}

	durationTotal := int64(0)
	durationCount := int64(0)

	summary.AnalysisCount = len(reports)
	summary.FixTaskCount = len(tasks)

	for _, report := range reports {
		if report.Status == "completed" || report.Status == "completed_fallback" {
			summary.SuccessfulCount++
		}
		if report.Status == "completed_fallback" {
			summary.FallbackCount++
		}
		if strings.TrimSpace(report.ErrorMessage) != "" {
			summary.FailedCount++
		}
	}

	for _, task := range tasks {
		if task.Status == model.FixTaskStatusCompleted || task.Status == model.FixTaskStatusCompletedWithWarnings {
			summary.SuccessfulCount++
		}
		if task.Status == model.FixTaskStatusFailed {
			summary.FailedCount++
		}
	}

	var tokenUsages []model.AITokenUsage
	if err := db.Where("project_id = ?", projectID).Find(&tokenUsages).Error; err != nil {
		logger.Errorf("[QualityInsights] query ai token usages: %v", err)
	}
	for _, usage := range tokenUsages {
		if usage.AttemptIndex > 0 && usage.IsFinalAttempt {
			summary.FallbackCount++
		}
		summary.TotalTokens += usage.TotalTokens
		summary.EstimatedCostUSD += usage.EstimatedCostUSD
		if usage.DurationMs > 0 {
			durationTotal += usage.DurationMs
			durationCount++
		}
	}

	if durationCount > 0 {
		summary.AverageDurationMs = durationTotal / durationCount
	}
	return summary
}

func buildSourceBreakdowns(signals []model.IssueSignal) []QualitySourceBreakdown {
	type aggregate struct {
		signalCount       int
		affectedUserCount int
		clusterIDs        map[uint]struct{}
	}

	sourceMap := make(map[string]*aggregate)
	for _, signal := range signals {
		item := sourceMap[signal.SourceType]
		if item == nil {
			item = &aggregate{clusterIDs: make(map[uint]struct{})}
			sourceMap[signal.SourceType] = item
		}
		item.signalCount++
		item.affectedUserCount += signal.AffectedUserCount
		if signal.ClusterID != nil {
			item.clusterIDs[*signal.ClusterID] = struct{}{}
		}
	}

	items := make([]QualitySourceBreakdown, 0, len(sourceMap))
	for sourceType, item := range sourceMap {
		items = append(items, QualitySourceBreakdown{
			SourceType:        sourceType,
			SignalCount:       item.signalCount,
			ClusterCount:      len(item.clusterIDs),
			AffectedUserCount: item.affectedUserCount,
		})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].SignalCount == items[j].SignalCount {
			return items[i].SourceType < items[j].SourceType
		}
		return items[i].SignalCount > items[j].SignalCount
	})
	return items
}

func buildModuleHotspots(clusters []model.IssueCluster, clusterAnomalies map[uint]string) []QualityModuleHotspot {
	type aggregate struct {
		moduleID                *uint
		moduleName              string
		clusterCount            int
		openClusterCount        int
		convertedClusterCount   int
		affectedUserCount       int
		highAnomalyClusterCount int
	}

	moduleMap := make(map[string]*aggregate)
	for _, cluster := range clusters {
		key := "unmapped"
		moduleName := "未映射模块"
		moduleID := (*uint)(nil)
		if cluster.ModuleID != nil && cluster.Module != nil {
			key = "module:" + cluster.Module.Code
			moduleName = cluster.Module.Name
			moduleID = cluster.ModuleID
		}
		item := moduleMap[key]
		if item == nil {
			item = &aggregate{moduleID: moduleID, moduleName: moduleName}
			moduleMap[key] = item
		}
		item.clusterCount++
		item.affectedUserCount += cluster.AffectedUserCount
		switch cluster.Status {
		case model.IssueTriageStatusConverted:
			item.convertedClusterCount++
		case model.IssueTriageStatusIgnored, model.IssueTriageStatusClosed:
		default:
			item.openClusterCount++
		}
		if clusterAnomalies[cluster.ID] == "high" {
			item.highAnomalyClusterCount++
		}
	}

	items := make([]QualityModuleHotspot, 0, len(moduleMap))
	for _, item := range moduleMap {
		items = append(items, QualityModuleHotspot{
			ModuleID:                item.moduleID,
			ModuleName:              item.moduleName,
			ClusterCount:            item.clusterCount,
			OpenClusterCount:        item.openClusterCount,
			ConvertedClusterCount:   item.convertedClusterCount,
			AffectedUserCount:       item.affectedUserCount,
			HighAnomalyClusterCount: item.highAnomalyClusterCount,
		})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].ClusterCount == items[j].ClusterCount {
			if items[i].AffectedUserCount == items[j].AffectedUserCount {
				return items[i].ModuleName < items[j].ModuleName
			}
			return items[i].AffectedUserCount > items[j].AffectedUserCount
		}
		return items[i].ClusterCount > items[j].ClusterCount
	})
	return items
}

func buildTopReleaseAnomalies(items []AppReleaseTrendItem) []AppReleaseTrendItem {
	filtered := make([]AppReleaseTrendItem, 0, len(items))
	for _, item := range items {
		if item.AnomalyLevel == "watch" || item.AnomalyLevel == "high" {
			filtered = append(filtered, item)
		}
	}
	sort.Slice(filtered, func(i, j int) bool {
		levelDiff := compareAnomalyLevel(filtered[i].AnomalyLevel, filtered[j].AnomalyLevel)
		if levelDiff != 0 {
			return levelDiff > 0
		}
		if filtered[i].AffectedUserCount == filtered[j].AffectedUserCount {
			return filtered[i].Release.ReleaseTime.After(filtered[j].Release.ReleaseTime)
		}
		return filtered[i].AffectedUserCount > filtered[j].AffectedUserCount
	})
	if len(filtered) > 5 {
		filtered = filtered[:5]
	}
	return filtered
}
