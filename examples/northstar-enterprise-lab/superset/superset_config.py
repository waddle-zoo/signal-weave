import os
from urllib.parse import quote_plus

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:"
    f"{quote_plus(os.environ['SUPERSET_DB_PASSWORD'])}@superset-db:5432/superset"
)

WTF_CSRF_ENABLED = True
ENABLE_PROXY_FIX = True
TALISMAN_ENABLED = False
SQLALCHEMY_TRACK_MODIFICATIONS = False

CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "northstar_",
    "CACHE_REDIS_URL": "redis://redis:6379/1",
}
DATA_CACHE_CONFIG = CACHE_CONFIG
RESULTS_BACKEND = None

ROW_LIMIT = 50000
SQL_MAX_ROW = 50000
SUPERSET_WEBSERVER_TIMEOUT = 120
