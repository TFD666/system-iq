FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy requirements first so the pip install layer is cached unless they change.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY samples samples

RUN chown -R app:app /app
USER app

WORKDIR /app/backend
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
