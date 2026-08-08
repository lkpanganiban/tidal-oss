# Tidal hydrodynamic model + web visualisation — all-in-one Docker image
#
# Build:   docker build -t tidal-model -f src/Dockerfile .
# Run:     docker run -p 5000:5000 -v ./output:/output tidal-model
#
# The image includes:
#   1. The Python shallow-water model (src/model/)
#   2. The Flask + MapLibre web service (src/web/)
#
# Default entry point runs the web service under gunicorn (multi-worker).
# Use `docker run --entrypoint python ... -m model.run` to run the model CLI.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OUTPUT_DIR=/output

# libgdal-dev is required by rasterio/fiona; gcc/g++ for any wheels that need
# building on slim images (e.g. netCDF4, scipy).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY src/requirements-model.txt /app/requirements-model.txt
COPY src/web/requirements.txt /app/web/requirements.txt
COPY src/requirements-lock.txt /app/requirements-lock.txt
COPY src/requirements-dev.txt /app/requirements-dev.txt
COPY pyproject.toml /app/pyproject.toml

# Install the pinned lockfile (model + web deps) for reproducible builds.
# Regenerate with: uv pip compile --python-version 3.12 \
#   --output-file src/requirements-lock.txt \
#   src/requirements-model.txt src/web/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements-lock.txt

# Dev/test tooling so `docker run ... -m pytest` works (see README).
RUN pip install --no-cache-dir -r /app/requirements-dev.txt

COPY src/ /app/src/

WORKDIR /app/src

ENV PYTHONPATH=/app/src

RUN mkdir -p /output

HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/metadata')" || exit 1

EXPOSE 5000

# gunicorn serves the WSGI app from web/app.py (`app` object) with 4 workers.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "web.app:app"]
