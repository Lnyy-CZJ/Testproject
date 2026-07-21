package service

import (
	"bug-agent/pkg/logger"
	"bug-agent/internal/model"
	"bug-agent/internal/util"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"
)

const signalStaleThreshold = 14 * 24 * time.Hour

var ErrIssueClusterNotFound = errors.New("issue cluster not found")

type SignalTriageService struct {
	db *gorm.DB
}

type IssueClusterListParams struct {
	Status       string
	Query        string
	Platform     string
	AppVersion   string
	ReleaseID    uint
	AnomalyLevel string
	Page         int
	PageSize     int
}

type IssueClusterListItem struct {
	model.IssueCluster
	Platform           string   `json:"platform,omitempty"`
	AppVersion         string   `json:"appVersion,omitempty"`
	BuildNumber        string   `json:"buildNumber,omitempty"`
	PrimarySourceType  string   `json:"primarySourceType,omitempty"`
	ReleaseMatchCount  int      `json:"releaseMatchCount"`
	AnomalyLevel       string   `json:"anomalyLevel,omitempty"`
	RoutingConfidence  float64  `json:"routingConfidence,omitempty"`
	RoutingEvidence    []string `json:"routingEvidence,omitempty"`
	RoutingRuleID      *uint    `json:"routingRuleId,omitempty"`
	SuggestedOwnerID   *uint    `json:"suggestedOwnerId,omitempty"`
	SuggestedModuleID  *uint    `json:"suggestedModuleId,omitempty"`
}

type IssuePoolReleaseSummaryItem struct {
	Release           model.AppRelease `json:"release"`
	ClusterCount      int              `json:"clusterCount"`
	SignalCount       int              `json:"signalCount"`
	AffectedUserCount int              `json:"affectedUserCount"`
	LastSeenAt        time.Time        `json:"lastSeenAt"`
}

type clusterSignalContext struct {
	latestSignals  map[uint]model.IssueSignal
	clusterSignals map[uint][]model.IssueSignal
	releaseMap     map[releaseLookupKey][]model.AppRelease
}

func NewSignalTriageService(db *gorm.DB) *SignalTriageService {
	return &SignalTriageService{db: db}
}

func (s *SignalTriageService) preloadClusterRelations(query *gorm.DB) *gorm.DB {
	return query.
		Preload("Owner").
		Preload("Defect").
		Preload("Defect.Assignee").
		Preload("Defect.Reporter")
}

func (s *SignalTriageService) ListClusters(projectID uint, params IssueClusterListParams) ([]IssueClusterListItem, int64, error) {
	if params.Page < 1 {
		params.Page = 1
	}
	if params.PageSize < 1 || params.PageSize > 100 {
		params.PageSize = 20
	}

	query := s.buildBaseClusterQuery(projectID, params)
	if params.ReleaseID > 0 || strings.TrimSpace(params.AnomalyLevel) != "" {
		filteredClusterIDs, err := s.listFilteredClusterIDs(projectID, IssueClusterListParams{
			Status:       params.Status,
			Query:        params.Query,
			Platform:     params.Platform,
			AppVersion:   params.AppVersion,
			ReleaseID:    params.ReleaseID,
			AnomalyLevel: params.AnomalyLevel,
		})
		if err != nil {
			return nil, 0, err
		}
		total := int64(len(filteredClusterIDs))
		if total == 0 {
			return []IssueClusterListItem{}, 0, nil
		}

		var clusters []model.IssueCluster
		if err := s.preloadClusterRelations(s.db.Model(&model.IssueCluster{})).
			Where("project_id = ? AND id IN ?", projectID, filteredClusterIDs).
			Order("last_seen_at desc, id desc").
			Offset((params.Page - 1) * params.PageSize).
			Limit(params.PageSize).
			Find(&clusters).Error; err != nil {
			return nil, 0, err
		}
		items, err := s.enrichClusterListItems(projectID, clusters)
		if err != nil {
			return nil, 0, err
		}
		return items, total, nil
	}

	var total int64
	if err := query.Count(&total).Error; err != nil {
		return nil, 0, err
	}

	var clusters []model.IssueCluster
	if err := s.preloadClusterRelations(query).
		Order("last_seen_at desc, id desc").
		Offset((params.Page - 1) * params.PageSize).
		Limit(params.PageSize).
		Find(&clusters).Error; err != nil {
		return nil, 0, err
	}
	items, err := s.enrichClusterListItems(projectID, clusters)
	if err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

func (s *SignalTriageService) GetCluster(projectID, clusterID uint) (*model.IssueCluster, error) {
	var cluster model.IssueCluster
	if err := s.preloadClusterRelations(s.db).Where("project_id = ? AND id = ?", projectID, clusterID).First(&cluster).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrIssueClusterNotFound
		}
		return nil, err
	}
	return &cluster, nil
}

func (s *SignalTriageService) ListSignals(projectID, clusterID uint) ([]model.IssueSignal, error) {
	if _, err := s.GetCluster(projectID, clusterID); err != nil {
		return nil, err
	}

	var signals []model.IssueSignal
	if err := s.db.Where("project_id = ? AND cluster_id = ?", projectID, clusterID).
		Order("last_seen_at desc, id desc").
		Find(&signals).Error; err != nil {
		return nil, err
	}
	return signals, nil
}

func (s *SignalTriageService) AssignCluster(projectID, clusterID, ownerUserID, operatorID uint) (*model.IssueCluster, error) {
	cluster, err := s.GetCluster(projectID, clusterID)
	if err != nil {
		return nil, err
	}

	suggestion := s.explainRoutingSuggestion(projectID, clusterID)

	before := cloneIssueCluster(*cluster)
	cluster.OwnerUserID = &ownerUserID
	if cluster.Status == model.IssueTriageStatusNew {
		cluster.Status = model.IssueTriageStatusTriaging
	}

	if err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Save(cluster).Error; err != nil {
			return err
		}
		if err := s.createTriageRecord(tx, nil, cluster, "assign", operatorID, before, *cluster, ""); err != nil {
			return err
		}

		if suggestion != nil {
			accepted := suggestion.SuggestedOwnerID != nil && *suggestion.SuggestedOwnerID == ownerUserID
			evidenceJSON, _ := json.Marshal(suggestion.RoutingEvidence)
			fb := model.RoutingSuggestionFeedback{
				ClusterID:       clusterID,
				RoutingRuleID:   suggestion.RoutingRuleID,
				SuggestedOwner:  suggestion.SuggestedOwnerID,
				SuggestedModule: suggestion.SuggestedModuleID,
				Confidence:      suggestion.RoutingConfidence,
				EvidenceJSON:    string(evidenceJSON),
				Accepted:        accepted,
				ActualOwner:     &ownerUserID,
				OperatorID:      operatorID,
			}
			if err := tx.Create(&fb).Error; err != nil {
				logger.Errorf("Create failed: %v", err)
			}
		}

		return nil
	}); err != nil {
		return nil, err
	}
	return cluster, nil
}

func (s *SignalTriageService) IgnoreCluster(projectID, clusterID, operatorID uint, reason string) (*model.IssueCluster, error) {
	cluster, err := s.GetCluster(projectID, clusterID)
	if err != nil {
		return nil, err
	}

	before := cloneIssueCluster(*cluster)
	cluster.Status = model.IssueTriageStatusIgnored

	if err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Save(cluster).Error; err != nil {
			return err
		}
		if err := tx.Model(&model.IssueSignal{}).
			Where("project_id = ? AND cluster_id = ?", projectID, clusterID).
			Update("triage_status", model.IssueTriageStatusIgnored).Error; err != nil {
			return err
		}
		return s.createTriageRecord(tx, nil, cluster, "ignore", operatorID, before, *cluster, strings.TrimSpace(reason))
	}); err != nil {
		return nil, err
	}
	return cluster, nil
}

func (s *SignalTriageService) MergeCluster(projectID, sourceClusterID, targetClusterID, operatorID uint, reason string) (*model.IssueCluster, *model.IssueCluster, error) {
	if sourceClusterID == targetClusterID {
		return nil, nil, ErrIssueClusterNotFound
	}
	source, err := s.GetCluster(projectID, sourceClusterID)
	if err != nil {
		return nil, nil, err
	}
	target, err := s.GetCluster(projectID, targetClusterID)
	if err != nil {
		return nil, nil, err
	}

	before := cloneIssueCluster(*source)
	err = s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Model(&model.IssueSignal{}).
			Where("project_id = ? AND cluster_id = ?", projectID, sourceClusterID).
			Updates(map[string]interface{}{
				"cluster_id":    targetClusterID,
				"triage_status": model.IssueTriageStatusClustered,
				"updated_at":    time.Now(),
			}).Error; err != nil {
			return err
		}

		source.Status = model.IssueTriageStatusClustered
		source.SignalCount = 0
		source.AffectedUserCount = 0
		if err := tx.Save(source).Error; err != nil {
			return err
		}

		if err := s.refreshClusterMetrics(tx, target); err != nil {
			return err
		}

		return s.createTriageRecord(tx, nil, source, "merge", operatorID, before, *source, strings.TrimSpace(reason))
	})
	if err != nil {
		return nil, nil, err
	}
	return source, target, nil
}

func (s *SignalTriageService) ConvertCluster(projectID, clusterID, operatorID uint) (*model.IssueCluster, *model.Defect, error) {
	cluster, err := s.GetCluster(projectID, clusterID)
	if err != nil {
		return nil, nil, err
	}
	if cluster.LinkedDefectID != nil {
		var defect model.Defect
		if err := s.db.First(&defect, *cluster.LinkedDefectID).Error; err == nil {
			return cluster, &defect, nil
		} else {
			logger.Warnf("关联缺陷 #%d 已被删除，清除旧关联: %v", *cluster.LinkedDefectID, err)
			s.db.Model(&model.IssueCluster{}).Where("id = ?", clusterID).Update("linked_defect_id", nil)
			cluster.LinkedDefectID = nil
		}
	}

	signals, err := s.ListSignals(projectID, clusterID)
	if err != nil {
		return nil, nil, err
	}

	iteration, err := s.ensureIteration(projectID)
	if err != nil {
		return nil, nil, err
	}

	var defect model.Defect
	before := cloneIssueCluster(*cluster)
	err = s.db.Transaction(func(tx *gorm.DB) error {
		var lockedCluster model.IssueCluster
		if err := tx.Set("gorm:query_option", "FOR UPDATE").First(&lockedCluster, clusterID).Error; err != nil {
			return err
		}
		if lockedCluster.LinkedDefectID != nil {
			return fmt.Errorf("问题簇已关联缺陷 #%d，不可重复转换", *lockedCluster.LinkedDefectID)
		}

		project := model.Project{}
		if err := tx.First(&project, projectID).Error; err != nil {
			return err
		}

		defectCode, err := model.GenerateDefectCode(tx, &project)
		if err != nil {
			return err
		}
		defect = model.Defect{
			Code:        defectCode,
			IterationID: iteration.ID,
			Title:       cluster.Title,
			Description: s.buildDefectDescription(*cluster, signals),
			Severity:    util.DefaultString(cluster.Severity, model.SeverityNormal),
		Priority:    util.DefaultString(cluster.Priority, model.PriorityP2),
			Type:        model.DefectTypeFunctional,
			Status:      model.DefectStatusPendingAssign,
			ReporterID:  operatorID,
			Tags:        "issue-pool",
		}
		if cluster.OwnerUserID != nil {
			defect.AssigneeID = cluster.OwnerUserID
		}
		if err := tx.Create(&defect).Error; err != nil {
			return err
		}

		comment := model.Comment{
			DefectID: defect.ID,
			UserID:   operatorID,
			Content: sanitizeCommentContent(fmt.Sprintf(
				"🛰️ 该缺陷由问题池转入。\n问题簇 #%d\n历史信号数: %d\n影响用户数: %d",
				cluster.ID,
				cluster.SignalCount,
				cluster.AffectedUserCount,
			)),
		}
		if err := tx.Create(&comment).Error; err != nil {
			return err
		}

		cluster.LinkedDefectID = &defect.ID
		cluster.Status = model.IssueTriageStatusConverted
		if err := tx.Save(cluster).Error; err != nil {
			return err
		}

		if err := tx.Model(&model.IssueSignal{}).
			Where("project_id = ? AND cluster_id = ?", projectID, clusterID).
			Updates(map[string]interface{}{
				"linked_defect_id": defect.ID,
				"triage_status":    model.IssueTriageStatusConverted,
			}).Error; err != nil {
			return err
		}

		return s.createTriageRecord(tx, nil, cluster, "convert", operatorID, before, *cluster, "")
	})
	if err != nil {
		return nil, nil, err
	}
	return cluster, &defect, nil
}

func (s *SignalTriageService) BatchAssignClusters(projectID uint, clusterIDs []uint, ownerUserID, operatorID uint) (int, error) {
	count := 0
	for _, clusterID := range clusterIDs {
		if _, err := s.AssignCluster(projectID, clusterID, ownerUserID, operatorID); err != nil {
			return count, err
		}
		count++
	}
	return count, nil
}

func (s *SignalTriageService) BatchIgnoreClusters(projectID uint, clusterIDs []uint, operatorID uint, reason string) (int, error) {
	count := 0
	for _, clusterID := range clusterIDs {
		if _, err := s.IgnoreCluster(projectID, clusterID, operatorID, reason); err != nil {
			return count, err
		}
		count++
	}
	return count, nil
}

func (s *SignalTriageService) BatchConvertClusters(projectID uint, clusterIDs []uint, operatorID uint) (int, []uint, error) {
	count := 0
	defectIDs := make([]uint, 0, len(clusterIDs))
	for _, clusterID := range clusterIDs {
		_, defect, err := s.ConvertCluster(projectID, clusterID, operatorID)
		if err != nil {
			return count, defectIDs, err
		}
		if defect != nil {
			defectIDs = append(defectIDs, defect.ID)
		}
		count++
	}
	return count, defectIDs, nil
}

func (s *SignalTriageService) ensureIteration(projectID uint) (*model.Iteration, error) {
	var iteration model.Iteration
	err := s.db.Where("project_id = ? AND status = ?", projectID, "active").Order("id desc").First(&iteration).Error
	switch {
	case err == nil:
		return &iteration, nil
	case !errors.Is(err, gorm.ErrRecordNotFound):
		return nil, err
	}

	err = s.db.Where("project_id = ?", projectID).Order("id desc").First(&iteration).Error
	switch {
	case err == nil:
		return &iteration, nil
	case !errors.Is(err, gorm.ErrRecordNotFound):
		return nil, err
	}

	now := time.Now()
	iteration = model.Iteration{
		ProjectID: projectID,
		Name:      "问题池默认迭代",
		Status:    "active",
		StartDate: now,
		EndDate:   now.Add(signalStaleThreshold),
	}
	if err := s.db.Create(&iteration).Error; err != nil {
		return nil, err
	}
	return &iteration, nil
}

func (s *SignalTriageService) createTriageRecord(tx *gorm.DB, signal *model.IssueSignal, cluster *model.IssueCluster, action string, operatorID uint, before, after model.IssueCluster, reason string) error {
	beforeJSON, err := json.Marshal(before)
	if err != nil {
		logger.Errorf("[SignalTriage] marshal before state failed: %v", err)
	}
	afterJSON, err := json.Marshal(after)
	if err != nil {
		logger.Errorf("[SignalTriage] marshal after state failed: %v", err)
	}

	record := model.IssueTriageRecord{
		Action:     action,
		OperatorID: operatorID,
		BeforeJSON: string(beforeJSON),
		AfterJSON:  string(afterJSON),
		Reason:     reason,
	}
	if signal != nil && signal.ID > 0 {
		record.SignalID = &signal.ID
	}
	if cluster != nil && cluster.ID > 0 {
		record.ClusterID = &cluster.ID
	}
	return tx.Create(&record).Error
}

func (s *SignalTriageService) refreshClusterMetrics(tx *gorm.DB, cluster *model.IssueCluster) error {
	var signalCount int64
	if err := tx.Model(&model.IssueSignal{}).Where("cluster_id = ?", cluster.ID).Count(&signalCount).Error; err != nil {
		return err
	}
	cluster.SignalCount = int(signalCount)
	if signalCount == 0 {
		return tx.Save(cluster).Error
	}

	var affectedUserCount int64
	if err := tx.Model(&model.IssueSignal{}).
		Where("cluster_id = ?", cluster.ID).
		Select("COALESCE(SUM(affected_user_count), 0)").
		Scan(&affectedUserCount).Error; err != nil {
		return err
	}

	var firstSignal model.IssueSignal
	if err := tx.Where("cluster_id = ?", cluster.ID).Order("first_seen_at asc, id asc").First(&firstSignal).Error; err != nil {
		return err
	}
	var lastSignal model.IssueSignal
	if err := tx.Where("cluster_id = ?", cluster.ID).Order("last_seen_at desc, id desc").First(&lastSignal).Error; err != nil {
		return err
	}

	cluster.AffectedUserCount = int(affectedUserCount)
	cluster.FirstSeenAt = firstSignal.FirstSeenAt
	cluster.LastSeenAt = lastSignal.LastSeenAt
	if strings.TrimSpace(cluster.Severity) == "" {
		cluster.Severity = lastSignal.RawSeverity
	}
	if strings.TrimSpace(cluster.Priority) == "" {
		cluster.Priority = lastSignal.RawPriority
	}
	if strings.TrimSpace(cluster.Title) == "" {
		cluster.Title = lastSignal.Title
	}
	if strings.TrimSpace(cluster.Summary) == "" {
		cluster.Summary = lastSignal.Description
	}
	return tx.Save(cluster).Error
}

func (s *SignalTriageService) buildDefectDescription(cluster model.IssueCluster, signals []model.IssueSignal) string {
	var builder strings.Builder
	builder.WriteString("来源: 问题池\n")
	builder.WriteString(fmt.Sprintf("问题簇ID: %d\n", cluster.ID))
	builder.WriteString(fmt.Sprintf("历史信号数: %d\n", cluster.SignalCount))
	builder.WriteString(fmt.Sprintf("影响用户数: %d\n", cluster.AffectedUserCount))
	if cluster.Summary != "" {
		builder.WriteString("\n摘要:\n")
		builder.WriteString(cluster.Summary)
		builder.WriteString("\n")
	}
	if len(signals) > 0 {
		first := signals[0]
		builder.WriteString("\n首条信号:\n")
		builder.WriteString(fmt.Sprintf("事件ID: %s\n", first.SourceEventID))
		if first.Platform != "" {
			builder.WriteString(fmt.Sprintf("平台: %s\n", first.Platform))
		}
		if first.AppVersion != "" {
			builder.WriteString(fmt.Sprintf("版本: %s\n", first.AppVersion))
		}
		if first.StackTrace != "" {
			builder.WriteString("堆栈:\n")
			builder.WriteString(first.StackTrace)
			builder.WriteString("\n")
		}
	}
	return sanitizeCommentContent(strings.TrimSpace(builder.String()))
}

func cloneIssueCluster(cluster model.IssueCluster) model.IssueCluster {
	cloned := cluster
	if cluster.OwnerUserID != nil {
		v := *cluster.OwnerUserID
		cloned.OwnerUserID = &v
	}
	if cluster.LinkedDefectID != nil {
		v := *cluster.LinkedDefectID
		cloned.LinkedDefectID = &v
	}
	if cluster.ModuleID != nil {
		v := *cluster.ModuleID
		cloned.ModuleID = &v
	}
	return cloned
}

func (s *SignalTriageService) ListReleaseSummaries(projectID uint, params IssueClusterListParams) ([]IssuePoolReleaseSummaryItem, error) {
	clusterIDs, err := s.listFilteredClusterIDs(projectID, params)
	if err != nil {
		return nil, err
	}
	if len(clusterIDs) == 0 {
		return []IssuePoolReleaseSummaryItem{}, nil
	}

	ctx, err := s.loadClusterSignalContext(projectID, clusterIDs)
	if err != nil {
		return nil, err
	}

	aggregated := make(map[uint]*IssuePoolReleaseSummaryItem)
	for _, signals := range ctx.clusterSignals {
		clusterReleases := make(map[uint]struct{})
		for _, signal := range signals {
			release, _, ok := matchSignalToRelease(signal, ctx.releaseMap)
			if !ok {
				continue
			}
			item, exists := aggregated[release.ID]
			if !exists {
				item = &IssuePoolReleaseSummaryItem{
					Release:           release,
					ClusterCount:      0,
					SignalCount:       0,
					AffectedUserCount: 0,
					LastSeenAt:        signal.LastSeenAt,
				}
				aggregated[release.ID] = item
			}
			item.SignalCount++
			item.AffectedUserCount += signal.AffectedUserCount
			if signal.LastSeenAt.After(item.LastSeenAt) {
				item.LastSeenAt = signal.LastSeenAt
			}
			if _, seen := clusterReleases[release.ID]; !seen {
				clusterReleases[release.ID] = struct{}{}
				item.ClusterCount++
			}
		}
	}

	items := make([]IssuePoolReleaseSummaryItem, 0, len(aggregated))
	for _, item := range aggregated {
		items = append(items, *item)
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].AffectedUserCount == items[j].AffectedUserCount {
			if items[i].SignalCount == items[j].SignalCount {
				return items[i].LastSeenAt.After(items[j].LastSeenAt)
			}
			return items[i].SignalCount > items[j].SignalCount
		}
		return items[i].AffectedUserCount > items[j].AffectedUserCount
	})
	return items, nil
}

func (s *SignalTriageService) buildBaseClusterQuery(projectID uint, params IssueClusterListParams) *gorm.DB {
	query := s.db.Model(&model.IssueCluster{}).Where("project_id = ?", projectID)
	status := strings.TrimSpace(params.Status)
	if status != "" {
		query = query.Where("status = ?", status)
	}
	if q := strings.TrimSpace(params.Query); q != "" {
		like := "%" + escapeLike(q) + "%"
		query = query.Where("title LIKE ? OR summary LIKE ?", like, like)
	}
	if platform := strings.ToLower(strings.TrimSpace(params.Platform)); platform != "" {
		subQuery := s.db.Model(&model.IssueSignal{}).
			Select("DISTINCT cluster_id").
			Where("project_id = ? AND cluster_id IS NOT NULL AND LOWER(platform) = ?", projectID, platform)
		if appVersion := strings.ToLower(strings.TrimSpace(params.AppVersion)); appVersion != "" {
			subQuery = subQuery.Where("LOWER(app_version) LIKE ?", "%"+escapeLike(appVersion)+"%")
		}
		query = query.Where("id IN (?)", subQuery)
	} else if appVersion := strings.ToLower(strings.TrimSpace(params.AppVersion)); appVersion != "" {
		subQuery := s.db.Model(&model.IssueSignal{}).
			Select("DISTINCT cluster_id").
			Where("project_id = ? AND cluster_id IS NOT NULL AND LOWER(app_version) LIKE ?", projectID, "%"+escapeLike(appVersion)+"%")
		query = query.Where("id IN (?)", subQuery)
	}
	return query
}

func (s *SignalTriageService) listClusterIDs(query *gorm.DB) ([]uint, error) {
	var clusterIDs []uint
	if err := query.Pluck("id", &clusterIDs).Error; err != nil {
		return nil, err
	}
	return clusterIDs, nil
}

func (s *SignalTriageService) listFilteredClusterIDs(projectID uint, params IssueClusterListParams) ([]uint, error) {
	clusterIDs, err := s.listClusterIDs(s.buildBaseClusterQuery(projectID, params))
	if err != nil {
		return nil, err
	}
	if len(clusterIDs) == 0 {
		return clusterIDs, nil
	}
	if params.ReleaseID > 0 {
		clusterIDs, err = s.filterClusterIDsByRelease(projectID, clusterIDs, params.ReleaseID)
		if err != nil {
			return nil, err
		}
	}
	if len(clusterIDs) == 0 || strings.TrimSpace(params.AnomalyLevel) == "" {
		return clusterIDs, nil
	}
	return s.filterClusterIDsByAnomaly(projectID, clusterIDs, params.AnomalyLevel)
}

func (s *SignalTriageService) filterClusterIDsByRelease(projectID uint, clusterIDs []uint, releaseID uint) ([]uint, error) {
	if len(clusterIDs) == 0 {
		return []uint{}, nil
	}

	var release model.AppRelease
	if err := s.db.Where("project_id = ? AND id = ?", projectID, releaseID).First(&release).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return []uint{}, nil
		}
		return nil, err
	}

	var candidates []model.AppRelease
	if err := s.db.
		Where("project_id = ? AND LOWER(platform) = ? AND LOWER(app_version) = ?", projectID, normalizeReleaseToken(release.Platform), normalizeReleaseToken(release.AppVersion)).
		Order("release_time desc, id desc").
		Find(&candidates).Error; err != nil {
		return nil, err
	}
	releaseMap := map[releaseLookupKey][]model.AppRelease{
		{
			platform:   normalizeReleaseToken(release.Platform),
			appVersion: normalizeReleaseToken(release.AppVersion),
		}: candidates,
	}

	var signals []model.IssueSignal
	if err := s.db.
		Where("project_id = ? AND cluster_id IN ? AND LOWER(platform) = ? AND LOWER(app_version) = ?", projectID, clusterIDs, normalizeReleaseToken(release.Platform), normalizeReleaseToken(release.AppVersion)).
		Find(&signals).Error; err != nil {
		return nil, err
	}

	filteredSet := make(map[uint]struct{})
	for _, signal := range signals {
		if signal.ClusterID == nil {
			continue
		}
		matchedRelease, _, ok := matchSignalToRelease(signal, releaseMap)
		if ok && matchedRelease.ID == release.ID {
			filteredSet[*signal.ClusterID] = struct{}{}
		}
	}

	filteredIDs := make([]uint, 0, len(filteredSet))
	for _, clusterID := range clusterIDs {
		if _, ok := filteredSet[clusterID]; ok {
			filteredIDs = append(filteredIDs, clusterID)
		}
	}
	return filteredIDs, nil
}

func (s *SignalTriageService) loadClusterSignalContext(projectID uint, clusterIDs []uint) (*clusterSignalContext, error) {
	ctx := &clusterSignalContext{
		latestSignals:  make(map[uint]model.IssueSignal),
		clusterSignals: make(map[uint][]model.IssueSignal),
		releaseMap:     make(map[releaseLookupKey][]model.AppRelease),
	}
	if len(clusterIDs) == 0 {
		return ctx, nil
	}

	var signals []model.IssueSignal
	if err := s.db.
		Where("project_id = ? AND cluster_id IN ?", projectID, clusterIDs).
		Order("cluster_id asc, last_seen_at desc, id desc").
		Find(&signals).Error; err != nil {
		return nil, err
	}

	releaseKeys := make(map[releaseLookupKey]struct{})
	platforms := make(map[string]struct{})
	appVersions := make(map[string]struct{})

	for _, signal := range signals {
		if signal.ClusterID == nil {
			continue
		}
		clusterID := *signal.ClusterID
		if _, exists := ctx.latestSignals[clusterID]; !exists {
			ctx.latestSignals[clusterID] = signal
		}
		ctx.clusterSignals[clusterID] = append(ctx.clusterSignals[clusterID], signal)

		platform := normalizeReleaseToken(signal.Platform)
		appVersion := normalizeReleaseToken(signal.AppVersion)
		if platform == "" || appVersion == "" {
			continue
		}
		key := releaseLookupKey{platform: platform, appVersion: appVersion}
		releaseKeys[key] = struct{}{}
		platforms[platform] = struct{}{}
		appVersions[appVersion] = struct{}{}
	}

	if len(releaseKeys) == 0 {
		return ctx, nil
	}

	var releases []model.AppRelease
	if err := s.db.
		Where("project_id = ? AND LOWER(platform) IN ? AND LOWER(app_version) IN ?", projectID, mapKeys(platforms), mapKeys(appVersions)).
		Order("release_time desc, id desc").
		Find(&releases).Error; err != nil {
		return nil, err
	}
	for _, release := range releases {
		key := releaseLookupKey{
			platform:   normalizeReleaseToken(release.Platform),
			appVersion: normalizeReleaseToken(release.AppVersion),
		}
		if _, ok := releaseKeys[key]; !ok {
			continue
		}
		ctx.releaseMap[key] = append(ctx.releaseMap[key], release)
	}
	return ctx, nil
}

func (s *SignalTriageService) enrichClusterListItems(projectID uint, clusters []model.IssueCluster) ([]IssueClusterListItem, error) {
	if len(clusters) == 0 {
		return []IssueClusterListItem{}, nil
	}

	clusterIDs := make([]uint, 0, len(clusters))
	for _, cluster := range clusters {
		clusterIDs = append(clusterIDs, cluster.ID)
	}
	ctx, err := s.loadClusterSignalContext(projectID, clusterIDs)
	if err != nil {
		return nil, err
	}
	releaseAnomalies, err := s.loadReleaseAnomalyLevels(projectID)
	if err != nil {
		return nil, err
	}
	clusterAnomalies := buildClusterAnomalyLevels(ctx, releaseAnomalies)
	rules, err := s.loadRoutingRules(projectID)
	if err != nil {
		return nil, err
	}
	moduleNames, err := s.loadModuleNames(projectID, rules)
	if err != nil {
		return nil, err
	}

	items := make([]IssueClusterListItem, 0, len(clusters))
	for _, cluster := range clusters {
		item := IssueClusterListItem{
			IssueCluster:      cluster,
			ReleaseMatchCount: 0,
		}
		if signal, ok := ctx.latestSignals[cluster.ID]; ok {
			item.Platform = signal.Platform
			item.AppVersion = signal.AppVersion
			item.BuildNumber = signal.BuildNumber
			item.PrimarySourceType = signal.SourceType
			item.RoutingConfidence, item.RoutingEvidence, item.RoutingRuleID = explainRoutingSuggestion(signal, rules, moduleNames)
		}

		releaseIDs := make(map[uint]struct{})
		for _, signal := range ctx.clusterSignals[cluster.ID] {
			release, _, ok := matchSignalToRelease(signal, ctx.releaseMap)
			if !ok {
				continue
			}
			releaseIDs[release.ID] = struct{}{}
		}
		item.ReleaseMatchCount = len(releaseIDs)
		item.AnomalyLevel = clusterAnomalies[cluster.ID]
		items = append(items, item)
	}
	return items, nil
}

func (s *SignalTriageService) loadRoutingRules(projectID uint) ([]model.IssueRoutingRule, error) {
	var rules []model.IssueRoutingRule
	if err := s.db.Where("project_id = ? AND enabled = ?", projectID, true).
		Order("sort_order asc, id asc").
		Find(&rules).Error; err != nil {
		return nil, err
	}
	return rules, nil
}

func (s *SignalTriageService) loadModuleNames(projectID uint, rules []model.IssueRoutingRule) (map[uint]string, error) {
	moduleIDs := make([]uint, 0)
	seen := make(map[uint]struct{})
	for _, rule := range rules {
		if rule.ModuleID == nil {
			continue
		}
		if _, ok := seen[*rule.ModuleID]; ok {
			continue
		}
		seen[*rule.ModuleID] = struct{}{}
		moduleIDs = append(moduleIDs, *rule.ModuleID)
	}
	if len(moduleIDs) == 0 {
		return map[uint]string{}, nil
	}
	var modules []model.ProjectModule
	if err := s.db.Where("project_id = ? AND id IN ?", projectID, moduleIDs).Find(&modules).Error; err != nil {
		return nil, err
	}
	result := make(map[uint]string, len(modules))
	for _, module := range modules {
		result[module.ID] = module.Name
	}
	return result, nil
}

func explainRoutingSuggestion(signal model.IssueSignal, rules []model.IssueRoutingRule, moduleNames map[uint]string) (float64, []string, *uint) {
	for _, rule := range rules {
		if !matchesRoutingRule(rule, &signal) {
			continue
		}
		confidence := routingConfidenceForMatchType(rule.MatchType)
		reasons := []string{fmt.Sprintf("命中规则：%s = %s", rule.MatchType, strings.TrimSpace(rule.MatchValue))}
		if rule.ModuleID != nil {
			moduleName := moduleNames[*rule.ModuleID]
			if strings.TrimSpace(moduleName) == "" {
				moduleName = fmt.Sprintf("模块 #%d", *rule.ModuleID)
			}
			reasons = append(reasons, "建议模块："+moduleName)
			confidence += 0.02
		}
		if rule.OwnerUserID != nil {
			reasons = append(reasons, fmt.Sprintf("建议负责人：用户 #%d", *rule.OwnerUserID))
			confidence += 0.02
		}
		if strings.TrimSpace(rule.PriorityOverride) != "" {
			reasons = append(reasons, "建议优先级："+strings.TrimSpace(rule.PriorityOverride))
			confidence += 0.01
		}
		if strings.TrimSpace(rule.SeverityOverride) != "" {
			reasons = append(reasons, "建议严重级别："+strings.TrimSpace(rule.SeverityOverride))
			confidence += 0.01
		}
		if confidence > 0.99 {
			confidence = 0.99
		}
		ruleID := rule.ID
		return confidence, reasons, &ruleID
	}
	return 0, []string{"未命中路由规则，等待人工分诊"}, nil
}

func routingConfidenceForMatchType(matchType string) float64 {
	switch strings.TrimSpace(matchType) {
	case "fingerprint_pattern", "stack_keyword":
		return 0.95
	case "source_type":
		return 0.86
	case "app_version":
		return 0.8
	case "platform":
		return 0.72
	default:
		return 0.6
	}
}

func (s *SignalTriageService) filterClusterIDsByAnomaly(projectID uint, clusterIDs []uint, anomalyLevel string) ([]uint, error) {
	if len(clusterIDs) == 0 {
		return []uint{}, nil
	}

	ctx, err := s.loadClusterSignalContext(projectID, clusterIDs)
	if err != nil {
		return nil, err
	}
	releaseAnomalies, err := s.loadReleaseAnomalyLevels(projectID)
	if err != nil {
		return nil, err
	}
	clusterAnomalies := buildClusterAnomalyLevels(ctx, releaseAnomalies)

	level := strings.ToLower(strings.TrimSpace(anomalyLevel))
	filteredIDs := make([]uint, 0, len(clusterIDs))
	for _, clusterID := range clusterIDs {
		if clusterAnomalies[clusterID] == level {
			filteredIDs = append(filteredIDs, clusterID)
		}
	}
	return filteredIDs, nil
}

func (s *SignalTriageService) loadReleaseAnomalyLevels(projectID uint) (map[uint]string, error) {
	routingSvc := NewProjectRoutingService(s.db)
	trends, err := routingSvc.ListReleaseTrends(projectID)
	if err != nil {
		return nil, err
	}

	releaseAnomalies := make(map[uint]string, len(trends))
	for _, trend := range trends {
		releaseAnomalies[trend.Release.ID] = trend.AnomalyLevel
	}
	return releaseAnomalies, nil
}

func buildClusterAnomalyLevels(ctx *clusterSignalContext, releaseAnomalies map[uint]string) map[uint]string {
	clusterAnomalies := make(map[uint]string, len(ctx.clusterSignals))
	for clusterID, signals := range ctx.clusterSignals {
		currentLevel := ""
		for _, signal := range signals {
			release, _, ok := matchSignalToRelease(signal, ctx.releaseMap)
			if !ok {
				continue
			}
			level := releaseAnomalies[release.ID]
			if compareAnomalyLevel(level, currentLevel) > 0 {
				currentLevel = level
			}
		}
		if currentLevel != "" {
			clusterAnomalies[clusterID] = currentLevel
		}
	}
	return clusterAnomalies
}

func compareAnomalyLevel(left, right string) int {
	weights := map[string]int{
		"":         -1,
		"baseline": 0,
		"normal":   1,
		"watch":    2,
		"high":     3,
	}
	return weights[strings.ToLower(strings.TrimSpace(left))] - weights[strings.ToLower(strings.TrimSpace(right))]
}

func (s *SignalTriageService) explainRoutingSuggestion(projectID, clusterID uint) *IssueClusterListItem {
	var signals []model.IssueSignal
	if err := s.db.Where("project_id = ? AND cluster_id = ?", projectID, clusterID).
		Order("last_seen_at DESC").Limit(1).Find(&signals).Error; err != nil {
		logger.Errorf("查询信号失败: %v", err)
	}
	if len(signals) == 0 {
		return nil
	}

	var rules []model.IssueRoutingRule
	if err := s.db.Where("project_id = ? AND enabled = ?", projectID, true).Order("sort_order ASC").Find(&rules).Error; err != nil {
		logger.Errorf("查询路由规则失败: %v", err)
	}
	if len(rules) == 0 {
		return nil
	}

	moduleNames, _ := s.loadModuleNames(projectID, rules)
	confidence, evidence, ruleID := explainRoutingSuggestion(signals[0], rules, moduleNames)
	if ruleID == nil {
		return nil
	}

	item := &IssueClusterListItem{
		RoutingConfidence: confidence,
		RoutingEvidence:   evidence,
		RoutingRuleID:     ruleID,
	}

	for _, rule := range rules {
		if rule.ID == *ruleID {
			item.SuggestedOwnerID = rule.OwnerUserID
			item.SuggestedModuleID = rule.ModuleID
			break
		}
	}

	return item
}

func (s *SignalTriageService) GetRoutingSuggestionStats(projectID uint) (map[string]interface{}, error) {
	var feedbacks []model.RoutingSuggestionFeedback
	if err := s.db.Joins("JOIN issue_clusters ON issue_clusters.id = routing_suggestion_feedbacks.cluster_id").
		Where("issue_clusters.project_id = ?", projectID).
		Find(&feedbacks).Error; err != nil {
		return nil, err
	}

	total := len(feedbacks)
	accepted := 0
	for _, fb := range feedbacks {
		if fb.Accepted {
			accepted++
		}
	}

	adoptionRate := 0.0
	if total > 0 {
		adoptionRate = float64(accepted) / float64(total) * 100
	}

	ruleStats := map[uint]struct{ total, accepted int }{}
	for _, fb := range feedbacks {
		if fb.RoutingRuleID != nil {
			stat := ruleStats[*fb.RoutingRuleID]
			stat.total++
			if fb.Accepted {
				stat.accepted++
			}
			ruleStats[*fb.RoutingRuleID] = stat
		}
	}

	ruleDetails := make([]map[string]interface{}, 0)
	for ruleID, stat := range ruleStats {
		rate := 0.0
		if stat.total > 0 {
			rate = float64(stat.accepted) / float64(stat.total) * 100
		}
		ruleDetails = append(ruleDetails, map[string]interface{}{
			"ruleId":        ruleID,
			"total":         stat.total,
			"accepted":      stat.accepted,
			"adoptionRate":  rate,
		})
	}

	return map[string]interface{}{
		"totalSuggestions": total,
		"accepted":         accepted,
		"adoptionRate":     adoptionRate,
		"ruleDetails":      ruleDetails,
	}, nil
}

func (s *SignalTriageService) AutoTriageClusters(projectID, operatorID uint) (int, int, error) {
	var allClusters []IssueClusterListItem

	for _, status := range []string{model.IssueTriageStatusNew, model.IssueTriageStatusClustered} {
		page := 1
		for {
			clusters, _, err := s.ListClusters(projectID, IssueClusterListParams{
				Status:   status,
				Page:     page,
				PageSize: 200,
			})
			if err != nil {
				return 0, 0, err
			}
			allClusters = append(allClusters, clusters...)
			if len(clusters) < 200 {
				break
			}
			page++
		}
	}

	if len(allClusters) == 0 {
		return 0, 0, nil
	}

	triaged := 0
	failed := 0

	for _, item := range allClusters {
		if item.SuggestedOwnerID == nil {
			continue
		}

		_, err := s.AssignCluster(projectID, item.ID, *item.SuggestedOwnerID, operatorID)
		if err != nil {
			failed++
			continue
		}
		triaged++
	}

	return triaged, failed, nil
}

// escapeLike 转义 SQL LIKE 模式中的通配符，防止用户输入被当作通配符
func escapeLike(s string) string {
	s = strings.ReplaceAll(s, "\\", "\\\\")
	s = strings.ReplaceAll(s, "%", "\\%")
	s = strings.ReplaceAll(s, "_", "\\_")
	return s
}
