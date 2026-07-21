import { logger } from '../utils/logger';
import { useState, useEffect, useCallback } from 'react';
import { Upload, Button, List, Image, Popconfirm, Space, Typography } from 'antd';
import { message } from '../utils/appMessage';
import { UploadOutlined, FileOutlined, DeleteOutlined, DownloadOutlined, PictureOutlined, FileTextOutlined, FilePdfOutlined, FileZipOutlined, VideoCameraOutlined } from '@ant-design/icons';
import { uploadAttachment, listAttachments, deleteAttachment } from '../api';
import { getErrorMessage } from '../utils/error';
import { formatDateTime } from '../utils/formatDate';

const { Text } = Typography;

interface Attachment {
  id: number;
  fileName: string;
  fileUrl: string;
  fileSize: number;
  fileType: string;
  createdAt: string;
}

interface AttachmentUploadProps {
  defectId: number;
  editable?: boolean;
}



const getFileIcon = (fileType: string) => {
  switch (fileType) {
    case 'image': return <PictureOutlined style={{ fontSize: 20, color: '#4f46e5' }} />;
    case 'video': return <VideoCameraOutlined style={{ fontSize: 20, color: '#0ea5e9' }} />;
    case 'pdf': return <FilePdfOutlined style={{ fontSize: 20, color: '#ef4444' }} />;
    case 'document': return <FileTextOutlined style={{ fontSize: 20, color: '#3b82f6' }} />;
    case 'archive': return <FileZipOutlined style={{ fontSize: 20, color: '#f59e0b' }} />;
    default: return <FileOutlined style={{ fontSize: 20, color: '#6b7280' }} />;
  }
};

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
};

const API_BASE = '/api/v1';
const getImageUrl = (url: string) => {
  if (/^https?:\/\//i.test(url)) return url;
  return API_BASE + url;
};

export default function AttachmentUpload({ defectId, editable = true }: AttachmentUploadProps) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);


  const loadAttachments = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAttachments(defectId);
      if (res.data) {
        setAttachments(res.data);
      }
    } catch (err) {
      logger.error('加载附件失败', err);
      message.error('附件加载失败');
    } finally {
      setLoading(false);
    }
  }, [defectId]);

  useEffect(() => {
    void loadAttachments();
  }, [loadAttachments]);

  const handleUpload = async (file: File) => {
    // 检查文件大小
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
      message.error('文件大小不能超过10MB');
      return false;
    }

    setUploading(true);
    try {
      const res = await uploadAttachment(defectId, file);
      message.success('上传成功');
      void loadAttachments();
    } catch (err: unknown) {
      message.error(getErrorMessage(err, '上传失败'));
    } finally {
      setUploading(false);
    }
    return false; // 阻止默认上传行为
  };

  const handleDelete = async (attachmentId: number) => {
    try {
      const res = await deleteAttachment(defectId, attachmentId);
      message.success('删除成功');
      setAttachments(prev => prev.filter(a => a.id !== attachmentId));
    } catch (err: unknown) {
      message.error(getErrorMessage(err, '删除失败'));
    }
  };

  return (
    <div>
      {editable && (
        <Upload
          beforeUpload={handleUpload}
          showUploadList={false}
          accept=".jpg,.jpeg,.png,.gif,.webp,.mp4,.avi,.mov,.webm,.mkv,.pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.json,.xml,.zip,.tar,.gz,.log"
        >
          <Button icon={<UploadOutlined />} loading={uploading} style={{ marginBottom: 12 }}>
            {uploading ? '上传中...' : '上传附件'}
          </Button>
        </Upload>
      )}

      <List
        loading={loading}
        dataSource={attachments}
        locale={{ emptyText: '暂无附件' }}
        renderItem={(item) => (
          <List.Item
            actions={editable ? [
              <Popconfirm
                key="delete"
                title="确定删除此附件？"
                onConfirm={() => handleDelete(item.id)}
                okText="确定"
                cancelText="取消"
              >
                <Button type="link" danger size="small" icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            ] : []}
          >
            <List.Item.Meta
              avatar={getFileIcon(item.fileType)}
              title={
                item.fileType === 'image' ? (
                  <Space>
                    <Text>{item.fileName}</Text>
                    <Image
                      src={getImageUrl(item.fileUrl)}
                      width={60}
                      height={60}
                      style={{ objectFit: 'cover', borderRadius: 4 }}
                      placeholder
                    />
                  </Space>
                ) : (
                  <a href={getImageUrl(item.fileUrl)} target="_blank" rel="noopener noreferrer">
                    {item.fileName}
                  </a>
                )
              }
              description={
                <Space split={<Text type="secondary">|</Text>}>
                  <Text type="secondary">{formatFileSize(item.fileSize)}</Text>
                  <Text type="secondary">{formatDateTime(item.createdAt)}</Text>
                  {item.fileType !== 'image' && (
                    <a href={getImageUrl(item.fileUrl)} target="_blank" rel="noopener noreferrer">
                      <DownloadOutlined /> 下载
                    </a>
                  )}
                </Space>
              }
            />
          </List.Item>
        )}
      />
    </div>
  );
}
