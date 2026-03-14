class SQSRouterError(Exception):
    """Base class for all sqs-router errors."""


class InvalidMessageBodyError(SQSRouterError):
    """Message body couldn't be parsed as JSON."""

    def __init__(self, body: str) -> None:
        self.body = body
        super().__init__(f"message body is not valid JSON: {body!r}")


class MissingTypeFieldError(SQSRouterError):
    """The routing key field wasn't found in the message."""

    def __init__(self, field: str, message: dict) -> None:
        self.field = field
        self.message = message
        super().__init__(f"missing field {field!r} in message: {message}")


class UnknownMessageTypeError(SQSRouterError):
    """No handler is registered for this message type."""

    def __init__(self, message_type: str) -> None:
        self.message_type = message_type
        super().__init__(f"no handler registered for type: {message_type!r}")


class HandlerError(SQSRouterError):
    """A handler raised an exception while processing a message."""

    def __init__(self, message_type: str, cause: Exception) -> None:
        self.message_type = message_type
        self.cause = cause
        super().__init__(
            f"handler for {message_type!r} raised {type(cause).__name__}: {cause}"
        )
        self.__cause__ = cause
