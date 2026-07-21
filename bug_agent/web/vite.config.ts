import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');

  return {
    plugins: [react()],
    server: {
      port: 5678,
      proxy: {
        '/api': {
          // 本地默认连接 Python FastAPI；需要时可通过 VITE_BACKEND_TARGET 覆盖。
          target: env.VITE_BACKEND_TARGET || 'http://localhost:8765',
          changeOrigin: true,
        },
      },
    },
  };
});
