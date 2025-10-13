FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY exporter.py .
COPY state.py .

# Expose metrics port
EXPOSE 9199

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:9199/metrics', timeout=5)"

CMD ["python", "-u", "exporter.py"]