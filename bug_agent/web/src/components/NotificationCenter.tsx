import { useEffect, useRef, useState, useCallback } from 'react';
import { Badge, Button, Drawer, Empty, Space, Spin, Typography } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { message } from '../utils/appMessage';
import { logger } from '../utils/logger';
import { getErrorMessage } from '../utils/error';
import { formatDateTime } from '../utils/formatDate';
import { useSSEEvent } from '../hooks/useSSE';
import {
  getUnreadNotificationCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationsRead,
} from '../api';
import type { NotificationItem } from '../api';

function parseMetadata(raw?: string) {
  if (!raw || raw === 'null') {
    return {};
  }
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function formatCreatedAt(item: NotificationItem) {
  return formatDateTime(item.createdAt);
}

export default function NotificationCenter() {
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const openRef = useRef(false);
  const [loading, setLoading] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const setOpenState = (value: boolean) => {
    openRef.current = value;
    setOpen(value);
  };


  const fetchUnreadCount = useCallback(async () => {
    try {
      const res = await getUnreadNotificationCount();
      setUnreadCount(Number(res?.data?.count || 0));
    } catch {
      logger.error('获取未读数失败');
      setUnreadCount(0);
    }
  }, []);

  const fetchNotifications = async () => {
    setLoading(true);
    try {
      const res = await listNotifications({ page: 1, pageSize: 20 });
      setNotifications(res?.data?.items || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '获取通知列表失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchUnreadCount();
  }, [fetchUnreadCount]);

  const handleNotification = useCallback(() => {
    void fetchUnreadCount();
    if (openRef.current) {
      void fetchNotifications();
    }
  }, [fetchUnreadCount]);

  useSSEEvent('notification', handleNotification);

  const openDrawer = async () => {
    setOpenState(true);
    await Promise.all([fetchUnreadCount(), fetchNotifications()]);
  };

  const markAsRead = async (id: number) => {
    const target = notifications.find((item) => item.id === id);
    if (!target || target.read) {
      return;
    }

    await markNotificationsRead([id]);
    setNotifications((prev) => prev.map((item) => (
      item.id === id ? { ...item, read: true } : item
    )));
    setUnreadCount((prev) => Math.max(0, prev - 1));
  };

  const handleMarkRead = async (id: number) => {
    try {
      await markAsRead(id);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '标记已读失败'));
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setNotifications((prev) => prev.map((item) => ({ ...item, read: true })));
      setUnreadCount(0);
      message.success('已全部标记为已读');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '全部标记已读失败'));
    }
  };

  const resolveNotificationPath = (item: NotificationItem) => {
    const relatedId = item.relatedId ?? 0;
    const metadata = parseMetadata(item.metadata);
    const metadataProjectId = Number(metadata.project_id) || 0;
    const metadataDefectId = Number(metadata.defect_id) || 0;
    const currentProjectMatch = location.pathname.match(/^\/projects\/(\d+)/);
    const currentProjectId = currentProjectMatch ? Number(currentProjectMatch[1]) : 0;
    const fallbackProjectId = Number(localStorage.getItem('lastProjectId') || 0);
    const projectId = metadataProjectId || currentProjectId || fallbackProjectId;
    const defectId = metadataDefectId || relatedId;

    if ((item.category ?? item.type)?.startsWith('defect_') && projectId > 0 && defectId > 0) {
      return `/projects/${projectId}/defects/${defectId}`;
    }

    return '';
  };

  const handleOpenNotification = async (item: NotificationItem) => {
    try {
      await markAsRead(item.id);
    } catch {
      logger.error('标记已读失败');
    }

    const path = resolveNotificationPath(item);
    if (path) {
      navigate(path);
      setOpenState(false);
    }
  };

  return (
    <>
      <button
        type="button"
        aria-label="通知中心"
        title="通知中心"
        style={{
          position: 'relative',
          padding: 8,
          border: 'none',
          background: 'transparent',
          cursor: 'pointer',
          borderRadius: 8,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        onClick={() => {
          void openDrawer();
        }}
      >
        <span
          style={{
            position: 'absolute',
            width: 1,
            height: 1,
            padding: 0,
            margin: -1,
            overflow: 'hidden',
            clip: 'rect(0, 0, 0, 0)',
            whiteSpace: 'nowrap',
            border: 0,
          }}
        >
          通知中心
        </span>
        <Badge count={unreadCount} size="small" offset={[-2, 2]}>
          <BellOutlined aria-hidden style={{ fontSize: 20, color: '#64748b' }} />
        </Badge>
      </button>

      <Drawer
        title={<h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>消息中心</h2>}
        placement="right"
        size={420}
        open={open}
        onClose={() => setOpenState(false)}
        extra={(
          <Space>
            <Button size="small" onClick={() => void fetchNotifications()}>
              刷新
            </Button>
            <Button size="small" type="primary" ghost onClick={() => void handleMarkAllRead()}>
              全部标记已读
            </Button>
          </Space>
        )}
      >
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
            <Spin />
          </div>
        ) : notifications.length === 0 ? (
          <Empty description="暂无消息" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div role="list" aria-label="通知列表">
            {notifications.map((item) => (
              <div
                key={item.id}
                role="listitem"
                style={{
                  cursor: 'pointer',
                  paddingLeft: 12,
                  paddingRight: 12,
                  borderRadius: 12,
                  marginBottom: 8,
                  background: item.read ? '#fff' : '#f8fafc',
                  border: `1px solid ${item.read ? '#f1f5f9' : '#dbeafe'}`,
                }}
                onClick={() => {
                  void handleOpenNotification(item);
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, width: '100%' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Space>
                      <Typography.Text strong>{item.title}</Typography.Text>
                      {!item.read ? (
                        <span
                          style={{
                            display: 'inline-block',
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: '#ef4444',
                          }}
                        />
                      ) : null}
                    </Space>
                    <Space direction="vertical" size={4} style={{ width: '100%', marginTop: 4 }}>
                      <Typography.Text>{item.content}</Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {formatCreatedAt(item)}
                      </Typography.Text>
                    </Space>
                  </div>

                  {!item.read ? (
                    <Button
                      key={`read-${item.id}`}
                      type="link"
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleMarkRead(item.id);
                      }}
                    >
                      标记已读
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </Drawer>
    </>
  );
}
