# 接口自动化壳服务镜像。
# 仅包含 Python 运行时与框架 + Web 依赖；不含 Node/npm/Allure CLI。
FROM python:3.12-slim

ARG APP_VERSION=unknown
ARG APP_REVISION=unknown
ARG APP_BUILD_DIRTY=true
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$APP_REVISION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # 容器内必须监听全部网卡，否则端口映射/Nginx 反代不可达；
    # 本地非容器运行不受影响（该默认值只存在于镜像内）。
    API_AUTOTEST_HOST=0.0.0.0 \
    APP_VERSION=${APP_VERSION} \
    APP_REVISION=${APP_REVISION} \
    APP_BUILD_DIRTY=${APP_BUILD_DIRTY}

WORKDIR /app

# 依赖分文件安装：requirements.txt（框架，不动）+ requirements-web.txt（壳服务）。
# 利用独立 COPY 层缓存依赖安装。
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

# 代码与用例资产入库；构建上下文由 .dockerignore 排除凭证与运行时目录，
# 保证镜像内不含 .env 与任何凭证；config/ 与 data/ 保留在镜像内。
COPY . .

EXPOSE 5003

# 独立模式与平台模式统一入口；平台模式下 5003 不映射宿主机，
# 由 Nginx 反代接入 /api-autotest 子路径。
CMD ["python", "-m", "web.app"]
