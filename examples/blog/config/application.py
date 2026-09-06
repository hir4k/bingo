from pathlib import Path

from bingo import Application
from config.routes import routes


class BlogApplication(Application):
    pass


ROOT = Path(__file__).resolve().parent.parent
app = BlogApplication(
    routes,
    root_path=ROOT,
)
