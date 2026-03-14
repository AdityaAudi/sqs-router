from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# parsed message body
Message = dict[str, Any]

# what handler functions look like
Handler = Callable[["MessageMetadata"], Any]


@dataclass(frozen=True)
class MessageMetadata:
    """SQS record context passed to every handler alongside the message body.

    Attributes:
        message_id: SQS message ID.
        receipt_handle: Use this if you need to manually delete the message.
        queue_name: Extracted from the event source ARN.
        message_type: The type string that was routed on.
        receive_count: How many times this message has been received. A count
            above 3 or so usually means something is consistently failing.
        attributes: Raw SQS system attributes.
        message_attributes: User-defined message attributes.
        body: The original raw body string, in case you need it unparsed.
    """

    message_id: str
    receipt_handle: str
    queue_name: str
    message_type: str
    receive_count: int
    attributes: dict[str, Any]
    message_attributes: dict[str, Any]
    body: str


@dataclass
class DispatchResult:
    """Tracks what happened during a dispatch() call.

    With partial_failure=True, batch_item_failures is populated and returned
    directly to Lambda. With partial_failure=False this struct still tracks
    success/failure counts but isn't returned.
    """

    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    batch_item_failures: list[dict[str, str]] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return bool(self.failed)
