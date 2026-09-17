import os

SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
    f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}/{os.environ['DATABASE_DB']}"
)
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
CELERY_CONFIG = {
    "broker_url": f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
    "result_backend": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
}
FEATURE_FLAGS = {
    "ALERT_REPORTS": True,
    "ALERT_REPORT_WEBHOOK": True,
}
SQLALCHEMY_TRACK_MODIFICATIONS = False
