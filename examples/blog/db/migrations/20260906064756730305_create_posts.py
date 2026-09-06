from bingo.db import Migration


class CreatePosts(Migration):
    def change(self):
        self.create_table(
            "posts",
            lambda t: [
                t.id(),
                t.string("title"),
                t.text("body"),
                t.boolean("published"),
                t.timestamps(),
            ],
        )
