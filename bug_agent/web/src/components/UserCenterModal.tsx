import { useEffect } from 'react';
import { Modal } from 'antd';
import UserCenterContent from './UserCenterContent';
import type { User } from '../types';

interface UserCenterModalProps {
  open: boolean;
  onClose: () => void;
  onUserUpdated?: (user: User) => void;
  forcePasswordChange?: boolean;
}

export default function UserCenterModal({
  open,
  onClose,
  onUserUpdated,
  forcePasswordChange = false,
}: UserCenterModalProps) {
  useEffect(() => {
    if (!open || forcePasswordChange) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [forcePasswordChange, onClose, open]);

  return (
    <Modal
      title="个人中心"
      open={open}
      onCancel={forcePasswordChange ? undefined : onClose}
      footer={null}
      width={960}
      closable={!forcePasswordChange}
      keyboard={!forcePasswordChange}
      mask={{ closable: !forcePasswordChange }}
      destroyOnHidden
    >
      {open ? (
        <UserCenterContent
          mode="modal"
          onUserUpdated={onUserUpdated}
          initialTab={forcePasswordChange ? 'password' : 'basic'}
          restrictToPassword={forcePasswordChange}
          onPasswordChanged={onClose}
        />
      ) : null}
    </Modal>
  );
}
