FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NIGHTSHIFT_RUNTIME_ROOT=/app/runtime

WORKDIR /app

RUN groupadd --system --gid 10001 nightshift \
    && useradd --system --uid 10001 --gid nightshift --home-dir /app --shell /usr/sbin/nologin nightshift

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

COPY backend ./backend

RUN mkdir -p /app/runtime/commit_data /app/runtime/analysis_data /app/runtime/reports /app/runtime/sqlite_data \
    && chown -R nightshift:nightshift /app/runtime

USER nightshift

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read()" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
