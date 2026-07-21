package handler

import (
	"bug-agent/internal/middleware"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"errors"
	"fmt"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type IssuePoolHandler struct {
	svc       *service.SignalTriageService
	routingSv *service.ProjectRoutingService
}

func NewIssuePoolHandler(db *gorm.DB) *IssuePoolHandler {
	return &IssuePoolHandler{
		svc:       service.NewSignalTriageService(db),
		routingSv: service.NewProjectRoutingService(db),
	}
}

func (h *IssuePoolHandler) ListClusters(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	page, pageSize := parsePagination(c, 100)
	releaseID, err := parseOptionalUintQuery(c, "releaseId")
	if err != nil {
		response.BadRequest(c, "无效的版本发布 ID")
		return
	}

	items, total, err := h.svc.ListClusters(projectID, service.IssueClusterListParams{
		Status:       c.Query("status"),
		Query:        c.Query("q"),
		Platform:     c.Query("platform"),
		AppVersion:   c.Query("appVersion"),
		ReleaseID:    releaseID,
		AnomalyLevel: c.Query("anomalyLevel"),
		Page:         page,
		PageSize:     pageSize,
	})
	if err != nil {
		response.ServerError(c, "获取问题池失败")
		return
	}
	response.Success(c, gin.H{
		"items":    items,
		"total":    total,
		"page":     page,
		"pageSize": pageSize,
	})
}

func (h *IssuePoolHandler) ListReleaseSummaries(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	releaseID, err := parseOptionalUintQuery(c, "releaseId")
	if err != nil {
		response.BadRequest(c, "无效的版本发布 ID")
		return
	}

	items, err := h.svc.ListReleaseSummaries(projectID, service.IssueClusterListParams{
		Status:       c.Query("status"),
		Query:        c.Query("q"),
		Platform:     c.Query("platform"),
		AppVersion:   c.Query("appVersion"),
		ReleaseID:    releaseID,
		AnomalyLevel: c.Query("anomalyLevel"),
	})
	if err != nil {
		response.ServerError(c, "获取问题池版本汇总失败")
		return
	}
	response.Success(c, items)
}

func (h *IssuePoolHandler) GetCluster(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	clusterID, err := parsePathUintParam(c, "clusterId")
	if err != nil {
		response.BadRequest(c, "无效的问题簇 ID")
		return
	}

	cluster, err := h.svc.GetCluster(projectID, clusterID)
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "获取问题簇详情失败")
		return
	}
	response.Success(c, cluster)
}

func (h *IssuePoolHandler) ListSignals(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	clusterID, err := parsePathUintParam(c, "clusterId")
	if err != nil {
		response.BadRequest(c, "无效的问题簇 ID")
		return
	}

	signals, err := h.svc.ListSignals(projectID, clusterID)
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "获取信号列表失败")
		return
	}
	response.Success(c, gin.H{"items": signals, "total": len(signals)})
}

func (h *IssuePoolHandler) ListClusterReleases(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	clusterID, err := parsePathUintParam(c, "clusterId")
	if err != nil {
		response.BadRequest(c, "无效的问题簇 ID")
		return
	}

	items, err := h.routingSv.ListClusterReleaseMatches(projectID, clusterID)
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "获取问题簇版本影响失败")
		return
	}
	response.Success(c, items)
}

func (h *IssuePoolHandler) AssignCluster(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	clusterID, err := parsePathUintParam(c, "clusterId")
	if err != nil {
		response.BadRequest(c, "无效的问题簇 ID")
		return
	}

	var req struct {
		OwnerUserID uint `json:"ownerUserId" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	cluster, err := h.svc.AssignCluster(projectID, clusterID, req.OwnerUserID, getUserID(c))
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "指派问题簇失败")
		return
	}
	response.Success(c, cluster)
}

func (h *IssuePoolHandler) BatchAssignClusters(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		ClusterIDs  []uint `json:"clusterIds" binding:"required,max=50"`
		OwnerUserID uint   `json:"ownerUserId" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	count, err := h.svc.BatchAssignClusters(projectID, req.ClusterIDs, req.OwnerUserID, getUserID(c))
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "批量指派问题簇失败")
		return
	}
	response.Success(c, gin.H{"updatedCount": count})
}

func (h *IssuePoolHandler) IgnoreCluster(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	clusterID, err := parsePathUintParam(c, "clusterId")
	if err != nil {
		response.BadRequest(c, "无效的问题簇 ID")
		return
	}

	var req struct {
		Reason string `json:"reason"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	cluster, err := h.svc.IgnoreCluster(projectID, clusterID, getUserID(c), req.Reason)
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "忽略问题簇失败")
		return
	}
	response.Success(c, cluster)
}

func (h *IssuePoolHandler) BatchIgnoreClusters(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		ClusterIDs []uint `json:"clusterIds" binding:"required,max=50"`
		Reason     string `json:"reason"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	count, err := h.svc.BatchIgnoreClusters(projectID, req.ClusterIDs, getUserID(c), req.Reason)
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "批量忽略问题簇失败")
		return
	}
	response.Success(c, gin.H{"updatedCount": count})
}

func (h *IssuePoolHandler) MergeCluster(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	clusterID, err := parsePathUintParam(c, "clusterId")
	if err != nil {
		response.BadRequest(c, "无效的问题簇 ID")
		return
	}

	var req struct {
		TargetClusterID uint   `json:"targetClusterId" binding:"required"`
		Reason          string `json:"reason"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	source, target, err := h.svc.MergeCluster(projectID, clusterID, req.TargetClusterID, getUserID(c), req.Reason)
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "合并问题簇失败")
		return
	}
	response.Success(c, gin.H{
		"sourceCluster": source,
		"targetCluster": target,
	})
}

func (h *IssuePoolHandler) ConvertCluster(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	clusterID, err := parsePathUintParam(c, "clusterId")
	if err != nil {
		response.BadRequest(c, "无效的问题簇 ID")
		return
	}

	cluster, defect, err := h.svc.ConvertCluster(projectID, clusterID, getUserID(c))
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "转缺陷失败")
		return
	}
	response.Success(c, gin.H{
		"cluster": cluster,
		"defect":  defect,
	})
}

func (h *IssuePoolHandler) BatchConvertClusters(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		ClusterIDs []uint `json:"clusterIds" binding:"required,max=50"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	count, defectIDs, err := h.svc.BatchConvertClusters(projectID, req.ClusterIDs, getUserID(c))
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "批量转缺陷失败")
		return
	}
	response.Success(c, gin.H{"updatedCount": count, "defectIds": defectIDs})
}

func (h *IssuePoolHandler) AutoTriageClusters(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	userID := middleware.GetUserID(c)

	triaged, failed, err := h.svc.AutoTriageClusters(projectID, userID)
	if err != nil {
		response.ServerErrorWithLog(c, err, "自动分诊失败")
		return
	}

	response.Success(c, gin.H{
		"triaged": triaged,
		"failed":  failed,
		"message": fmt.Sprintf("自动分诊完成：成功 %d 个，失败 %d 个", triaged, failed),
	})
}

func (h *IssuePoolHandler) GetRoutingSuggestionStats(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	stats, err := h.svc.GetRoutingSuggestionStats(projectID)
	if err != nil {
		response.ServerErrorWithLog(c, err, "获取建议统计失败")
		return
	}

	response.Success(c, stats)
}

func parsePathUintParam(c *gin.Context, key string) (uint, error) {
	value, err := strconv.ParseUint(c.Param(key), 10, 64)
	if err != nil || value == 0 {
		if err != nil {
			return 0, err
		}
		return 0, fmt.Errorf("%s is required", key)
	}
	return uint(value), nil
}

func parseOptionalUintQuery(c *gin.Context, key string) (uint, error) {
	value := c.Query(key)
	if value == "" {
		return 0, nil
	}

	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return 0, err
	}
	return uint(parsed), nil
}
