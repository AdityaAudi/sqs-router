from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from .exceptions import (
    HandlerError,
    InvalidMessageBodyError,
    MissingTypeFieldError,
    UnknownMessageTypeError,
)
from .types import DispatchResult, Message, MessageMetadata

logger = logging.getLogger(__name__)


class SQSRouter:
    """Decorator-based SQS message router for Lambda functions.

    SQS messages are just bytes — there's no built-in message type concept.
    You pick a field name that your producers write into the JSON body and
    tell the router to route on it. Different teams use "event_type", "action",
    "detail-type" (EventBridge), "topic", etc.

    Args:
        message_type_field: The JSON body field to route on. No default —
            you must pass the field name your producers actually use.
        raise_on_unhandled: Raise UnknownMessageTypeError if no handler
            matches and no default is set. Default: True.
        partial_failure: Return a partial batch failure response instead of
            re-raising on per-record errors. Requires ReportBatchItemFailures
            enabled on the event source mapping. Default: False.
        message_extractor: Custom callable to parse a raw SQS record dict
            into a message dict. Use for non-standard envelope formats.

    Example (internal microservice, field name "event_type")::

        router = SQSRouter(message_type_field="event_type")

        @router.on("user_signup")
        def handle(message, metadata):
            create_account(message["user_id"])

        def handler(event, context):
            return router.dispatch(event)

    Example (EventBridge forwarded to SQS, field name "detail-type")::

        router = SQSRouter(message_type_field="detail-type")

        @router.on("UserSignedUp")
        def handle(message, metadata):
            create_account(message["detail"]["user_id"])
    """

    def __init__(
        self,
        message_type_field: str,
        raise_on_unhandled: bool = True,
        partial_failure: bool = False,
        message_extractor: Optional[Callable[[dict], Message]] = None,
    ) -> None:
        self._message_type_field = message_type_field
        self._raise_on_unhandled = raise_on_unhandled
        self._partial_failure = partial_failure
        self._message_extractor = message_extractor or self._default_extractor
        self._handlers: dict[str, Callable] = {}
        self._default_handler: Optional[Callable] = None
        self._error_handler: Optional[Callable] = None

    def on(self, *event_types: str) -> Callable:
        """Register a handler for one or more message type values.

        The values should match whatever your producers write into the
        message_type_field. If your field is "event_type" and producers
        send "user_signup", register with router.on("user_signup").

        Usage::

            @router.on("user_signup")
            def handle(message, metadata): ...

            @router.on("charge.succeeded", "charge.refunded")
            def handle_charge(message, metadata): ...
        """
        if not event_types:
            raise ValueError("on() requires at least one event type")

        def decorator(func: Callable) -> Callable:
            for t in event_types:
                if t in self._handlers:
                    logger.warning("overwriting existing handler for %r", t)
                self._handlers[t] = func
                logger.debug("registered handler %r → %s", t, func.__name__)
            return func

        return decorator

    # on_many is an alias — some find it clearer when registering a long list
    on_many = on

    def default(self, func: Callable) -> Callable:
        """Fallback handler for any message type without a registered handler."""
        self._default_handler = func
        return func

    def on_error(self, func: Callable) -> Callable:
        """Hook called when a handler raises.

        Receives (exc, message, metadata). Good for sending to Sentry, Datadog,
        etc. Don't re-raise here — the router handles propagation.
        """
        self._error_handler = func
        return func

    def dispatch(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process a Lambda SQS event.

        With partial_failure=False (default), the first handler exception
        bubbles up and Lambda retries the entire batch.

        With partial_failure=True, exceptions are caught per-record and
        the return value is a batchItemFailures response — only failed
        messages get retried. You must also enable ReportBatchItemFailures
        on the event source mapping for this to work correctly.
        """
        records: list[dict] = event.get("Records", [])
        if not records:
            return {}

        result = DispatchResult()

        for record in records:
            message_id = record.get("messageId", "<unknown>")
            try:
                self._process_record(record, result)
            except Exception as exc:
                if self._partial_failure:
                    result.failed.append(message_id)
                    result.batch_item_failures.append({"itemIdentifier": message_id})
                    logger.error("record %s failed: %s", message_id, exc)
                else:
                    raise

        if self._partial_failure:
            return {"batchItemFailures": result.batch_item_failures}

        return {}

    def _process_record(self, record: dict[str, Any], result: DispatchResult) -> None:
        message_id = record.get("messageId", "<unknown>")
        raw_body = record.get("body", "")

        message = self._message_extractor(record)

        message_type = message.get(self._message_type_field)
        if message_type is None:
            raise MissingTypeFieldError(self._message_type_field, message)

        attributes = record.get("attributes", {})
        metadata = MessageMetadata(
            message_id=message_id,
            receipt_handle=record.get("receiptHandle", ""),
            queue_name=_queue_name_from_arn(record.get("eventSourceARN", "")),
            message_type=str(message_type),
            receive_count=int(attributes.get("ApproximateReceiveCount", 1)),
            attributes=attributes,
            message_attributes=record.get("messageAttributes", {}),
            body=raw_body,
        )

        handler = self._handlers.get(str(message_type)) or self._default_handler

        if handler is None:
            if self._raise_on_unhandled:
                raise UnknownMessageTypeError(str(message_type))
            logger.warning(
                "no handler for %r, skipping (message_id=%s)", message_type, message_id
            )
            return

        logger.debug("dispatching %r → %s", message_type, handler.__name__)
        try:
            handler(message, metadata)
            result.succeeded.append(message_id)
        except Exception as exc:
            if self._error_handler is not None:
                self._error_handler(exc, message, metadata)
            raise HandlerError(str(message_type), exc) from exc

    @property
    def registered_types(self) -> list[str]:
        return list(self._handlers.keys())

    def __repr__(self) -> str:
        return (
            f"SQSRouter(field={self._message_type_field!r}, "
            f"handlers={self.registered_types}, "
            f"partial_failure={self._partial_failure})"
        )

    def _default_extractor(self, record: dict[str, Any]) -> Message:
        raw = record.get("body", "")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise InvalidMessageBodyError(raw)

        # SNS → SQS wraps the payload in a Notification envelope.
        # Unwrap it transparently so callers don't have to think about it.
        if isinstance(parsed, dict) and parsed.get("Type") == "Notification":
            inner = parsed.get("Message", "{}")
            try:
                parsed = json.loads(inner)
            except (json.JSONDecodeError, TypeError):
                raise InvalidMessageBodyError(inner)

        return parsed


def _queue_name_from_arn(arn: str) -> str:
    # ARN format: arn:aws:sqs:us-east-1:123456789:queue-name
    return arn.split(":")[-1] if arn else ""
