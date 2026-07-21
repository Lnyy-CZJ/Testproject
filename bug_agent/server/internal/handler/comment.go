package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"context"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type CommentHandler struct {
	db              *gorm.DB
	analysisService *adk.ADKAnalysisService
}

func NewCommentHandler(db *gorm.DB) *CommentHandler {
	return &CommentHandler{db: db}
}

func NewCommentHandlerWithAnalysisService(db *gorm.DB, analysisService *adk.ADKAnalysisService) *CommentHandler {
	return &CommentHandler{db: db, analysisService: analysisService}
}

func (h *CommentHandler) CreateComment(c *gin.Context) {
	userID, ok := getUserIDFromContext(c)
	if !ok {
		response.Unauthorized(c, "未登录")
		return
	}
	var req struct {
		Content  string `json:"content" binding:"required"`
		Mentions []uint `json:"mentions"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	comment := model.Comment{
		DefectID: uint(defectID),
		UserID:   userID,
		Content:  req.Content,
	}

	if result := h.db.Create(&comment); result.Error != nil {
		response.ServerError(c, "发布评论失败")
		return
	}

	if err := h.db.Preload("User").First(&comment, comment.ID).Error; err != nil {
		logger.Errorf("[CommentHandler] preload user for comment %d failed: %v", comment.ID, err)
	}

	var notifiedAgents []string
	mentionUserIDs := make([]uint, 0, len(req.Mentions))
	seenMentionUsers := make(map[uint]bool)
	for _, mentionUID := range req.Mentions {
		if mentionUID == userID || seenMentionUsers[mentionUID] {
			continue
		}
		var user model.User
		if h.db.First(&user, mentionUID).Error == nil {
			seenMentionUsers[mentionUID] = true
			mentionUserIDs = append(mentionUserIDs, mentionUID)
			if user.AgentTypes != "" {
				notifiedAgents = append(notifiedAgents, strings.Split(user.AgentTypes, ",")...)
			}
		}
	}

	agentMentioned := isAgentMentioned(req.Content)
	defectProjectID := h.loadProjectIDByDefect(uint(defectID))
	if agentMentioned {
		var projectRepos []model.ProjectRepo
		if err := h.db.Where("project_id = ? AND agent_types != '' AND agent_types IS NOT NULL", defectProjectID).Find(&projectRepos).Error; err != nil {
			logger.Errorf("查询项目仓库失败: %v", err)
		}
		for _, repo := range projectRepos {
			if repo.AgentTypes != "" {
				notifiedAgents = append(notifiedAgents, strings.Split(repo.AgentTypes, ",")...)
			}
		}
	}

	if len(mentionUserIDs) > 0 {
		projectID := defectProjectID
		notifier := service.NewNotificationService(h.db, nil)
		_, _ = notifier.Send(&service.NotifyRequest{
			UserIDs:   mentionUserIDs,
			Title:     "评论中提及了你",
			Content:   req.Content,
			Type:      "in_app",
			Category:  "defect_mention",
			ProjectID: projectID,
			RelatedID: uint(defectID),
			Metadata: map[string]interface{}{
				"comment_id": comment.ID,
				"defect_id":  defectID,
				"from_user":  userID,
			},
		})
	}

	if len(notifiedAgents) > 0 {
		var defect model.Defect
		if err := h.db.First(&defect, defectID).Error; err == nil {
			if defect.Status == model.DefectStatusPendingAnalysis || defect.Status == model.DefectStatusPendingFix {
				uniqueAgents := []string{}
				seen := map[string]bool{}
				for _, a := range notifiedAgents {
					if !seen[a] {
						seen[a] = true
						uniqueAgents = append(uniqueAgents, a)
					}
				}

				if len(uniqueAgents) == 0 {
					uniqueAgents = []string{"frontend"}
				}

				asyncx.Go(func() {
					ctx, cancel := context.WithTimeout(asyncx.ShutdownContext(), 10*time.Minute)
					defer cancel()
					result, err := h.performADKAnalysis(ctx, adk.ADKAnalysisRequest{
						DefectID:   uint(defectID),
						AgentTypes: uniqueAgents,
						UserID:     uint(userID),
					})
					if err != nil {
						logger.Errorf("[CommentHandler] 评论触发分析失败: 缺陷 #%d, 错误: %v", defectID, err)
						return
					}
					logger.Infof("[CommentHandler] 评论触发分析完成: 缺陷 #%d, 报告=%s", defectID, result.ReportCode)
				})
			}
		}
	}

	response.Created(c, gin.H{
		"comment": comment,
	})
}

func (h *CommentHandler) performADKAnalysis(ctx context.Context, req adk.ADKAnalysisRequest) (*adk.ADKAnalysisResult, error) {
	analysisService := h.analysisService
	if analysisService == nil {
		var err error
		analysisService, err = adk.NewADKAnalysisService(h.db)
		if err != nil {
			return nil, err
		}
	}
	return analysisService.PerformAnalysis(ctx, req)
}

func (h *CommentHandler) ListComments(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	var comments []model.Comment
	if err := h.db.Preload("User").Where("defect_id = ?", defectID).Order("created_at ASC").Find(&comments).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}
	response.Success(c, comments)
}

func (h *CommentHandler) loadProjectIDByDefect(defectID uint) uint {
	var projectID uint
	if err := h.db.Model(&model.Defect{}).
		Select("iterations.project_id").
		Joins("JOIN iterations ON iterations.id = defects.iteration_id").
		Where("defects.id = ?", defectID).
		Scan(&projectID).Error; err != nil {
		return 0
	}
	return projectID
}

func isAgentMentioned(content string) bool {
	upper := strings.ToUpper(content)
	for i := 0; i < len(upper); i++ {
		if upper[i] == '@' {
			rest := upper[i+1:]
			if strings.HasPrefix(rest, "AGENT") && (len(rest) == 5 || !isAlpha(rest[5])) && (i == 0 || !isAlpha(upper[i-1])) {
				return true
			}
		}
	}
	return false
}

func isAlpha(ch byte) bool {
	return (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z')
}
