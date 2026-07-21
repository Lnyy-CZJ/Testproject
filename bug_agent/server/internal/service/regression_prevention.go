package service

import (
	"bug-agent/internal/model"
	"errors"
	"strings"
	"time"

	"gorm.io/gorm"
)

var (
	ErrRegressionItemNotFound = errors.New("regression item not found")
	ErrInvalidRegressionInput = errors.New("invalid regression item input")
)

type RegressionItemListParams struct {
	Status string
	Query  string
}

type RegressionItemUpdateInput struct {
	Title       *string
	Summary     *string
	Status      string
	OwnerUserID *uint
}

type RegressionPreventionService struct {
	db *gorm.DB
}

func NewRegressionPreventionService(db *gorm.DB) *RegressionPreventionService {
	return &RegressionPreventionService{db: db}
}

func (s *RegressionPreventionService) ListItems(projectID uint, params RegressionItemListParams) ([]model.RegressionItem, error) {
	query := s.preloadItems(s.db.Where("project_id = ?", projectID))
	if status := normalizeRegressionStatus(params.Status); status != "" {
		query = query.Where("status = ?", status)
	}
	if q := strings.TrimSpace(params.Query); q != "" {
		like := "%" + escapeLike(q) + "%"
		query = query.Where("title LIKE ? OR summary LIKE ? OR source_fingerprint LIKE ?", like, like, like)
	}

	var items []model.RegressionItem
	if err := query.Order("updated_at desc, id desc").Find(&items).Error; err != nil {
		return nil, err
	}
	return items, nil
}

func (s *RegressionPreventionService) CreateFromCluster(projectID, clusterID, operatorID uint) (*model.RegressionItem, error) {
	cluster, err := s.loadCluster(projectID, clusterID)
	if err != nil {
		return nil, err
	}

	var existing model.RegressionItem
	if err := s.preloadItems(s.db.Where("project_id = ? AND cluster_id = ?", projectID, clusterID)).First(&existing).Error; err == nil {
		return &existing, nil
	} else if !errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, err
	}

	item := &model.RegressionItem{
		ProjectID:         projectID,
		ClusterID:         &cluster.ID,
		DefectID:          normalizeOptionalUint(cluster.LinkedDefectID),
		Title:             cluster.Title,
		Summary:           strings.TrimSpace(cluster.Summary),
		SourceFingerprint: strings.TrimSpace(cluster.ClusterKey),
		Status:            model.RegressionItemStatusDraft,
		OwnerUserID:       normalizeOptionalUint(cluster.OwnerUserID),
		CreatedBy:         operatorID,
	}
	if err := s.db.Create(item).Error; err != nil {
		return nil, err
	}
	return s.getItem(projectID, item.ID)
}

func (s *RegressionPreventionService) UpdateItem(projectID, itemID uint, input RegressionItemUpdateInput) (*model.RegressionItem, error) {
	item, err := s.getItem(projectID, itemID)
	if err != nil {
		return nil, err
	}

	if input.Title != nil {
		item.Title = strings.TrimSpace(*input.Title)
	}
	if input.Summary != nil {
		item.Summary = strings.TrimSpace(*input.Summary)
	}
	if input.OwnerUserID != nil {
		item.OwnerUserID = normalizeOptionalUint(input.OwnerUserID)
	}
	if input.Status != "" {
		status := normalizeRegressionStatus(input.Status)
		if status == "" {
			return nil, ErrInvalidRegressionInput
		}
		item.Status = status
		if status == model.RegressionItemStatusVerified {
			now := time.Now()
			item.LastVerifiedAt = &now
		}
	}
	if strings.TrimSpace(item.Title) == "" {
		return nil, ErrInvalidRegressionInput
	}
	if err := s.db.Save(item).Error; err != nil {
		return nil, err
	}
	return s.getItem(projectID, item.ID)
}

func (s *RegressionPreventionService) getItem(projectID, itemID uint) (*model.RegressionItem, error) {
	var item model.RegressionItem
	if err := s.preloadItems(s.db.Where("project_id = ? AND id = ?", projectID, itemID)).First(&item).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrRegressionItemNotFound
		}
		return nil, err
	}
	return &item, nil
}

func (s *RegressionPreventionService) loadCluster(projectID, clusterID uint) (*model.IssueCluster, error) {
	var cluster model.IssueCluster
	if err := s.db.
		Preload("Owner").
		Preload("Defect").
		Where("project_id = ? AND id = ?", projectID, clusterID).
		First(&cluster).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrIssueClusterNotFound
		}
		return nil, err
	}
	return &cluster, nil
}

func (s *RegressionPreventionService) preloadItems(query *gorm.DB) *gorm.DB {
	return query.
		Preload("Cluster").
		Preload("Defect").
		Preload("Owner").
		Preload("Creator")
}

func normalizeRegressionStatus(status string) string {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "":
		return ""
	case model.RegressionItemStatusDraft,
		model.RegressionItemStatusActive,
		model.RegressionItemStatusVerified,
		model.RegressionItemStatusArchived:
		return strings.ToLower(strings.TrimSpace(status))
	default:
		return ""
	}
}
