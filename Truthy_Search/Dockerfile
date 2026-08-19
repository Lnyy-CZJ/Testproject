FROM python:3.12-slim

ARG APP_VERSION=unknown
ARG APP_REVISION=unknown
ARG APP_BUILD_DIRTY=true
ARG APP_CONTENT_SHA256=unknown
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$APP_REVISION \
      io.testplatform.source-content-sha256=$APP_CONTENT_SHA256

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_VERSION=${APP_VERSION} \
    APP_REVISION=${APP_REVISION} \
    APP_BUILD_DIRTY=${APP_BUILD_DIRTY} \
    APP_CONTENT_SHA256=${APP_CONTENT_SHA256}

WORKDIR /app

# 先安装稳定依赖层，业务代码变化时不重复下载依赖。
COPY requirements.txt ./
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# 只复制 Web 运行必需文件；.env、Raw、数据库和报告由 Compose 挂载。
COPY analysis_service.py analysis_store.py search_tool.py web_app.py ./
COPY result_to_excel.py result_to_excel_builder.mjs ./
COPY templates ./templates
COPY static ./static

EXPOSE 5002

# 配置文件只读挂载到 /run/secrets，不写入镜像。
CMD ["python3", "web_app.py", "--env-file", "/run/secrets/searchtool.env", "--host", "0.0.0.0", "--port", "5002"]
