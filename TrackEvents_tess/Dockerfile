FROM python:3.12-slim

ARG APP_VERSION=unknown
ARG APP_REVISION=unknown
ARG APP_BUILD_DIRTY=true
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$APP_REVISION

WORKDIR /app

COPY trackevents_core.py trackevents_web.py favicon.svg ./
COPY default.log ./default.log

ENV TRACKEVENTS_HOST=0.0.0.0 \
    TRACKEVENTS_PORT=8000 \
    APP_VERSION=${APP_VERSION} \
    APP_REVISION=${APP_REVISION} \
    APP_BUILD_DIRTY=${APP_BUILD_DIRTY}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)" \
  || exit 1

CMD ["python", "trackevents_web.py"]
