# 前端构建阶段：使用锁文件确保生产产物可重复构建。
FROM node:24-alpine AS frontend-builder

WORKDIR /workspace/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
COPY web/ /workspace/web/
RUN npm run build

# 网关运行阶段：仅保留 Nginx 和静态产物，生产环境不运行 Node.js。
FROM nginx:1.27-alpine

COPY --from=frontend-builder /workspace/frontend/dist/ /usr/share/nginx/html/
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/tool-unavailable.html /etc/nginx/errors/tool-unavailable.html

EXPOSE 80
