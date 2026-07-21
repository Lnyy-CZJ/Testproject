package service

import (
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"errors"
	"fmt"
	"sort"
	"strings"

	"gorm.io/gorm"
)

var validFilterKeys = map[string]bool{
	"d.type":     true,
	"d.severity": true,
	"d.priority": true,
	"d.status":   true,
}

func isValidFilterKey(key string) bool {
	return validFilterKeys[key]
}

var ErrDefectRecommendationNotFound = errors.New("defect not found")

type DefectRecommendationService struct {
	db *gorm.DB
}

type AssigneeRecommendation struct {
	UserID            uint     `json:"userId"`
	Username          string   `json:"username"`
	Nickname          string   `json:"nickname"`
	AgentTypes        []string `json:"agentTypes"`
	Score             float64  `json:"score"`
	Confidence        float64  `json:"confidence"`
	Reasons           []string `json:"reasons"`
	CurrentOpenLoad   int64    `json:"currentOpenLoad"`
	HistoricalHandled int64    `json:"historicalHandled"`
}

type AgentRecommendation struct {
	AgentType  string   `json:"agentType"`
	Label      string   `json:"label"`
	Score      float64  `json:"score"`
	Confidence float64  `json:"confidence"`
	Reasons    []string `json:"reasons"`
}

func NewDefectRecommendationService(db *gorm.DB) *DefectRecommendationService {
	return &DefectRecommendationService{db: db}
}

func (s *DefectRecommendationService) RecommendAssignees(defectID uint, limit int) ([]AssigneeRecommendation, error) {
	limit = normalizeRecommendationLimit(limit)
	defect, projectID, err := s.loadDefectWithProject(defectID)
	if err != nil {
		return nil, err
	}

	members, err := s.projectUsers(projectID)
	if err != nil {
		return nil, err
	}
	if len(members) == 0 {
		return []AssigneeRecommendation{}, nil
	}

	userIDs := make([]uint, 0, len(members))
	for _, user := range members {
		userIDs = append(userIDs, user.ID)
	}

	totalHandled := s.groupDefectCount(projectID, userIDs, nil, nil)
	typeResolved := s.groupDefectCount(
		projectID,
		userIDs,
		map[string]interface{}{"d.type": defect.Type},
		[]string{model.DefectStatusFixed, model.DefectStatusCompleted},
	)
	openLoad := s.groupDefectCount(
		projectID,
		userIDs,
		nil,
		[]string{
			model.DefectStatusPendingAssign,
			model.DefectStatusPendingAnalysis,
			model.DefectStatusAnalyzing,
			model.DefectStatusPendingFix,
			model.DefectStatusFixing,
			model.DefectStatusPendingVerify,
			model.DefectStatusSuspended,
		},
	)

	maxLoad := int64(1)
	for _, load := range openLoad {
		if load > maxLoad {
			maxLoad = load
		}
	}

	targetAgent := primaryAgentForDefectType(defect.Type)
	recommendations := make([]AssigneeRecommendation, 0, len(members))
	for _, user := range members {
		handled := totalHandled[user.ID]
		resolved := typeResolved[user.ID]
		load := openLoad[user.ID]
		agentTypes := splitAgentTypes(user.AgentTypes)
		match := hasAgentType(agentTypes, targetAgent)

		typeScore := ratio(resolved, handled+1)           // 0~1
		loadScore := 1 - ratio(load, maxLoad+1)           // 0~1
		historyScore := clamp(float64(handled)/8.0, 0, 1) // 0~1
		agentScore := 0.0
		if match {
			agentScore = 1
		}

		score := 0.48*typeScore + 0.24*loadScore + 0.18*historyScore + 0.10*agentScore
		score = clamp(score, 0, 1)

		reasons := make([]string, 0, 4)
		if resolved > 0 {
			reasons = append(reasons, fmt.Sprintf("同类型历史已完成 %d 条", resolved))
		}
		if load <= 1 {
			reasons = append(reasons, "当前待处理负载较低")
		}
		if match {
			reasons = append(reasons, fmt.Sprintf("AGENT 身份包含 %s", targetAgent))
		}
		if handled > 0 {
			reasons = append(reasons, fmt.Sprintf("项目内累计处理 %d 条", handled))
		}
		if len(reasons) == 0 {
			reasons = append(reasons, "项目成员，推荐作为候选负责人")
		}

		recommendations = append(recommendations, AssigneeRecommendation{
			UserID:            user.ID,
			Username:          user.Username,
			Nickname:          user.Nickname,
			AgentTypes:        agentTypes,
			Score:             round2(score),
			Confidence:        round2(score),
			Reasons:           reasons,
			CurrentOpenLoad:   load,
			HistoricalHandled: handled,
		})
	}

	sort.SliceStable(recommendations, func(i, j int) bool {
		if recommendations[i].Score == recommendations[j].Score {
			return recommendations[i].CurrentOpenLoad < recommendations[j].CurrentOpenLoad
		}
		return recommendations[i].Score > recommendations[j].Score
	})
	if len(recommendations) > limit {
		recommendations = recommendations[:limit]
	}
	return recommendations, nil
}

func (s *DefectRecommendationService) RecommendAgents(defectID uint, limit int) ([]AgentRecommendation, error) {
	limit = normalizeRecommendationLimit(limit)
	defect, projectID, err := s.loadDefectWithProject(defectID)
	if err != nil {
		return nil, err
	}

	base := baseAgentWeights(defect.Type)
	history := s.agentHistoryScores(projectID, defect.Type)
	maxHistory := int64(1)
	for _, count := range history {
		if count > maxHistory {
			maxHistory = count
		}
	}

	seen := make(map[string]struct{}, len(base)+len(history))
	agentTypes := make([]string, 0, len(base)+len(history))
	for key := range base {
		if key == "" {
			continue
		}
		seen[key] = struct{}{}
		agentTypes = append(agentTypes, key)
	}
	for key := range history {
		if _, ok := seen[key]; ok || key == "" {
			continue
		}
		agentTypes = append(agentTypes, key)
	}

	recommendations := make([]AgentRecommendation, 0, len(agentTypes))
	for _, agentType := range agentTypes {
		baseScore := base[agentType]
		historyScore := ratio(history[agentType], maxHistory+1)
		score := clamp(0.72*baseScore+0.28*historyScore, 0, 1)
		reasons := []string{}
		if baseScore >= 0.85 {
			reasons = append(reasons, "与当前缺陷类型匹配度高")
		}
		if history[agentType] > 0 {
			reasons = append(reasons, fmt.Sprintf("历史分析命中 %d 次", history[agentType]))
		}
		if len(reasons) == 0 {
			reasons = append(reasons, "作为兜底协作 AGENT")
		}
		recommendations = append(recommendations, AgentRecommendation{
			AgentType:  agentType,
			Label:      agentTypeLabel(agentType),
			Score:      round2(score),
			Confidence: round2(score),
			Reasons:    reasons,
		})
	}

	sort.SliceStable(recommendations, func(i, j int) bool {
		return recommendations[i].Score > recommendations[j].Score
	})
	if len(recommendations) > limit {
		recommendations = recommendations[:limit]
	}
	return recommendations, nil
}

func (s *DefectRecommendationService) loadDefectWithProject(defectID uint) (*model.Defect, uint, error) {
	var defect model.Defect
	if err := s.db.Preload("Iteration").First(&defect, defectID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, 0, ErrDefectRecommendationNotFound
		}
		return nil, 0, err
	}
	if defect.Iteration.ID == 0 {
		return nil, 0, errors.New("defect iteration not found")
	}
	return &defect, defect.Iteration.ProjectID, nil
}

func (s *DefectRecommendationService) projectUsers(projectID uint) ([]model.User, error) {
	var members []model.ProjectMember
	if err := s.db.Where("project_id = ?", projectID).Find(&members).Error; err != nil {
		return nil, err
	}
	if len(members) == 0 {
		return []model.User{}, nil
	}
	ids := make([]uint, 0, len(members))
	for _, member := range members {
		ids = append(ids, member.UserID)
	}
	var users []model.User
	if err := s.db.Select("id", "username", "nickname", "agent_types").Where("id IN ?", ids).Find(&users).Error; err != nil {
		return nil, err
	}
	return users, nil
}

func (s *DefectRecommendationService) groupDefectCount(projectID uint, assigneeIDs []uint, eqFilters map[string]interface{}, statuses []string) map[uint]int64 {
	type countRow struct {
		AssigneeID uint
		Count      int64
	}
	result := make(map[uint]int64, len(assigneeIDs))
	if len(assigneeIDs) == 0 {
		return result
	}
	query := s.db.Table("defects d").
		Select("d.assignee_id as assignee_id, COUNT(*) as count").
		Joins("JOIN iterations i ON i.id = d.iteration_id").
		Where("i.project_id = ? AND d.assignee_id IN ?", projectID, assigneeIDs).
		Group("d.assignee_id")

	for key, value := range eqFilters {
		if !isValidFilterKey(key) {
			logger.Warnf("[DefectRecommendation] invalid filter key ignored: %s", key)
			continue
		}
		query = query.Where(fmt.Sprintf("%s = ?", key), value)
	}
	if len(statuses) > 0 {
		query = query.Where("d.status IN ?", statuses)
	}
	var rows []countRow
	if err := query.Scan(&rows).Error; err != nil {
		return result
	}
	for _, row := range rows {
		result[row.AssigneeID] = row.Count
	}
	return result
}

func (s *DefectRecommendationService) agentHistoryScores(projectID uint, defectType string) map[string]int64 {
	type countRow struct {
		AgentType string
		Count     int64
	}
	result := map[string]int64{}
	var rows []countRow
	err := s.db.Table("analysis_reports ar").
		Select("ar.agent_type as agent_type, COUNT(*) as count").
		Joins("JOIN defects d ON d.id = ar.defect_id").
		Joins("JOIN iterations i ON i.id = d.iteration_id").
		Where("i.project_id = ? AND d.type = ? AND ar.status IN ?", projectID, defectType, []string{"completed", "completed_fallback"}).
		Group("ar.agent_type").
		Scan(&rows).Error
	if err != nil {
		return result
	}
	for _, row := range rows {
		if strings.TrimSpace(row.AgentType) == "" {
			continue
		}
		result[row.AgentType] = row.Count
	}
	return result
}

func normalizeRecommendationLimit(limit int) int {
	if limit <= 0 {
		return 3
	}
	if limit > 5 {
		return 5
	}
	return limit
}

func splitAgentTypes(raw string) []string {
	parts := strings.Split(raw, ",")
	values := make([]string, 0, len(parts))
	for _, part := range parts {
		value := strings.TrimSpace(part)
		if value == "" {
			continue
		}
		values = append(values, value)
	}
	return values
}

func hasAgentType(values []string, target string) bool {
	target = strings.TrimSpace(target)
	if target == "" {
		return false
	}
	for _, value := range values {
		if strings.EqualFold(strings.TrimSpace(value), target) {
			return true
		}
	}
	return false
}

func primaryAgentForDefectType(defectType string) string {
	switch strings.TrimSpace(defectType) {
	case model.DefectTypeUI:
		return "ui"
	case model.DefectTypePerformance:
		return "backend"
	case model.DefectTypeSecurity:
		return "backend"
	case model.DefectTypeCompatibility:
		return "client"
	default:
		return "product"
	}
}

func baseAgentWeights(defectType string) map[string]float64 {
	switch strings.TrimSpace(defectType) {
	case model.DefectTypeUI:
		return map[string]float64{"ui": 0.98, "frontend": 0.92, "test": 0.8, "product": 0.62}
	case model.DefectTypePerformance:
		return map[string]float64{"backend": 0.96, "frontend": 0.86, "test": 0.78, "client": 0.68}
	case model.DefectTypeSecurity:
		return map[string]float64{"backend": 0.97, "test": 0.88, "product": 0.74}
	case model.DefectTypeCompatibility:
		return map[string]float64{"client": 0.95, "frontend": 0.86, "test": 0.8}
	default:
		return map[string]float64{"product": 0.9, "backend": 0.82, "test": 0.78, "frontend": 0.7}
	}
}

func agentTypeLabel(agentType string) string {
	labels := map[string]string{
		"product":  "产品 AGENT",
		"ui":       "UI AGENT",
		"frontend": "前端 AGENT",
		"client":   "客户端 AGENT",
		"backend":  "后端 AGENT",
		"test":     "测试 AGENT",
	}
	if label, ok := labels[agentType]; ok {
		return label
	}
	return agentType
}

func ratio(num, den int64) float64 {
	if den <= 0 {
		return 0
	}
	return clamp(float64(num)/float64(den), 0, 1)
}

func clamp(value, min, max float64) float64 {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}

func round2(value float64) float64 {
	return float64(int(value*100+0.5)) / 100
}
