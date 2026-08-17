# 单 worker 保证同一服务只有一个持久化队列调度器。
FROM python:3.12-slim

ARG APP_REVISION=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_REVISION=${APP_REVISION}
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --create-home --uid 10001 agent
COPY --chown=agent:agent . .
RUN mkdir -p /app/runtime/functional && chown -R agent:agent /app/runtime/functional
USER agent
EXPOSE 5004
CMD ["gunicorn", "services.functional_agent.app:create_app()", "--bind", "0.0.0.0:5004", "--workers", "1", "--threads", "8", "--access-logfile", "-", "--error-logfile", "-"]
