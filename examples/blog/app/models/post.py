from bingo.db import Model, fields


class Post(Model):
    title = fields.String()
    body = fields.Text()
    published = fields.Boolean(default=False)
    created_at = fields.DateTime(auto_now_add=True)
    updated_at = fields.DateTime(auto_now=True)
