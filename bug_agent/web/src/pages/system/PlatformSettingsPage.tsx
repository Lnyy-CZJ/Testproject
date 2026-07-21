import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Tag } from 'antd';
import { MailOutlined, ReloadOutlined, SendOutlined, SettingOutlined } from '@ant-design/icons';
import { message } from '../../utils/appMessage';
import {
  getPlatformEmailSettings,
  testPlatformEmailSettings,
  updatePlatformEmailSettings,
} from '../../api';
import type { PlatformEmailSettings } from '../../types';
import PageLayout from '../../components/layout/PageLayout';
import PageContent from '../../components/layout/PageContent';
import PageMetricSection from '../../components/layout/PageMetricSection';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';

interface FormValues {
  smtpHost: string;
  smtpPort: number;
  smtpUser?: string;
  smtpPassword?: string;
  smtpFrom: string;
  securityType?: string;
  testRecipient?: string;
}

const PlatformSettingsPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [passwordConfigured, setPasswordConfigured] = useState(false);
  const [settingsPreview, setSettingsPreview] = useState({
    smtpHost: '',
    smtpPort: 587,
    smtpFrom: '',
  });
  const [form] = Form.useForm<FormValues>();


  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getPlatformEmailSettings();
      const data: PlatformEmailSettings = res.data || {
        smtpHost: '',
        smtpPort: 587,
        smtpUser: '',
        smtpFrom: '',
        passwordConfigured: false,
      };
      setPasswordConfigured(Boolean(data.passwordConfigured));
      setSettingsPreview({
        smtpHost: data.smtpHost || '',
        smtpPort: data.smtpPort || 587,
        smtpFrom: data.smtpFrom || '',
      });
      form.setFieldsValue({
        smtpHost: data.smtpHost || '',
        smtpPort: data.smtpPort || 587,
        smtpUser: data.smtpUser || '',
        smtpPassword: '',
        smtpFrom: data.smtpFrom || '',
        securityType: data.securityType || 'tls',
      });
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '获取平台邮件配置失败'));
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    void fetchSettings();
  }, [fetchSettings]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields(['smtpHost', 'smtpPort', 'smtpUser', 'smtpPassword', 'smtpFrom']);
      setSaving(true);
      await updatePlatformEmailSettings({
        smtpHost: values.smtpHost.trim(),
        smtpPort: Number(values.smtpPort || 587),
        smtpUser: values.smtpUser?.trim() || '',
        smtpPassword: values.smtpPassword || '',
        smtpFrom: values.smtpFrom.trim(),
        securityType: values.securityType || 'tls',
      });
      await fetchSettings();
      form.setFieldValue('smtpPassword', '');
      message.success('平台邮件配置已保存');
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) {
        return;
      }
      message.error(getErrorMessage(error, '保存平台邮件配置失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    try {
      const values = await form.validateFields(['smtpHost', 'smtpPort', 'smtpUser', 'smtpPassword', 'smtpFrom', 'testRecipient']);
      setTesting(true);
      await testPlatformEmailSettings({
        smtpHost: values.smtpHost.trim(),
        smtpPort: Number(values.smtpPort || 587),
        smtpUser: values.smtpUser?.trim() || '',
        smtpPassword: values.smtpPassword || '',
        smtpFrom: values.smtpFrom.trim(),
        securityType: values.securityType || 'tls',
        to: String(values.testRecipient || '').trim(),
      });
      message.success('测试邮件发送成功');
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) {
        return;
      }
      message.error(getErrorMessage(error, '测试邮件发送失败'));
    } finally {
      setTesting(false);
    }
  };

  return (
    <PageLayout>
      <PageContent>

      <PageMetricSection
        items={[
          { key: 'host', label: 'SMTP Host', value: settingsPreview.smtpHost || '-', icon: <MailOutlined />, tone: 'purple' },
          { key: 'port', label: 'SMTP Port', value: settingsPreview.smtpPort || 587, icon: <SettingOutlined />, tone: 'cyan' },
          { key: 'sender', label: '发件人', value: settingsPreview.smtpFrom ? '已设置' : '未设置', icon: <SendOutlined />, tone: 'amber' },
          { key: 'password', label: '凭证状态', value: passwordConfigured ? '已配置' : '未配置', icon: <ReloadOutlined />, tone: 'green' },
        ]}
        actions={(
          <Button icon={<ReloadOutlined />} onClick={fetchSettings} loading={loading}>
            刷新
          </Button>
        )}
      />

      <Card className="scene-card">
        <Alert
          type="info"
          showIcon
          title="SMTP 配置保存到数据库后，系统邮件发送将优先使用数据库配置；环境变量仅作为兜底。"
          style={{ marginBottom: 16 }}
        />

        <Form
          form={form}
          layout="vertical"
          initialValues={{ smtpPort: 587 }}
          onValuesChange={(_, allValues) => {
            setSettingsPreview({
              smtpHost: allValues.smtpHost || '',
              smtpPort: allValues.smtpPort || 587,
              smtpFrom: allValues.smtpFrom || '',
            });
          }}
        >
          <Card
            className="utility-card"
            type="inner"
            title={<Space><MailOutlined /> 发件邮箱配置</Space>}
            extra={passwordConfigured ? <Tag color="success">密码已配置</Tag> : <Tag>未配置密码</Tag>}
          >
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
              <Form.Item
                name="smtpHost"
                label="SMTP Host"
                rules={[{ required: true, message: '请输入 SMTP Host' }]}
              >
                <Input placeholder="smtp.example.com" />
              </Form.Item>
              <Form.Item
                name="smtpPort"
                label="SMTP Port"
                rules={[{ required: true, message: '请输入 SMTP 端口' }]}
              >
                <InputNumber min={1} max={65535} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="securityType" label="加密方式" initialValue="tls">
                <Select
                  options={[
                    { value: 'none', label: '无加密' },
                    { value: 'ssl', label: 'SSL/TLS (端口465)' },
                    { value: 'tls', label: 'STARTTLS (端口587)' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="smtpUser" label="SMTP 用户名">
                <Input placeholder="noreply@example.com" />
              </Form.Item>
              <Form.Item
                name="smtpFrom"
                label="发件人"
                rules={[{ required: true, message: '请输入发件人' }]}
                extra="可填写邮箱地址或带名称的发件人，如 BugAgent <noreply@example.com>"
              >
                <Input placeholder="BugAgent <noreply@example.com>" />
              </Form.Item>
            </div>

            <Form.Item
              name="smtpPassword"
              label="SMTP 密码"
              extra={passwordConfigured ? '留空则保留当前密码；填写后将覆盖现有密码。' : '当前未配置密码。'}
            >
              <Input.Password placeholder={passwordConfigured ? '留空则不修改' : '请输入 SMTP 密码'} />
            </Form.Item>

            <Space>
              <Button type="primary" onClick={handleSave} loading={saving}>
                保存配置
              </Button>
            </Space>
          </Card>

          <Card
            className="utility-card"
            type="inner"
            title="测试发送"
            style={{ marginTop: 16 }}
            styles={{ body: { paddingTop: 20 } }}
          >
            <Form.Item
              name="testRecipient"
              label="测试接收邮箱"
              rules={[{ required: true, message: '请输入测试接收邮箱' }]}
            >
              <Input placeholder="receiver@example.com" />
            </Form.Item>
            <Button icon={<SendOutlined />} onClick={handleTest} loading={testing}>
              发送测试邮件
            </Button>
          </Card>
        </Form>
      </Card>
      </PageContent>
    </PageLayout>
  );
};

export default PlatformSettingsPage;
