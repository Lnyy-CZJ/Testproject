package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"errors"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type RegressionPreventionHandler struct {
	svc *service.RegressionPreventionService
}

func NewRegressionPreventionHandler(db *gorm.DB) *RegressionPreventionHandler {
	return &RegressionPreventionHandler{svc: service.NewRegressionPreventionService(db)}
}

func (h *RegressionPreventionHandler) ListItems(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	items, err := h.svc.ListItems(projectID, service.RegressionItemListParams{
		Status: c.Query("status"),
		Query:  c.Query("q"),
	})
	if err != nil {
		response.ServerError(c, "获取回归预防列表失败")
		return
	}
	response.Success(c, items)
}

func (h *RegressionPreventionHandler) CreateFromCluster(c *gin.Context) {
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

	item, err := h.svc.CreateFromCluster(projectID, clusterID, getUserID(c))
	if err != nil {
		if errors.Is(err, service.ErrIssueClusterNotFound) {
			response.NotFound(c, "问题簇不存在")
			return
		}
		response.ServerError(c, "创建回归预防项失败")
		return
	}
	response.Created(c, item)
}

func (h *RegressionPreventionHandler) UpdateItem(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	itemID, err := parsePathUintParam(c, "itemId")
	if err != nil {
		response.BadRequest(c, "无效的回归项 ID")
		return
	}

	var req struct {
		Title       *string `json:"title"`
		Summary     *string `json:"summary"`
		Status      string  `json:"status"`
		OwnerUserID *uint   `json:"ownerUserId"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	item, err := h.svc.UpdateItem(projectID, itemID, service.RegressionItemUpdateInput(req))
	if err != nil {
		switch {
		case errors.Is(err, service.ErrRegressionItemNotFound):
			response.NotFound(c, "回归预防项不存在")
		case errors.Is(err, service.ErrInvalidRegressionInput):
			response.BadRequest(c, "回归预防项参数不合法")
		default:
			response.ServerError(c, "更新回归预防项失败")
		}
		return
	}
	response.Success(c, item)
}
