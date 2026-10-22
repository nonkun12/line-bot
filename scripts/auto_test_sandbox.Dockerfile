# Minimal, reproducible runtime for untrusted generated regression tests.
# The container is run with --network none, --read-only, and UID/GID 65534.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

WORKDIR /workspace
COPY requirements.txt /tmp/requirements.txt
# Some pinned requirements (notably aiohttp) may need a source build on
# Python versions without a compatible wheel. Install build tools only for
# dependency installation, then remove them from the final sandbox image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt \
    && apt-get purge -y --auto-remove gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/* /tmp/requirements.txt
