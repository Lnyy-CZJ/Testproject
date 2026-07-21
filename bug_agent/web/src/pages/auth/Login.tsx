import { useState } from 'react';
import { Form, Input, Button } from 'antd';
import { message } from '../../utils/appMessage';
import { appStorage } from '../../utils/storage';
import { useNavigate, Link as RouterLink } from 'react-router-dom';
import { login } from '../../api';
import { getErrorMessage } from '../../utils/error';

interface LoginValues {
  username: string;
  password: string;
}

export default function Login() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const capabilityCards = [
    {
      title: '缺陷流转工作台',
      description: '把问题识别、AI 结论、修复任务和协作动态组织在同一主舞台。',
    },
    {
      title: '多 Agent 协作',
      description: '产品、前端、后端、测试和 UI Agent 在统一上下文里参与判断。',
    },
    {
      title: '结构化结论',
      description: '摘要、依据、风险和下一步动作分层呈现，而不是堆一屏日志。',
    },
    {
      title: '可执行的修复链路',
      description: '从分析到修复任务、验证建议和分支上下文一键衔接。',
    },
  ];


  const onFinish = async (values: LoginValues) => {
    setLoading(true);
    try {
      const res = await login(values);
      const token = res.data?.token;
      if (!token) {
        message.error('登录响应异常，未获取到有效凭证');
        return;
      }
      appStorage.setToken(token);
      appStorage.setUser(res.data?.user || null);
      message.success('登录成功');
      navigate('/');
    } catch (err: unknown) {
      message.error(getErrorMessage(err, '登录失败'));
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

          <div className="text-[11px] uppercase tracking-[0.24em] text-white/60">Login</div>
          <h2 className="mt-4 text-5xl font-semibold leading-[1.04] tracking-tight">
            让缺陷的识别、分析、修复与验证在同一界面里连续推进。
          </h2>
          <p className="mt-6 max-w-[560px] text-lg leading-8 text-white/78">
            Bug Agent 不是标准后台，而是把问题上下文、AI 结论和行动轨道组织成工作台的质量协作产品。
          </p>

          <div className="mt-10 grid gap-4 md:grid-cols-2">
            {capabilityCards.map((item) => (
              <div key={item.title} className="rounded-[24px] border border-white/12 bg-white/10 p-5 backdrop-blur-sm">
                <div className="text-sm font-semibold text-white">{item.title}</div>
                <div className="mt-2 text-sm leading-7 text-white/72">{item.description}</div>
              </div>
            ))}
          </div>

          <div className="mt-10 flex flex-wrap gap-3">
            <div className="rounded-full border border-white/12 bg-white/10 px-4 py-2 text-sm text-white/84">6 类 Agent 协作角色</div>
            <div className="rounded-full border border-white/12 bg-white/10 px-4 py-2 text-sm text-white/84">Chat-first 缺陷录入</div>
            <div className="rounded-full border border-white/12 bg-white/10 px-4 py-2 text-sm text-white/84">结构化结论与决策侧轨</div>
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
              <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Structured Console</div>
            </div>
          </div>

          <div className="auth-form-panel">
            <div className="text-[11px] uppercase tracking-[0.22em] text-purple-700">Welcome Back</div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">继续你的质量工作流</h2>
            <p className="mt-3 text-[15px] leading-7 text-slate-500">
              登录后直接进入你的平台工作区，继续处理项目、缺陷和 Agent 分析链路。
            </p>

            <Form
              onFinish={onFinish}
              size="large"
              autoComplete="off"
              layout="vertical"
              initialValues={{ username: '', password: '' }}
              className="mt-8"
            >
              <Form.Item
                name="username"
                label="用户名"
                rules={[{ required: true, message: '请输入用户名' }]}
              >
                <Input placeholder="请输入用户名" />
              </Form.Item>
              <Form.Item
                name="password"
                label="密码"
                rules={[{ required: true, message: '请输入密码' }]}
              >
                <Input.Password placeholder="请输入密码" />
              </Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                block
                className="brand-button h-12 font-medium"
              >
                登录
              </Button>
            </Form>

            <div className="mt-6 text-center text-sm text-slate-500">
              还没有账户？
              <RouterLink to="/register" className="text-purple-600 hover:text-purple-700 font-medium ml-1">
                立即注册
              </RouterLink>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
