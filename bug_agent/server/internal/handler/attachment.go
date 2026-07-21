package handler

import (
	"bug-agent/internal/config"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type AttachmentHandler struct {
	db *gorm.DB
}

func NewAttachmentHandler(db *gorm.DB) *AttachmentHandler { return &AttachmentHandler{db: db} }

// UploadAttachment 上传附件
func (h *AttachmentHandler) UploadAttachment(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	var defect model.Defect
	if err := h.db.First(&defect, defectID).Error; err != nil {
		response.NotFound(c, "缺陷不存在")
		return
	}

	// 获取上传的文件
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		response.BadRequest(c, "请选择要上传的文件")
		return
	}
	defer file.Close()

	// 文件大小限制 (10MB)
	const maxSize = 10 * 1024 * 1024
	if header.Size > maxSize {
		response.BadRequest(c, "文件大小不能超过10MB")
		return
	}

	// 获取文件扩展名
	ext := strings.ToLower(filepath.Ext(header.Filename))

	// 允许的文件类型
	allowedExts := map[string]bool{
		".jpg": true, ".jpeg": true, ".png": true, ".gif": true, ".webp": true,
		".mp4": true, ".avi": true, ".mov": true, ".webm": true, ".mkv": true,
		".pdf": true, ".doc": true, ".docx": true, ".xls": true, ".xlsx": true,
		".txt": true, ".md": true, ".json": true, ".xml": true,
		".zip": true, ".tar": true, ".gz": true,
		".log": true,
	}
	if !allowedExts[ext] {
		response.BadRequest(c, "不支持的文件类型")
		return
	}

	// 创建上传目录
	uploadDir := filepath.Join(config.C.Server.UploadDir, time.Now().Format("2006/01/02"))
	if err := os.MkdirAll(uploadDir, 0755); err != nil {
		response.BadRequest(c, "创建上传目录失败")
		return
	}

	// 生成唯一文件名
	filename := fmt.Sprintf("%d_%d%s", time.Now().UnixNano(), defectID, ext)
	filePath := filepath.Join(uploadDir, filename)

	// 创建目标文件
	dst, err := os.Create(filePath)
	if err != nil {
		response.BadRequest(c, "创建文件失败")
		return
	}
	defer dst.Close()

	// 复制文件内容
	if _, err := io.Copy(dst, file); err != nil {
		dst.Close()
		os.Remove(filePath)
		response.BadRequest(c, "保存文件失败")
		return
	}

	// 获取文件类型
	fileType := getFileType(ext)

	// 保存附件记录
	attachment := model.Attachment{
		DefectID:  uint(defectID),
		FileName:  header.Filename,
		FileURL:   "/" + strings.ReplaceAll(filePath, "\\", "/"),
		FileSize:  header.Size,
		FileType:  fileType,
		CreatedAt: time.Now(),
	}

	if err := h.db.Create(&attachment).Error; err != nil {
		os.Remove(filePath)
		response.BadRequest(c, "保存附件记录失败")
		return
	}

	response.Created(c, attachment)
}

// ListAttachments 获取附件列表
func (h *AttachmentHandler) ListAttachments(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	var attachments []model.Attachment
	if err := h.db.Where("defect_id = ?", defectID).Order("created_at DESC").Find(&attachments).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	response.Success(c, attachments)
}

// DeleteAttachment 删除附件
func (h *AttachmentHandler) DeleteAttachment(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	attachmentID, ok := parseIDParam(c, "attachmentId")
	if !ok {
		return
	}

	var attachment model.Attachment
	if err := h.db.Where("id = ? AND defect_id = ?", attachmentID, defectID).First(&attachment).Error; err != nil {
		response.NotFound(c, "附件不存在")
		return
	}

	// 删除文件
	uploadDir := config.C.Server.UploadDir
	if uploadDir == "" {
		uploadDir = "./uploads"
	}
	filePath := filepath.Join(uploadDir, strings.TrimPrefix(attachment.FileURL, "/"))
	if err := os.Remove(filePath); err != nil {
		// 文件不存在也继续删除记录
		logger.Errorf("删除文件失败: %v", err)
	}

	// 删除数据库记录
	if err := h.db.Delete(&attachment).Error; err != nil {
		logger.Errorf("删除附件记录失败: %v", err)
		response.ServerError(c, "删除附件记录失败")
		return
	}

	response.Success(c, gin.H{"message": "删除成功"})
}

// DownloadFile serves a file from the upload directory after authentication.
func (h *AttachmentHandler) DownloadFile(c *gin.Context) {
	filename := c.Param("filename")
	filename = strings.TrimPrefix(filename, "/")
	if filename == "" {
		response.BadRequest(c, "文件名不能为空")
		return
	}

	if strings.Contains(filename, "..") || strings.HasPrefix(filename, "/") {
		response.BadRequest(c, "非法文件路径")
		return
	}

	uploadDir := config.C.Server.UploadDir
	if uploadDir == "" {
		uploadDir = "./uploads"
	}
	filePath := filepath.Join(uploadDir, filename)

	// Ensure the resolved path is still within the upload directory
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		response.BadRequest(c, "非法文件路径")
		return
	}
	absUploadDir, err := filepath.Abs(uploadDir)
	if err != nil {
		response.ServerError(c, "上传目录配置错误")
		return
	}
	if !strings.HasPrefix(absPath, absUploadDir+string(filepath.Separator)) && absPath != absUploadDir {
		response.BadRequest(c, "非法文件路径")
		return
	}

	if _, err := os.Stat(absPath); os.IsNotExist(err) {
		response.NotFound(c, "文件不存在")
		return
	}

	c.File(absPath)
}

// getFileType 根据扩展名获取文件类型
func getFileType(ext string) string {
	switch ext {
	case ".jpg", ".jpeg", ".png", ".gif", ".webp":
		return "image"
	case ".mp4", ".avi", ".mov", ".webm", ".mkv":
		return "video"
	case ".pdf":
		return "pdf"
	case ".doc", ".docx":
		return "document"
	case ".xls", ".xlsx":
		return "spreadsheet"
	case ".txt", ".md", ".json", ".xml", ".log":
		return "text"
	case ".zip", ".tar", ".gz":
		return "archive"
	default:
		return "other"
	}
}
