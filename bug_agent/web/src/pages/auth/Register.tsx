import { useEffect, useState } from 'react';
import { Alert, Form, Input, Button, Spin } from 'antd';
import { message } from '../../utils/appMessage';
import { useNavigate, Link as RouterLink, useSearchParams } from 'react-router-dom';
import { acceptInvite, register, validateInvite } from '../../api';
import { getErrorMessage } from '../../utils/error';

interface RegisterFormValues {
  username: string;
  email: string;
  password: string;
  nickname?: string;
}


export default function Register() {
  const [loading, setLoading] = useState(false);
  const [validatingInvite, setValidatingInvite] = useState(false);
  const [inviteValid, setInviteValid] = useState<boolean | null>(null);
  const [inviteMessage, setInviteMessage] = useState('');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const inviteCode = searchParams.get('invite') || '';
  const onboardingCards = [
    {
      title: '项目上下文',
      description: '进入项目即获得统一的项目导航、当前迭代和协作身份。',
    },
    {
      title: '缺陷工作台',
      description: '列表页高效扫描，详情页专注阅读与推进下一步动作。',
    },
    {
      title: 'AI 决策支持',
      description: '摘要、证据、风险和建议动作分层出现，而不是一大段机器文本。',
    },
  ];


  useEffect(() => {
    if (!inviteCode) {
      setInviteValid(null);
      setInviteMessage('');
      return;
    }

    let cancelled = false;
    const run = async () => {
      setValidatingInvite(true);
      try {
        const res = await validateInvite(inviteCode);
        if (cancelled) return;
        setInviteValid(true);
        setInviteMessage('邀请码有效，注册后将自动绑定邀请关系。');
        return;
      } catch (err: unknown) {
        if (cancelled) return;
        setInviteValid(false);
        setInviteMessage(getErrorMessage(err, '邀请码无效或已过期'));
      } finally {
        if (!cancelled) setValidatingInvite(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [inviteCode]);

  const onFinish = async (values: RegisterFormValues) => {
    if (inviteCode && inviteValid !== true) {
      message.error('邀请码无效或已过期');
      return;
    }

    setLoading(true);
    try {
      const res = (inviteCode
        ? await acceptInvite(inviteCode, values)
        : await register(values));
      message.success(inviteCode ? '邀请码注册成功，请登录' : '注册成功，请登录');
      navigate('/login');
    } catch (err: unknown) {
      message.error(getErrorMessage(err, '注册失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-screen">
      <section className="auth-story">
        <div className="auth-story__content">
          <div className="flex items-center gap-4 mb-10">
            <div className="w-16 h-16 rounded-[22px] bg-white/16 flex items-center justify-center backdrop-blur-sm border border-white/10">
              <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.24em] text-white/60">Structured Experimental Console</div>
              <h1 className="text-3xl font-semibold tracking-tight">Bug Agent</h1>
            </div>
          </div>

          <div className="text-[11px] uppercase tracking-[0.24em] text-white/60">Join Workspace</div>
          <h2 className="mt-4 text-5xl font-semibold leading-[1.04] tracking-tight">
            从注册开始，就进入一套为缺陷协作而设计的产品系统。
          </h2>
          <p className="mt-6 max-w-[560px] text-lg leading-8 text-white/78">
            这不是普通后台的账号入口，而是进入项目上下文、工作台骨架和多 Agent 协作链路的开始。
          </p>

          <div className="mt-10 space-y-4">
            {onboardingCards.map((item) => (
              <div key={item.title} className="rounded-[24px] border border-white/12 bg-white/10 p-5 backdrop-blur-sm">
                <div className="text-sm font-semibold text-white">{item.title}</div>
                <div className="mt-2 text-sm leading-7 text-white/72">{item.description}</div>
              </div>
            ))}
          </div>

          <div className="mt-10 flex flex-wrap gap-3">
            <div className="rounded-full border border-white/12 bg-white/10 px-4 py-2 text-sm text-white/84">浅色主界面 + 紫青能量层</div>
            <div className="rounded-full border border-white/12 bg-white/10 px-4 py-2 text-sm text-white/84">Linear 式结构化阅读</div>
            <div className="rounded-full border border-white/12 bg-white/10 px-4 py-2 text-sm text-white/84">Cohere 风格产品气质</div>
          </div>
        </div>
      </section>

      <section className="auth-form-wrap">
        <div className="w-full max-w-[520px]">
          <div className="mobile-brand">
            <div className="w-12 h-12 bg-gradient-to-br from-purple-600 to-cyan-600 rounded-xl flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <div className="text-lg font-semibold text-slate-900">Bug Agent</div>
              <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Join Workspace</div>
            </div>
          </div>

          <div className="auth-form-panel">
            <div className="text-[11px] uppercase tracking-[0.22em] text-purple-700">Create Account</div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">创建你的工作区身份</h2>
            <p className="mt-3 text-[15px] leading-7 text-slate-500">
              完成注册后，你将进入项目、缺陷、Agent 和质量工作台构成的统一产品系统。
            </p>

            <Form
              onFinish={onFinish}
              size="large"
              autoComplete="off"
              layout="vertical"
              className="mt-8"
            >
              {inviteCode && (
                <div className="mb-4">
                  {validatingInvite ? (
                    <div className="flex items-center gap-2 text-slate-500 text-sm">
                      <Spin size="small" />
                      正在验证邀请码...
                    </div>
                  ) : (
                    <Alert
                      type={inviteValid ? 'success' : 'error'}
                      showIcon
                      message={inviteValid ? '邀请码注册' : '邀请码不可用'}
                      description={inviteMessage || '邀请码状态未知'}
                    />
                  )}
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <Form.Item
                  name="nickname"
                  label="姓名"
                >
                  <Input placeholder="您的姓名" />
                </Form.Item>
                <Form.Item
                  name="username"
                  label="用户名"
                  rules={[{ required: true, message: '请输入用户名' }]}
                >
                  <Input placeholder="用户名" />
                </Form.Item>
              </div>
              <Form.Item
                name="email"
                label="邮箱"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '请输入有效的邮箱地址' },
                ]}
              >
                <Input placeholder="your@email.com" />
              </Form.Item>
              <Form.Item
                name="password"
                label="密码"
                rules={[
                  { required: true, message: '请输入密码' },
                  { min: 8, message: '密码至少8位' },
                ]}
              >
                <Input.Password placeholder="至少8位字符" />
              </Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading || validatingInvite}
                disabled={!!inviteCode && inviteValid !== true}
                block
                className="brand-button h-12 font-medium mt-2"
              >
                注册
              </Button>
            </Form>

            <div className="mt-6 text-center text-sm text-slate-500">
              已有账户？
              <RouterLink to="/login" className="text-purple-600 hover:text-purple-700 font-medium ml-1">
                立即登录
              </RouterLink>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
