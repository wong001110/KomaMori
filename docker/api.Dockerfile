FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-jpn \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY apps/api ./apps/api
RUN python -m pip install --no-cache-dir .

RUN mkdir -p /app/data /app/assets
EXPOSE 8000

CMD ["uvicorn", "komamori.main:app", "--host", "0.0.0.0", "--port", "8000"]
