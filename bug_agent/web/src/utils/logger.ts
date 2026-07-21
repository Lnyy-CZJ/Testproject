const isDev = import.meta.env.DEV;

export const logger = {
  error: (...args: unknown[]) => {
    if (isDev) console.error('[BugAgent]', ...args);
  },
  warn: (...args: unknown[]) => {
    if (isDev) console.warn('[BugAgent]', ...args);
  },
  info: (...args: unknown[]) => {
    if (isDev) console.log('[BugAgent]', ...args);
  },
};
