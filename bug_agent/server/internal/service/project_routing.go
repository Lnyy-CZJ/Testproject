package service

import (
	"bug-agent/internal/model"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"
)

var (
	ErrProjectModuleNotFound    = errors.New("project module not found")
	ErrIssueRoutingRuleNotFound = errors.New("issue routing rule not found")
	ErrAppReleaseNotFound       = errors.New("app release not found")
	ErrInvalidProjectRouting    = errors.New("invalid project routing params")
)

var allowedRoutingMatchTypes = map[string]struct{}{
	"source_type":         {},
	"platform":            {},
	"app_version":         {},
	"fingerprint_pattern": {},
	"stack_keyword":       {},
}

type ProjectModuleInput struct {
	Name        string
	Code        string
	Description string
	OwnerUserID *uint
	RepoID      *uint
	PathPattern string
	Tags        string
}

type IssueRoutingRuleInput struct {
	MatchType        string
	MatchValue       string
	ModuleID         *uint
	OwnerUserID      *uint
	PriorityOverride string
	SeverityOverride string
	Enabled          bool
	SortOrder        int
}

type AppReleaseInput struct {
	Platform    string
	AppVersion  string
	BuildNumber string
	Channel     string
	ReleaseTime time.Time
	CommitSHA   string
	RepoID      *uint
	Metadata    map[string]interface{}
}

type IssueClusterReleaseMatch struct {
	Release           model.AppRelease `json:"release"`
	MatchMode         string           `json:"matchMode"`
	SignalCount       int              `json:"signalCount"`
	AffectedUserCount int              `json:"affectedUserCount"`
	LastSeenAt        time.Time        `json:"lastSeenAt"`
}

type AppReleaseTrendItem struct {
	Release                   model.AppRelease  `json:"release"`
	ClusterCount              int               `json:"clusterCount"`
	SignalCount               int               `json:"signalCount"`
	AffectedUserCount         int               `json:"affectedUserCount"`
	LastSeenAt                *time.Time        `json:"lastSeenAt,omitempty"`
	PreviousRelease           *model.AppRelease `json:"previousRelease,omitempty"`
	PreviousClusterCount      int               `json:"previousClusterCount"`
	PreviousAffectedUserCount int               `json:"previousAffectedUserCount"`
	ClusterDelta              int               `json:"clusterDelta"`
	AffectedUserDelta         int               `json:"affectedUserDelta"`
	AnomalyLevel              string            `json:"anomalyLevel"`
}

type releaseLookupKey struct {
	platform   string
	appVersion string
}

type ProjectRoutingService struct {
	db *gorm.DB
}

func NewProjectRoutingService(db *gorm.DB) *ProjectRoutingService {
	return &ProjectRoutingService{db: db}
}

func (s *ProjectRoutingService) ListModules(projectID uint) ([]model.ProjectModule, error) {
	var items []model.ProjectModule
	if err := s.db.Where("project_id = ?", projectID).Order("created_at desc, id desc").Find(&items).Error; err != nil {
		return nil, err
	}
	return items, nil
}

func (s *ProjectRoutingService) CreateModule(projectID uint, input ProjectModuleInput) (*model.ProjectModule, error) {
	module := &model.ProjectModule{
		ProjectID:   projectID,
		Name:        strings.TrimSpace(input.Name),
		Code:        strings.TrimSpace(input.Code),
		Description: strings.TrimSpace(input.Description),
		OwnerUserID: normalizeOptionalUint(input.OwnerUserID),
		RepoID:      normalizeOptionalUint(input.RepoID),
		PathPattern: strings.TrimSpace(input.PathPattern),
		Tags:        strings.TrimSpace(input.Tags),
	}
	if module.Name == "" || module.Code == "" {
		return nil, ErrInvalidProjectRouting
	}
	if err := s.db.Create(module).Error; err != nil {
		return nil, err
	}
	return module, nil
}

func (s *ProjectRoutingService) UpdateModule(projectID, moduleID uint, input ProjectModuleInput) (*model.ProjectModule, error) {
	module, err := s.getModule(projectID, moduleID)
	if err != nil {
		return nil, err
	}
	name := strings.TrimSpace(input.Name)
	code := strings.TrimSpace(input.Code)
	if name == "" || code == "" {
		return nil, ErrInvalidProjectRouting
	}
	module.Name = name
	module.Code = code
	module.Description = strings.TrimSpace(input.Description)
	module.OwnerUserID = normalizeOptionalUint(input.OwnerUserID)
	module.RepoID = normalizeOptionalUint(input.RepoID)
	module.PathPattern = strings.TrimSpace(input.PathPattern)
	module.Tags = strings.TrimSpace(input.Tags)
	if err := s.db.Save(module).Error; err != nil {
		return nil, err
	}
	return module, nil
}

func (s *ProjectRoutingService) DeleteModule(projectID, moduleID uint) error {
	return s.db.Transaction(func(tx *gorm.DB) error {
		module, err := s.getModuleWithDB(tx, projectID, moduleID)
		if err != nil {
			return err
		}
		if err := tx.Model(&model.IssueRoutingRule{}).
			Where("project_id = ? AND module_id = ?", projectID, module.ID).
			Update("module_id", nil).Error; err != nil {
			return err
		}
		if err := tx.Model(&model.IssueCluster{}).
			Where("project_id = ? AND module_id = ?", projectID, module.ID).
			Update("module_id", nil).Error; err != nil {
			return err
		}
		return tx.Delete(&model.ProjectModule{}, module.ID).Error
	})
}

func (s *ProjectRoutingService) ListRules(projectID uint) ([]model.IssueRoutingRule, error) {
	var items []model.IssueRoutingRule
	if err := s.db.Where("project_id = ?", projectID).Order("sort_order asc, id asc").Find(&items).Error; err != nil {
		return nil, err
	}
	return items, nil
}

func (s *ProjectRoutingService) CreateRule(projectID uint, input IssueRoutingRuleInput) (*model.IssueRoutingRule, error) {
	rule, err := s.buildRule(projectID, input, nil)
	if err != nil {
		return nil, err
	}
	if err := s.db.Create(rule).Error; err != nil {
		return nil, err
	}
	return rule, nil
}

func (s *ProjectRoutingService) UpdateRule(projectID, ruleID uint, input IssueRoutingRuleInput) (*model.IssueRoutingRule, error) {
	existing, err := s.getRule(projectID, ruleID)
	if err != nil {
		return nil, err
	}
	rule, err := s.buildRule(projectID, input, existing)
	if err != nil {
		return nil, err
	}
	if err := s.db.Save(rule).Error; err != nil {
		return nil, err
	}
	return rule, nil
}

func (s *ProjectRoutingService) DeleteRule(projectID, ruleID uint) error {
	rule, err := s.getRule(projectID, ruleID)
	if err != nil {
		return err
	}
	return s.db.Delete(&model.IssueRoutingRule{}, rule.ID).Error
}

func (s *ProjectRoutingService) ListReleases(projectID uint) ([]model.AppRelease, error) {
	var items []model.AppRelease
	if err := s.db.Where("project_id = ?", projectID).Order("release_time desc, id desc").Find(&items).Error; err != nil {
		return nil, err
	}
	return items, nil
}

func (s *ProjectRoutingService) ListReleaseTrends(projectID uint) ([]AppReleaseTrendItem, error) {
	releases, err := s.ListReleases(projectID)
	if err != nil {
		return nil, err
	}
	if len(releases) == 0 {
		return []AppReleaseTrendItem{}, nil
	}

	releaseMap := make(map[releaseLookupKey][]model.AppRelease)
	for _, release := range releases {
		key := releaseLookupKey{
			platform:   normalizeReleaseToken(release.Platform),
			appVersion: normalizeReleaseToken(release.AppVersion),
		}
		releaseMap[key] = append(releaseMap[key], release)
	}

	trendsByID := make(map[uint]*AppReleaseTrendItem, len(releases))
	clusterSets := make(map[uint]map[uint]struct{}, len(releases))
	for _, release := range releases {
		releaseCopy := release
		trendsByID[release.ID] = &AppReleaseTrendItem{
			Release:           releaseCopy,
			AnomalyLevel:      "baseline",
			ClusterCount:      0,
			SignalCount:       0,
			AffectedUserCount: 0,
		}
		clusterSets[release.ID] = make(map[uint]struct{})
	}

	var signals []model.IssueSignal
	if err := s.db.Where("project_id = ?", projectID).
		Order("last_seen_at desc, id desc").
		Find(&signals).Error; err != nil {
		return nil, err
	}

	for _, signal := range signals {
		release, _, ok := matchSignalToRelease(signal, releaseMap)
		if !ok {
			continue
		}
		item := trendsByID[release.ID]
		item.SignalCount++
		item.AffectedUserCount += signal.AffectedUserCount
		if signal.ClusterID != nil {
			clusterSets[release.ID][*signal.ClusterID] = struct{}{}
		}
		if item.LastSeenAt == nil || signal.LastSeenAt.After(*item.LastSeenAt) {
			lastSeenAt := signal.LastSeenAt
			item.LastSeenAt = &lastSeenAt
		}
	}

	for releaseID, clusterSet := range clusterSets {
		trendsByID[releaseID].ClusterCount = len(clusterSet)
	}

	groupedReleases := make(map[string][]model.AppRelease)
	for _, release := range releases {
		groupKey := normalizeReleaseToken(release.Platform) + ":" + normalizeReleaseChannel(release.Channel)
		groupedReleases[groupKey] = append(groupedReleases[groupKey], release)
	}

	for _, group := range groupedReleases {
		sort.Slice(group, func(i, j int) bool {
			if group[i].ReleaseTime.Equal(group[j].ReleaseTime) {
				return group[i].ID < group[j].ID
			}
			return group[i].ReleaseTime.Before(group[j].ReleaseTime)
		})

		for index, release := range group {
			item := trendsByID[release.ID]
			if index == 0 {
				item.AnomalyLevel = "baseline"
				continue
			}

			previousRelease := group[index-1]
			previousItem := trendsByID[previousRelease.ID]
			previousReleaseCopy := previousRelease
			item.PreviousRelease = &previousReleaseCopy
			item.PreviousClusterCount = previousItem.ClusterCount
			item.PreviousAffectedUserCount = previousItem.AffectedUserCount
			item.ClusterDelta = item.ClusterCount - previousItem.ClusterCount
			item.AffectedUserDelta = item.AffectedUserCount - previousItem.AffectedUserCount
			item.AnomalyLevel = classifyReleaseAnomaly(item.ClusterCount, previousItem.ClusterCount, item.AffectedUserCount, previousItem.AffectedUserCount)
		}
	}

	items := make([]AppReleaseTrendItem, 0, len(releases))
	for _, release := range releases {
		items = append(items, *trendsByID[release.ID])
	}
	return items, nil
}

func (s *ProjectRoutingService) CreateRelease(projectID uint, input AppReleaseInput) (*model.AppRelease, error) {
	release, err := s.buildRelease(projectID, input, nil)
	if err != nil {
		return nil, err
	}
	if err := s.db.Create(release).Error; err != nil {
		return nil, err
	}
	return release, nil
}

func (s *ProjectRoutingService) UpdateRelease(projectID, releaseID uint, input AppReleaseInput) (*model.AppRelease, error) {
	existing, err := s.getRelease(projectID, releaseID)
	if err != nil {
		return nil, err
	}
	release, err := s.buildRelease(projectID, input, existing)
	if err != nil {
		return nil, err
	}
	if err := s.db.Save(release).Error; err != nil {
		return nil, err
	}
	return release, nil
}

func (s *ProjectRoutingService) DeleteRelease(projectID, releaseID uint) error {
	release, err := s.getRelease(projectID, releaseID)
	if err != nil {
		return err
	}
	return s.db.Delete(&model.AppRelease{}, release.ID).Error
}

func (s *ProjectRoutingService) ListClusterReleaseMatches(projectID, clusterID uint) ([]IssueClusterReleaseMatch, error) {
	var cluster model.IssueCluster
	if err := s.db.
		Where("project_id = ? AND id = ?", projectID, clusterID).
		First(&cluster).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrIssueClusterNotFound
		}
		return nil, err
	}

	var signals []model.IssueSignal
	if err := s.db.
		Where("project_id = ? AND cluster_id = ?", projectID, clusterID).
		Order("last_seen_at desc, id desc").
		Find(&signals).Error; err != nil {
		return nil, err
	}
	if len(signals) == 0 {
		return []IssueClusterReleaseMatch{}, nil
	}

	releaseKeys := make(map[releaseLookupKey]struct{})
	platforms := make(map[string]struct{})
	appVersions := make(map[string]struct{})
	for _, signal := range signals {
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
		return []IssueClusterReleaseMatch{}, nil
	}

	var releases []model.AppRelease
	if err := s.db.
		Where("project_id = ? AND LOWER(platform) IN ? AND LOWER(app_version) IN ?", projectID, mapKeys(platforms), mapKeys(appVersions)).
		Order("release_time desc, id desc").
		Find(&releases).Error; err != nil {
		return nil, err
	}

	releaseMap := make(map[releaseLookupKey][]model.AppRelease)
	for _, release := range releases {
		key := releaseLookupKey{
			platform:   normalizeReleaseToken(release.Platform),
			appVersion: normalizeReleaseToken(release.AppVersion),
		}
		if _, ok := releaseKeys[key]; !ok {
			continue
		}
		releaseMap[key] = append(releaseMap[key], release)
	}

	aggregated := make(map[uint]*IssueClusterReleaseMatch)
	for _, signal := range signals {
		release, matchMode, ok := matchSignalToRelease(signal, releaseMap)
		if !ok {
			continue
		}
		item, exists := aggregated[release.ID]
		if !exists {
			item = &IssueClusterReleaseMatch{
				Release:           release,
				MatchMode:         matchMode,
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
		if item.MatchMode != "exact_build" && matchMode == "exact_build" {
			item.MatchMode = "exact_build"
		}
	}

	items := make([]IssueClusterReleaseMatch, 0, len(aggregated))
	for _, item := range aggregated {
		items = append(items, *item)
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].Release.ReleaseTime.Equal(items[j].Release.ReleaseTime) {
			return items[i].Release.ID > items[j].Release.ID
		}
		return items[i].Release.ReleaseTime.After(items[j].Release.ReleaseTime)
	})
	return items, nil
}

func (s *ProjectRoutingService) ApplyClusterRouting(signal *model.IssueSignal, cluster *model.IssueCluster) error {
	if signal == nil || cluster == nil || signal.ProjectID == 0 {
		return nil
	}

	var rules []model.IssueRoutingRule
	if err := s.db.
		Where("project_id = ? AND enabled = ?", signal.ProjectID, true).
		Order("sort_order asc, id asc").
		Find(&rules).Error; err != nil {
		return err
	}

	for _, rule := range rules {
		if !matchesRoutingRule(rule, signal) {
			continue
		}
		if cluster.ModuleID == nil && rule.ModuleID != nil {
			cluster.ModuleID = normalizeOptionalUint(rule.ModuleID)
		}
		if cluster.OwnerUserID == nil {
			switch {
			case rule.OwnerUserID != nil:
				cluster.OwnerUserID = normalizeOptionalUint(rule.OwnerUserID)
			case rule.ModuleID != nil:
				module, err := s.getModuleWithDB(s.db, signal.ProjectID, *rule.ModuleID)
				if err == nil && module.OwnerUserID != nil {
					cluster.OwnerUserID = normalizeOptionalUint(module.OwnerUserID)
				}
			}
		}
		if strings.TrimSpace(rule.PriorityOverride) != "" {
			cluster.Priority = truncateText(strings.TrimSpace(rule.PriorityOverride), 20)
		}
		if strings.TrimSpace(rule.SeverityOverride) != "" {
			cluster.Severity = truncateText(strings.TrimSpace(rule.SeverityOverride), 20)
		}
		break
	}

	return nil
}

func (s *ProjectRoutingService) buildRule(projectID uint, input IssueRoutingRuleInput, existing *model.IssueRoutingRule) (*model.IssueRoutingRule, error) {
	matchType := strings.TrimSpace(input.MatchType)
	matchValue := strings.TrimSpace(input.MatchValue)
	if _, ok := allowedRoutingMatchTypes[matchType]; !ok || matchValue == "" {
		return nil, ErrInvalidProjectRouting
	}
	if input.ModuleID != nil {
		if _, err := s.getModule(projectID, *input.ModuleID); err != nil {
			return nil, err
		}
	}
	rule := existing
	if rule == nil {
		rule = &model.IssueRoutingRule{ProjectID: projectID}
	}
	rule.MatchType = matchType
	rule.MatchValue = matchValue
	rule.ModuleID = normalizeOptionalUint(input.ModuleID)
	rule.OwnerUserID = normalizeOptionalUint(input.OwnerUserID)
	rule.PriorityOverride = strings.TrimSpace(input.PriorityOverride)
	rule.SeverityOverride = strings.TrimSpace(input.SeverityOverride)
	rule.Enabled = input.Enabled
	rule.SortOrder = input.SortOrder
	return rule, nil
}

func (s *ProjectRoutingService) buildRelease(projectID uint, input AppReleaseInput, existing *model.AppRelease) (*model.AppRelease, error) {
	platform := strings.TrimSpace(input.Platform)
	appVersion := strings.TrimSpace(input.AppVersion)
	if platform == "" || appVersion == "" {
		return nil, ErrInvalidProjectRouting
	}
	metadataJSON := ""
	if len(input.Metadata) > 0 {
		raw, err := json.Marshal(input.Metadata)
		if err != nil {
			return nil, ErrInvalidProjectRouting
		}
		metadataJSON = string(raw)
	}
	release := existing
	if release == nil {
		release = &model.AppRelease{ProjectID: projectID}
	}
	release.Platform = platform
	release.AppVersion = appVersion
	release.BuildNumber = strings.TrimSpace(input.BuildNumber)
	release.Channel = strings.TrimSpace(input.Channel)
	release.ReleaseTime = input.ReleaseTime
	release.CommitSHA = strings.TrimSpace(input.CommitSHA)
	release.RepoID = normalizeOptionalUint(input.RepoID)
	release.MetadataJSON = metadataJSON
	return release, nil
}

func (s *ProjectRoutingService) getModule(projectID, moduleID uint) (*model.ProjectModule, error) {
	return s.getModuleWithDB(s.db, projectID, moduleID)
}

func (s *ProjectRoutingService) getModuleWithDB(db *gorm.DB, projectID, moduleID uint) (*model.ProjectModule, error) {
	var module model.ProjectModule
	if err := db.Where("project_id = ? AND id = ?", projectID, moduleID).First(&module).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrProjectModuleNotFound
		}
		return nil, err
	}
	return &module, nil
}

func (s *ProjectRoutingService) getRule(projectID, ruleID uint) (*model.IssueRoutingRule, error) {
	var rule model.IssueRoutingRule
	if err := s.db.Where("project_id = ? AND id = ?", projectID, ruleID).First(&rule).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrIssueRoutingRuleNotFound
		}
		return nil, err
	}
	return &rule, nil
}

func (s *ProjectRoutingService) getRelease(projectID, releaseID uint) (*model.AppRelease, error) {
	var release model.AppRelease
	if err := s.db.Where("project_id = ? AND id = ?", projectID, releaseID).First(&release).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrAppReleaseNotFound
		}
		return nil, err
	}
	return &release, nil
}

func matchesRoutingRule(rule model.IssueRoutingRule, signal *model.IssueSignal) bool {
	matchValue := strings.TrimSpace(strings.ToLower(rule.MatchValue))
	if matchValue == "" || signal == nil {
		return false
	}

	switch rule.MatchType {
	case "source_type":
		return strings.EqualFold(strings.TrimSpace(signal.SourceType), rule.MatchValue)
	case "platform":
		return strings.EqualFold(strings.TrimSpace(signal.Platform), rule.MatchValue)
	case "app_version":
		av := strings.ToLower(strings.TrimSpace(signal.AppVersion))
		return av == matchValue || strings.HasPrefix(av, matchValue+".")
	case "fingerprint_pattern":
		return strings.Contains(strings.ToLower(strings.TrimSpace(signal.Fingerprint)), matchValue)
	case "stack_keyword":
		stack := strings.ToLower(strings.TrimSpace(signal.StackTrace + "\n" + signal.LogExcerpt + "\n" + signal.Description))
		return strings.Contains(stack, matchValue)
	default:
		return false
	}
}

func matchSignalToRelease(signal model.IssueSignal, releaseMap map[releaseLookupKey][]model.AppRelease) (model.AppRelease, string, bool) {
	key := releaseLookupKey{
		platform:   normalizeReleaseToken(signal.Platform),
		appVersion: normalizeReleaseToken(signal.AppVersion),
	}
	candidates := releaseMap[key]
	if len(candidates) == 0 {
		return model.AppRelease{}, "", false
	}

	buildNumber := normalizeReleaseToken(signal.BuildNumber)
	if buildNumber != "" {
		for _, release := range candidates {
			if normalizeReleaseToken(release.BuildNumber) == buildNumber {
				return release, "exact_build", true
			}
		}
	}

	if len(candidates) == 1 {
		return candidates[0], "app_version", true
	}

	return model.AppRelease{}, "", false
}

func normalizeReleaseToken(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func normalizeReleaseChannel(value string) string {
	channel := normalizeReleaseToken(value)
	if channel == "" {
		return "default"
	}
	return channel
}

func mapKeys(values map[string]struct{}) []string {
	items := make([]string, 0, len(values))
	for key := range values {
		items = append(items, key)
	}
	sort.Strings(items)
	return items
}

func classifyReleaseAnomaly(clusterCount, previousClusterCount, affectedUserCount, previousAffectedUserCount int) string {
	if previousClusterCount == 0 && previousAffectedUserCount == 0 {
		return "watch"
	}

	highAffected := affectedUserCount >= maxInt(previousAffectedUserCount+10, previousAffectedUserCount*2)
	highCluster := clusterCount >= maxInt(previousClusterCount+3, previousClusterCount*2)
	if highAffected || highCluster {
		return "high"
	}

	watchAffected := affectedUserCount >= maxInt(previousAffectedUserCount+5, 5)
	watchCluster := clusterCount >= maxInt(previousClusterCount+1, 2)
	if watchAffected || watchCluster {
		return "watch"
	}

	return "normal"
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
