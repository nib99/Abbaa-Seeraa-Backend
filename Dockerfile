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

# Expose a placeholder (Railway ignores this and uses $PORT)
EXPOSE 8000

# IMPORTANT: Use shell form so ${PORT} expands correctly
# Railway injects the PORT variable dynamically
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
