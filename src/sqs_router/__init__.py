"""sqs-router: Flask-style message routing for Lambda SQS consumers.

    from sqs_router import SQSRouter

    router = SQSRouter()

    @router.on("order.created")
    def handle_order(message, metadata):
        print(message["order_id"])

    def handler(event, context):
        return router.dispatch(event)
"""

from .exceptions import (
    HandlerError,
    InvalidMessageBodyError,
    MissingTypeFieldError,
    SQSRouterError,
    UnknownMessageTypeError,
)
from .router import SQSRouter
from .types import DispatchResult, MessageMetadata

__all__ = [
    "SQSRouter",
    "MessageMetadata",
    "DispatchResult",
    "SQSRouterError",
    "InvalidMessageBodyError",
    "MissingTypeFieldError",
    "UnknownMessageTypeError",
    "HandlerError",
]

__version__ = "0.1.0"
