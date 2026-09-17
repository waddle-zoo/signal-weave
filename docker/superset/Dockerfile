FROM apache/superset:6.1.0

USER root
RUN /app/.venv/bin/python -m ensurepip --upgrade \
    && /app/.venv/bin/python -m pip install --no-cache-dir psycopg2-binary
USER superset
