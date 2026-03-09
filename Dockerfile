FROM python:3.10-slim

LABEL maintainer="mcpdb" \
      description="MCPDB — Natural language database exploration" \
      version="5.4.0"

# System deps for weasyprint (PDF export) and database drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source and config
COPY pyproject.toml LICENSE mcpdb.yaml.example ./
COPY mcpdb/ mcpdb/

# Install package with extras
RUN pip install --no-cache-dir ".[web,cli,tui,sandbox,csv,excel,export,gemini,mysql,postgresql]"

# Experience cache and chart output
RUN mkdir -p /data/experience /data/charts
ENV MCPDB_EXPERIENCE_DIR=/data/experience
ENV MCPDB_CHARTS_DIR=/data/charts

EXPOSE 8080

# Default: web client mode
CMD ["mcpdb", "web", "--port", "8080", "--no-browser"]
