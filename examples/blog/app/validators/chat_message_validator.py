from bingo.validation import Validator, rules


class ChatMessageValidator(Validator):
    name = rules.String(required=True, max_length=40)
    body = rules.String(required=True, max_length=500)
