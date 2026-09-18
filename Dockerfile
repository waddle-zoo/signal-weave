FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && groupadd --gid 10001 signalweave \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin signalweave \
    && mkdir -p /app/data \
    && chown -R signalweave:signalweave /app

USER signalweave

EXPOSE 8000

CMD ["python", "-m", "signalweave.cli", "serve", "--transport", "streamable-http"]
