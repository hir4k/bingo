from pathlib import Path

from bingo import Application
from config.database import DATABASE_URL
from config.routes import routes


class BlogApplication(Application):
    debug = True


ROOT = Path(__file__).resolve().parent.parent
app = BlogApplication(
    routes,
    root_path=ROOT,
    database_url=DATABASE_URL,
)
