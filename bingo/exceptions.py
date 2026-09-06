class BingoError(Exception):
    """Base class for errors with an actionable Bingo-level explanation."""


class BingoConventionError(BingoError):
    pass


class BingoRouteError(BingoError):
    pass


class BingoValidationError(BingoError):
    def __init__(self, validator) -> None:
        self.validator = validator
        self.errors = validator.errors
        super().__init__("The submitted data is invalid.")


class BingoDatabaseError(BingoError):
    pass


class BingoNotFoundError(BingoError):
    pass


class BingoViewError(BingoError):
    pass


class BingoJSONViewError(BingoViewError):
    pass
