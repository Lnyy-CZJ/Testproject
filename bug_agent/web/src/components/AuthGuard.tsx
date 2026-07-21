import { useEffect, useMemo } from 'react';
import { Navigate } from 'react-router-dom';
import { appStorage } from '../utils/storage';
import { sseManager } from '../hooks/sseManager';

function validateToken(token: string | null) {
  if (!token) {
    return false;
  }

  try {
    const parts = token.split('.');
    if (parts.length !== 3) {
      appStorage.clear();
      return false;
    }
    const payload = JSON.parse(decodeURIComponent(escape(atob(parts[1]))));
    const exp = Number(payload.exp);
    if (!Number.isFinite(exp) || exp <= 0 || exp * 1000 < Date.now()) {
      appStorage.clear();
      return false;
    }
    return true;
  } catch {
    appStorage.clear();
    return false;
  }
}

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const token = appStorage.getToken();
  const isAuthorized = useMemo(() => validateToken(token), [token]);

  useEffect(() => {
    if (isAuthorized && token) {
      sseManager.connect(token, []);
    } else {
      sseManager.disconnect();
    }
  }, [isAuthorized, token]);

  if (!isAuthorized) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
