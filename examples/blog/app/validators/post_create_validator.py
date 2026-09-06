from bingo.validation import Validator, rules


class PostCreateValidator(Validator):
    title = rules.String(required=True)
    body = rules.Text(required=True)
    published = rules.Boolean(required=True)
