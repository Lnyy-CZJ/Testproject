import React from 'react';
import { Button, Result } from 'antd';

interface PageLoadStateProps {
  title?: string;
  subTitle: string;
  retryText?: string;
  onRetry?: () => void;
}

const PageLoadState: React.FC<PageLoadStateProps> = ({
  title = '数据加载失败',
  subTitle,
  retryText = '重试',
  onRetry,
}) => (
  <Result
    status="error"
    title={title}
    subTitle={subTitle}
    extra={onRetry ? (
      <Button type="primary" onClick={onRetry}>
        {retryText}
      </Button>
    ) : undefined}
  />
);

export default PageLoadState;
