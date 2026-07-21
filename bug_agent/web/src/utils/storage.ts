const storage = localStorage;

export const appStorage = {
  getToken: (): string => storage.getItem('token') || '',
  setToken: (token: string) => storage.setItem('token', token),
  removeToken: () => storage.removeItem('token'),

  getUser: <T = Record<string, unknown>>(): T | null => {
    try {
      const raw = storage.getItem('user');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  },
  setUser: (user: unknown) => storage.setItem('user', JSON.stringify(user)),
  removeUser: () => storage.removeItem('user'),

  clear: () => {
    storage.removeItem('token');
    storage.removeItem('user');
    storage.removeItem('lastProjectId');
  },
};
