# Tidal hydrodynamic model + web visualisation — all-in-one Docker image
#
# Build:   docker build -t tidal-model -f src/Dockerfile .
# Run:     docker run -p 5000:5000 -v ./output:/output tidal-model
#
# The image includes:
#   1. The Python shallow-water model (src/model/)
#   2. The Flask + MapLibre web service (src/web/)
#
# Default entry point runs the web service.
# Use --entrypoint to run the model CLI instead.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OUTPUT_DIR=/output

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY src/web/requirements.txt /app/web/requirements.txt

RUN pip install --no-cache-dir -r /app/web/requirements.txt

RUN pip install --no-cache-dir \
    scipy>=1.10 \
    xarray>=2023 \
    pyyaml>=6.0

COPY src/ /app/src/

WORKDIR /app/src

ENV PYTHONPATH=/app/src:$PYTHONPATH

RUN mkdir -p /output

HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/metadata')" || exit 1

EXPOSE 5000

ENTRYPOINT ["python", "-m", "web.app"]
CMD ["--host", "0.0.0.0", "--port", "5000"]
