package service

import (
	"bug-agent/internal/model"
	"fmt"
	"time"

	"gorm.io/gorm"
)

type WorkflowService struct {
	db *gorm.DB
}

func NewWorkflowService(db *gorm.DB) *WorkflowService {
	return &WorkflowService{db: db}
}

type TransitionRequest struct {
	DefectID uint   `json:"defectId" binding:"required"`
	ToStatus string `json:"toStatus" binding:"required"`
	Comment  string `json:"comment"`
	UserID   uint   `json:"userId"`
}

func (s *WorkflowService) Transition(req *TransitionRequest) (*model.StatusChange, error) {
	var defect model.Defect
	if err := s.db.First(&defect, req.DefectID).Error; err != nil {
		return nil, fmt.Errorf("defect not found: %w", err)
	}

	if !model.IsValidDefectTransition(defect.Status, req.ToStatus) {
		valid := model.GetValidTransitions(defect.Status)
		return nil, fmt.Errorf("invalid transition: %s -> %s, valid: %v", defect.Status, req.ToStatus, valid)
	}

	change := &model.StatusChange{
		DefectID:   req.DefectID,
		FromStatus: defect.Status,
		ToStatus:   req.ToStatus,
		ChangedBy:  req.UserID,
		Comment:    req.Comment,
		CreatedAt:  time.Now(),
	}

	if err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(change).Error; err != nil {
			return fmt.Errorf("failed to record status change: %w", err)
		}
		result := tx.Model(&model.Defect{}).Where("id = ? AND status = ?", req.DefectID, defect.Status).Update("status", req.ToStatus)
		if result.Error != nil {
			return fmt.Errorf("failed to update defect status: %w", result.Error)
		}
		if result.RowsAffected == 0 {
			return fmt.Errorf("conflict: defect %d status was changed concurrently", req.DefectID)
		}
		return nil
	}); err != nil {
		return nil, err
	}

	return change, nil
}

func (s *WorkflowService) GetHistory(defectID uint) ([]model.StatusChange, error) {
	var changes []model.StatusChange
	err := s.db.Where("defect_id = ?", defectID).
		Order("created_at desc").
		Find(&changes).Error
	return changes, err
}

func (s *WorkflowService) GetAvailableTransitions(defectID uint) ([]string, error) {
	var defect model.Defect
	if err := s.db.Select("status").First(&defect, defectID).Error; err != nil {
		return nil, fmt.Errorf("defect not found: %w", err)
	}
	return model.GetValidTransitions(defect.Status), nil
}

func (s *WorkflowService) BatchTransition(defectIDs []uint, toStatus string, userID uint, comment string) (int, []error) {
	// Project-level permission check: verify user has access to every defect's project.
	type defectProject struct {
		DefectID  uint
		ProjectID uint
	}
	var defectProjects []defectProject
	if err := s.db.Table("defects").
		Select("defects.id AS defect_id, iterations.project_id AS project_id").
		Joins("JOIN iterations ON iterations.id = defects.iteration_id").
		Where("defects.id IN ?", defectIDs).
		Scan(&defectProjects).Error; err != nil {
		return 0, []error{fmt.Errorf("failed to resolve defect projects: %w", err)}
	}

	defectToProject := make(map[uint]uint, len(defectProjects))
	for _, dp := range defectProjects {
		defectToProject[dp.DefectID] = dp.ProjectID
	}

	// Collect unique project IDs and verify membership for each.
	uniqueProjects := make(map[uint]struct{})
	for _, pid := range defectToProject {
		uniqueProjects[pid] = struct{}{}
	}
	for projectID := range uniqueProjects {
		var count int64
		s.db.Table("project_members").
			Where("project_id = ? AND user_id = ?", projectID, userID).
			Count(&count)
		if count == 0 {
			return 0, []error{fmt.Errorf("access denied: user %d is not a member of project %d", userID, projectID)}
		}
	}

	// Verify all requested defect IDs were found
	for _, id := range defectIDs {
		if _, ok := defectToProject[id]; !ok {
			return 0, []error{fmt.Errorf("defect %d not found", id)}
		}
	}

	var successes int
	var errors []error

	for _, id := range defectIDs {
		req := &TransitionRequest{
			DefectID: id,
			ToStatus: toStatus,
			Comment:  comment,
			UserID:   userID,
		}
		_, err := s.Transition(req)
		if err != nil {
			errors = append(errors, fmt.Errorf("defect %d: %w", id, err))
		} else {
			successes++
		}
	}

	return successes, errors
}
