FROM python:3.11-slim

# Set environment variables for better python behavior
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Create non-privileged user
RUN useradd -u 10001 -m appuser

WORKDIR /app

# Install system dependencies for postgres and clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium && \
    chmod -R 755 /ms-playwright

# Copy project with proper ownership
COPY --chown=appuser:appuser . /app/

# Expose port
EXPOSE 8000

# Switch to non-privileged user
USER appuser

# Gunicorn handled in docker-compose command
CMD ["gunicorn", "RouteFinder.wsgi:application", "--bind", "0.0.0.0:8000"]
