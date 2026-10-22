# Minimal, reproducible runtime for untrusted generated regression tests.
# The container is run with --network none, --read-only, and UID/GID 65534.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

WORKDIR /workspace
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt
