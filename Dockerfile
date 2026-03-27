FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Tesseract
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose placeholder (Railway uses $PORT anyway)
EXPOSE 8000

# ✅ CORRECT: Use shell form CMD so ${PORT} works on Railway
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
