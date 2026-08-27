# EleGuard AI - Dockerfile for Railway
FROM python:3.13-slim

# Install Node.js and npm
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy Python requirements
COPY backend/requirements.txt ./backend/requirements.txt
COPY requirements.txt ./requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r backend/requirements.txt && pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

# Copy frontend and build
COPY frontend ./frontend
WORKDIR /app/frontend
RUN npm ci && npm run build

# Go back to app root
WORKDIR /app

# Copy backend code
COPY backend ./backend
COPY ai ./ai
COPY iot ./iot

# Create database directory
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Start command
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]