import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { appStorage } from '../../utils/storage';
import type { User } from '../../types';

const menuStyles = `
  .user-menu-item {
    padding: 9px 14px;
    cursor: pointer;
    border-radius: 8px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 14px;
    transition: background 0.15s;
  }
  .user-menu-item--profile {
    color: #334155;
  }
  .user-menu-item--profile:hover {
    background: #f1f5f9;
  }
  .user-menu-item--logout {
    color: #ef4444;
  }
  .user-menu-item--logout:hover {
    background: #fef2f2;
  }
`;

export function useUserState() {
  const navigate = useNavigate();
  const [user, setUser] = useState<Partial<User>>(() => appStorage.getUser<Partial<User>>() || {});
  const [profileOpen, setProfileOpen] = useState(false);
  const forcePasswordChange = Boolean(user?.mustChangePassword);
  const isProfileOpen = profileOpen || forcePasswordChange;

  useEffect(() => {
    const handleUserUpdated = () => {
      setUser(appStorage.getUser<Partial<User>>() || {});
    };
    window.addEventListener('user-profile-updated', handleUserUpdated);
    return () => window.removeEventListener('user-profile-updated', handleUserUpdated);
  }, []);

  const handleLogout = () => {
    appStorage.clear();
    navigate('/login');
  };

  return { user, setUser, profileOpen, setProfileOpen, forcePasswordChange, isProfileOpen, handleLogout };
}

interface UserMenuDropdownProps {
  open: boolean;
  onClose: () => void;
  onProfile: () => void;
  onLogout: () => void;
}

export default function UserMenuDropdown({ open, onClose, onProfile, onLogout }: UserMenuDropdownProps) {
  if (!open) return null;

  return (
    <>
      <style>{menuStyles}</style>
      <div style={{ position: 'fixed', inset: 0, zIndex: 1099 }} onClick={onClose} />
      <div
        style={{
          position: 'absolute',
          right: 0,
          top: '100%',
          marginTop: 8,
          minWidth: 160,
          background: '#fff',
          borderRadius: 12,
          boxShadow: '0 6px 24px rgba(0,0,0,0.1), 0 2px 6px rgba(0,0,0,0.06)',
          border: '1px solid #f1f5f9',
          zIndex: 1100,
          padding: '6px 4px',
        }}
      >
        <div
          className="user-menu-item user-menu-item--profile"
          onClick={() => { onClose(); onProfile(); }}
        >
          <UserOutlined style={{ fontSize: 15 }} />
          个人信息
        </div>
        <div style={{ borderTop: '1px solid #f1f5f9', margin: '4px 8px' }} />
        <div
          className="user-menu-item user-menu-item--logout"
          onClick={() => { onClose(); onLogout(); }}
        >
          <LogoutOutlined style={{ fontSize: 15 }} />
          退出登录
        </div>
      </div>
    </>
  );
}
