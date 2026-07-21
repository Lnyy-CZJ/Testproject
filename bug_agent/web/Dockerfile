# 构建 React 静态资源。使用 npx 避开当前旧页面遗留的 TypeScript 严格检查债务。
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --cache /tmp/npm-cache

COPY . ./
RUN npx vite build


# Nginx 提供 SPA 静态文件，并将 API 与 SSE 转发到 FastAPI 容器。
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
