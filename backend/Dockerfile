# syntax=docker/dockerfile:1
#
# Pinpoint API image.
#
# The image is host-agnostic: it runs on Fly.io, any container host, a VPS, or
# a local machine. It does not depend on a platform's Python build system,
# so there is no build-time pip resolution to go wrong.
#
#   docker build -t pinpoint-api ./backend
#   docker run -p 8000:8000 --env-file .env -v pinpoint-models:/app/models pinpoint-api
#
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/models \
    HUGGINGFACE_HUB_CACHE=/app/models/hub

WORKDIR /app

COPY requirements.txt requirements-local.txt ./

# torch and torchvision must come from the same index and build, or the
# torchvision C extension fails to load with
# "operator torchvision::nms does not exist". The CPU-only index keeps
# roughly 2 GB of CUDA libraries out of the image.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision

RUN pip install -r requirements.txt

# The offline GeoCLIP tier. Build with
# --build-arg INSTALL_LOCAL_MODEL=0 for a small image for hosts that cannot
# spare the RAM or the disk; the API then simply skips the local tier.
ARG INSTALL_LOCAL_MODEL=1
RUN if [ "$INSTALL_LOCAL_MODEL" = "1" ]; then pip install -r requirements-local.txt; fi

COPY . .

RUN useradd --create-home --uid 10001 pinpoint \
    && mkdir -p /app/models \
    && chown -R pinpoint:pinpoint /app
USER pinpoint

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# One worker on purpose: the local model is a per-process singleton, so a
# second worker would load its own copy of the weights.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
