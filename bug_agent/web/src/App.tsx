import { Component, useEffect, type ReactNode } from 'react';
import { RouterProvider } from 'react-router-dom';
import { ConfigProvider, App as AntApp, theme, Button, Result, Space } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import router from './router';
import { setMessageInstance } from './utils/appMessage';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面渲染异常"
          subTitle={this.state.error?.message || '发生了未知错误'}
          extra={
            <Space>
              <Button type="primary" onClick={this.handleRetry}>
                重试
              </Button>
              <Button onClick={() => { window.location.href = '/'; }}>
                返回首页
              </Button>
            </Space>
          }
        />
      );
    }
    return this.props.children;
  }
}

function AntdAppBridge() {
  const { message } = AntApp.useApp();

  useEffect(() => {
    setMessageInstance(message);
  }, [message]);

  return null;
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#8b5cf6',
          colorSuccess: '#22c55e',
          colorWarning: '#f59e0b',
          colorError: '#ef4444',
          colorInfo: '#06b6d4',
          colorBgBase: '#f5f7fb',
          colorBgContainer: '#ffffff',
          colorBgElevated: '#ffffff',
          colorBorder: '#dbe4f2',
          colorText: '#0f172a',
          colorTextSecondary: '#475569',
          borderRadius: 16,
          borderRadiusLG: 24,
          borderRadiusSM: 12,
          fontFamily: "'Geist', 'PingFang SC', 'Microsoft YaHei', sans-serif",
          fontSize: 14,
          controlHeight: 42,
          controlHeightLG: 48,
          boxShadowSecondary: '0 18px 40px rgba(15, 23, 42, 0.10)',
        },
        components: {
          Card: {
            borderRadiusLG: 24,
            paddingLG: 24,
            headerFontSize: 16,
            colorBorderSecondary: '#dbe4f2',
          },
          Button: {
            borderRadius: 14,
            controlHeight: 42,
            controlHeightLG: 48,
            fontWeight: 600,
          },
          Table: {
            borderRadius: 24,
            headerBg: '#edf2ff',
            headerColor: '#334155',
            headerSplitColor: '#dbe4f2',
            rowHoverBg: '#f8fbff',
          },
          Input: {
            borderRadius: 14,
            activeBorderColor: '#8b5cf6',
            hoverBorderColor: '#a78bfa',
          },
          InputNumber: {
            borderRadius: 14,
          },
          Select: {
            borderRadius: 14,
          },
          Menu: {
            itemBorderRadius: 14,
            itemMarginInline: 8,
            itemHeight: 44,
            itemColor: '#64748b',
            itemSelectedColor: '#5b21b6',
            itemSelectedBg: 'rgba(139, 92, 246, 0.12)',
          },
          Tag: {
            borderRadiusSM: 999,
            fontWeightStrong: 600,
          },
          Modal: {
            borderRadiusLG: 24,
          },
          Layout: {
            siderBg: '#ffffff',
          },
        },
      }}
    >
      <AntApp>
        <AntdAppBridge />
        <ErrorBoundary>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </AntApp>
    </ConfigProvider>
  );
}
