# Backend Dockerfile for development
# Uses Python 3.12 slim for compatibility with many binary wheels (cp312)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps required for some Python packages (compile-time deps trimmed)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker layer caching
COPY requirements.txt ./

# Upgrade pip and install requirements
RUN python -m pip install --upgrade pip wheel setuptools \
    && python -m pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . /app

# Expose default dev port
EXPOSE 8000

# Default command (development-friendly: reload enabled)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
