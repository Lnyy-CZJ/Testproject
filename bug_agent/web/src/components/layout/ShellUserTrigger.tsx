import { Avatar } from 'antd';
import { forwardRef, type ReactNode } from 'react';

interface ShellUserTriggerProps {
  name: ReactNode;
  role: ReactNode;
  initial: string;
  onClick?: () => void;
}

const ShellUserTrigger = forwardRef<HTMLDivElement, ShellUserTriggerProps>(
  function ShellUserTrigger({ name, role, initial, onClick }, ref) {
    return (
      <div ref={ref} role="button" tabIndex={0} aria-label="用户菜单" className="shell-user-trigger" onClick={onClick}>
        <Avatar
          size={34}
          aria-hidden
          style={{ background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)' }}
        >
          {initial}
        </Avatar>
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{name}</div>
          <div style={{ fontSize: 11, color: '#94a3b8' }}>{role}</div>
        </div>
      </div>
    );
  },
);

export default ShellUserTrigger;
