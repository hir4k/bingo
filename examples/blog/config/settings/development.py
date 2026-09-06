import os

DEBUG = True
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///db/development.sqlite3",
)
TASK_QUEUE_URL = os.getenv(
    "TASK_QUEUE_URL",
    "postgres://postgres@localhost/blog_tasks",
)
CHANNEL_URL = os.getenv("CHANNEL_URL", TASK_QUEUE_URL)
SERVER_RELOAD = True
PUBLIC_CACHE_SECONDS = 0
