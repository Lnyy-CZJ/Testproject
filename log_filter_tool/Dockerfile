FROM python:3.12-slim

ARG APP_VERSION=unknown
ARG APP_REVISION=unknown
ARG APP_BUILD_DIRTY=true
ARG APP_CONTENT_SHA256=unknown
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$APP_REVISION \
      io.testplatform.source-content-sha256=$APP_CONTENT_SHA256

ENV APP_VERSION=${APP_VERSION} \
    APP_REVISION=${APP_REVISION} \
    APP_BUILD_DIRTY=${APP_BUILD_DIRTY} \
    APP_CONTENT_SHA256=${APP_CONTENT_SHA256}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY people_search_analyzer.py .
COPY people_search_rules.py .
COPY people_search_ai.py .
COPY templates/ templates/
COPY skills/ skills/
COPY log_default.log .

EXPOSE 5001

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5001", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-"]
