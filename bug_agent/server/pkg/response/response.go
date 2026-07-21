package response

import (
	"net/http"

	"bug-agent/pkg/logger"

	"github.com/gin-gonic/gin"
)

type Response struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

type PageData struct {
	Items    interface{} `json:"items"`
	Total    int64       `json:"total"`
	Page     int         `json:"page"`
	PageSize int         `json:"pageSize"`
}

func SuccessPage(c *gin.Context, items interface{}, total int64, page, pageSize int) {
	Success(c, PageData{
		Items:    items,
		Total:    total,
		Page:     page,
		PageSize: pageSize,
	})
}

func Success(c *gin.Context, data interface{}) {
	c.JSON(http.StatusOK, Response{
		Code:    0,
		Message: "success",
		Data:    data,
	})
}

func Created(c *gin.Context, data interface{}) {
	c.JSON(http.StatusCreated, Response{
		Code:    0,
		Message: "created",
		Data:    data,
	})
}

func Error(c *gin.Context, httpCode int, code int, message string) {
	c.JSON(httpCode, Response{
		Code:    code,
		Message: message,
	})
}

func BadRequest(c *gin.Context, message string) {
	Error(c, http.StatusBadRequest, 400, message)
}

func Unauthorized(c *gin.Context, message string) {
	Error(c, http.StatusUnauthorized, 401, message)
}

func Forbidden(c *gin.Context, message string) {
	Error(c, http.StatusForbidden, 403, message)
}

func NotFound(c *gin.Context, message string) {
	Error(c, http.StatusNotFound, 404, message)
}

func Conflict(c *gin.Context, message string) {
	Error(c, http.StatusConflict, 409, message)
}

func ServerError(c *gin.Context, message string) {
	Error(c, http.StatusInternalServerError, 500, message)
}

func ServerErrorWithLog(c *gin.Context, internalErr error, userMessage string) {
	logger.Errorf("[ServerError] %v", internalErr)
	Error(c, http.StatusInternalServerError, 500, userMessage)
}
