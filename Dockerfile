FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY skills ./skills

# Bootstrap a patched pip with an independently published hash before registry
# resolution: older pip vendors the affected CA roots even on patched hosts.
RUN pip install --no-cache-dir --upgrade "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70" \
    && pip install --no-cache-dir . \
    && groupadd --gid 10001 signalweave \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin signalweave \
    && mkdir -p /app/data \
    && chown -R signalweave:signalweave /app

USER signalweave

EXPOSE 8000

CMD ["python", "-m", "signalweave.cli", "serve", "--transport", "streamable-http"]
