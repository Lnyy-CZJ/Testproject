import { useRef } from 'react';
import { Tag, Button, Empty, Avatar, Collapse, Timeline, Input } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import type { Comment, User } from '../../../types';
import { buildCommentPreview } from '../utils';
import MarkdownContent from '../../../components/MarkdownContent';
import '../defect-detail.css';
import dayjs from 'dayjs';

const { TextArea } = Input;

interface DefectCommentSectionProps {
  recentComments: Comment[];
  archivedComments: Comment[];
  commentText: string;
  onCommentTextChange: (value: string) => void;
  onSubmitComment: () => void;
}

function renderCommentItem(comment: Comment, keyPrefix: string) {
  const isSystemMessage = comment.isAgentMessage || comment.user?.nickname === '系统' || comment.user?.username === '系统';
  const preview = buildCommentPreview(comment.content);
  return {
    color: isSystemMessage ? 'purple' : 'blue',
    content: (
      <div className="pb-2">
        <div className="flex items-center gap-2 mb-1">
          <Avatar size={22} className={isSystemMessage ? 'avatar-system' : 'avatar-brand'}>
            {comment.user?.nickname?.[0] || comment.user?.username?.[0] || 'U'}
          </Avatar>
          <span className="text-sm font-medium text-slate-800">
            {comment.user?.nickname || comment.user?.username}
          </span>
          {isSystemMessage ? <Tag color="purple" className="tag-system">系统</Tag> : null}
          <span className="text-xs text-slate-400">{dayjs(comment.createdAt).format('MM-DD HH:mm')}</span>
        </div>
        <div className="text-sm text-slate-600 leading-6 pl-8">{preview}</div>
        {(comment.content.length > 160 || isSystemMessage) ? (
          <div className="pl-8">
            <Collapse
              ghost
              items={[{
                key: `${keyPrefix}-${comment.id}`,
                label: '查看完整内容',
                children: <MarkdownContent content={comment.content} />,
              }]}
            />
          </div>
        ) : null}
      </div>
    ),
  };
}

export default function DefectCommentSection({
  recentComments,
  archivedComments,
  commentText,
  onCommentTextChange,
  onSubmitComment,
}: DefectCommentSectionProps) {
  const commentEndRef = useRef<HTMLDivElement>(null);

  return (
    <div className="tab-content">
      {recentComments.length ? (
        <Timeline
          items={recentComments.map((comment) => renderCommentItem(comment, 'comment'))}
        />
      ) : (
        <Empty description="暂无评论或系统动态" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}

      {archivedComments.length ? (
        <Collapse
          ghost
          items={[{
            key: 'older-comments',
            label: `更早动态（${archivedComments.length}）`,
            children: (
              <Timeline
                items={archivedComments.map((comment) => renderCommentItem(comment, 'older-comment'))}
              />
            ),
          }]}
        />
      ) : null}

      <div className="flex gap-2 border-t border-slate-100 pt-4 mt-4">
        <TextArea
          value={commentText}
          onChange={(e) => onCommentTextChange(e.target.value)}
          placeholder="输入评论，@ 提及他人，@AGENT 请求重新分析…"
          autoSize={{ minRows: 2, maxRows: 5 }}
          className="comment-textarea"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={onSubmitComment}
          className="brand-button comment-send-btn"
        >
          发送
        </Button>
      </div>
      <div ref={commentEndRef} />
    </div>
  );
}
