#!/bin/sh
set -eu

superset db upgrade
superset fab create-admin \
  --username admin \
  --firstname Local \
  --lastname Admin \
  --email admin@example.com \
  --password admin || true
superset init
superset load_examples || true
gunicorn \
  --bind 0.0.0.0:8088 \
  --workers 2 \
  --timeout 120 \
  "superset.app:create_app()"
