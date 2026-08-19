# 前端构建阶段：使用锁文件确保生产产物可重复构建。
FROM node:24-alpine AS frontend-builder

ARG APP_VERSION=unknown
ARG APP_REVISION=unknown
ARG APP_BUILD_DIRTY=true
ARG APP_RUNTIME_ENV=unknown
ARG APP_CONTENT_SHA256=unknown

WORKDIR /workspace/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY versions.json /workspace/versions.json
COPY frontend/ ./
COPY web/ /workspace/web/
RUN npm run build

# 网关运行阶段：仅保留 Nginx 和静态产物，生产环境不运行 Node.js。
FROM nginx:1.27-alpine

ARG APP_VERSION=unknown
ARG APP_REVISION=unknown
ARG APP_BUILD_DIRTY=true
ARG APP_RUNTIME_ENV=unknown
ARG APP_CONTENT_SHA256=unknown
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$APP_REVISION \
      io.testplatform.source-content-sha256=$APP_CONTENT_SHA256

COPY --from=frontend-builder /workspace/frontend/dist/ /usr/share/nginx/html/
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/tool-unavailable.html /etc/nginx/errors/tool-unavailable.html
RUN printf '{"service":"platform-gateway","status":"ok","version":"%s","revision":"%s","dirty":%s,"runtime_environment":"%s","content_sha256":"%s"}\n' \
    "$APP_VERSION" "$APP_REVISION" "$APP_BUILD_DIRTY" "$APP_RUNTIME_ENV" "$APP_CONTENT_SHA256" \
    > /usr/share/nginx/html/version.json

EXPOSE 80
