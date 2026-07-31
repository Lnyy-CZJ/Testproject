import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * 前端构建配置。
 *
 * 功能说明:
 *   使用 React 插件构建单页应用，并在测试环境中启用 jsdom。
 *
 * 返回值:
 *   Vite 开发、生产构建与 Vitest 共用的配置对象。
 */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/trackevents": "http://127.0.0.1:8080",
      "/log-filter": "http://127.0.0.1:8080",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
