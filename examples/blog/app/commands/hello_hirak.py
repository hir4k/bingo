from bingo import BaseCommand


class Command(BaseCommand):
    """A simple command that prints a greeting message."""

    async def handle(self):
        print("Hello, Hirak!")
