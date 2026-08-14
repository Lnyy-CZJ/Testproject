FROM python:3.12-slim

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