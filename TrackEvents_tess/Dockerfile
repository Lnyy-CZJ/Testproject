FROM python:3.12-slim

WORKDIR /app

COPY trackevents_core.py trackevents_web.py favicon.svg ./
COPY default.log ./default.log

ENV TRACKEVENTS_HOST=0.0.0.0
ENV TRACKEVENTS_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)" \
  || exit 1

CMD ["python", "trackevents_web.py"]
