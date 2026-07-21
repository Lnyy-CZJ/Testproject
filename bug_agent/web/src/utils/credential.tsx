import { Space, Tag } from 'antd';
import type { RepoCredential } from '../types';

export function credentialScopeLabel(scope?: string) {
  return scope === 'platform' ? '平台' : '个人';
}

export function credentialScopeColor(scope?: string) {
  return scope === 'platform' ? 'gold' : 'blue';
}

export function isYunxiaoCredential(credential?: Partial<RepoCredential> | null) {
  return ['yunxiao', 'generic'].includes(String(credential?.provider || '').toLowerCase());
}

export function renderCredentialOptionLabel(credential: Partial<RepoCredential>) {
  return (
    <Space size={6} wrap>
      <span>{credential.name}</span>
      <Tag color={credentialScopeColor(credential.scope)} style={{ marginRight: 0 }}>
        {credentialScopeLabel(credential.scope)}
      </Tag>
      <Tag style={{ marginRight: 0 }}>
        {String(credential.provider || '').toUpperCase()}
      </Tag>
      <span style={{ color: '#64748b' }}>{credential.maskedValue}</span>
    </Space>
  );
}

export function parseCredentialExtraConfig(raw: string | undefined) {
  if (!raw) return { organizationId: '', workspaceId: '', endpoint: '' };
  try {
    const parsed = JSON.parse(raw);
    return {
      organizationId: String(parsed.organizationId || parsed.organization || parsed.workspaceId || '').trim(),
      workspaceId: String(parsed.workspaceId || parsed.spaceId || '').trim(),
      endpoint: String(parsed.endpoint || parsed.apiEndpoint || '').trim(),
    };
  } catch {
    return { organizationId: '', workspaceId: '', endpoint: '' };
  }
}

export function getProjectColor(code: string) {
  const colors = [
    'linear-gradient(135deg, #a855f7, #ec4899)',
    'linear-gradient(135deg, #3b82f6, #06b6d4)',
    'linear-gradient(135deg, #22c55e, #10b981)',
    'linear-gradient(135deg, #f97316, #ef4444)',
    'linear-gradient(135deg, #6366f1, #a855f7)',
    'linear-gradient(135deg, #14b8a6, #22c55e)',
  ];
  const index = (code?.charCodeAt(0) || 0) % colors.length;
  return colors[index];
}
