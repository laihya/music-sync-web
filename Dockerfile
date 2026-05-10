FROM python:3.11-slim

# ========== 使用 deb 源安装 fpcalc ==========
# 注意：Debian 中提供 fpcalc 的包名是 libchromaprint-tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libchromaprint-tools \
    libchromaprint-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -s /bin/bash watcher && chown -R watcher:watcher /app
USER watcher

VOLUME ["/downloads", "/media", "/failed", "/data"]
EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8003/health')" || exit 1

CMD ["python", "-m", "app.main"]