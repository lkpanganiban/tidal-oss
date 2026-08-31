# Tidal web visualisation — Docker image
#
# Build:   docker build -t tidal-model -f src/Dockerfile .
# Run:     docker run -p 5000:5000 -v ./output:/output tidal-model
#
# Serves the Flask + MapLibre web app (src/web/) with final outputs in /output.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OUTPUT_DIR=/output

# libgdal-dev is required by rasterio; gcc/g++ for wheels (netCDF4)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY src/web/requirements.txt /app/web-requirements.txt
COPY src/requirements-lock.txt /app/requirements-lock.txt
COPY pyproject.toml /app/pyproject.toml

# Install pinned lockfile for reproducible builds.
RUN pip install --no-cache-dir -r /app/requirements-lock.txt

COPY src/web/ /app/src/web/

WORKDIR /app/src

ENV PYTHONPATH=/app/src

RUN mkdir -p /output

HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/metadata')" || exit 1

EXPOSE 5000

# gunicorn serves the WSGI app from web/app.py (`app` object) with 4 workers.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "web.app:app"]
