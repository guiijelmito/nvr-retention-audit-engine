FROM python:3.12-slim-bookworm

ARG PLAYWRIGHT_VERSION=1.64.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt ./requirements.txt

# Instala a mesma versão do Playwright usada para baixar o Chromium.
RUN python -m pip install --no-cache-dir -r requirements.txt "playwright==${PLAYWRIGHT_VERSION}" \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY main.py ./
COPY nvr_audit_engine ./nvr_audit_engine

CMD ["python", "main.py"]
