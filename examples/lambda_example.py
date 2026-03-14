"""
Three realistic Lambda examples showing how sqs-router works with
different message conventions teams actually use in production.
"""

# -----------------------------------------------------------------------
# Example 1: Internal microservice queue
#
# Your team controls both producer and consumer. You've settled on
# "event_type" as the routing field. Messages look like:
#
#   {
#     "event_type": "user_signup",
#     "user_id": "u-8821",
#     "email": "ali@example.com",
#     "ts": "2025-03-14T10:00:00Z"
#   }
# -----------------------------------------------------------------------

import logging

from sqs_router import SQSRouter
from sqs_router.types import MessageMetadata

logger = logging.getLogger(__name__)

router = SQSRouter(message_type_field="event_type", partial_failure=True)


@router.on("user_signup")
def handle_signup(message: dict, metadata: MessageMetadata) -> None:
    logger.info("new signup: %s", message["user_id"])
    # db.create_account(message["user_id"], message["email"])


@router.on("user_deleted")
def handle_deletion(message: dict, metadata: MessageMetadata) -> None:
    logger.info("deleting user: %s", message["user_id"])
    # db.deactivate(message["user_id"])


@router.on("password_reset_requested")
def handle_reset(message: dict, metadata: MessageMetadata) -> None:
    if metadata.receive_count > 3:
        # something is consistently wrong with this message
        # let it go to the DLQ rather than retrying forever
        logger.error(
            "giving up on password reset for %s after %d attempts",
            message.get("user_id"),
            metadata.receive_count,
        )
        return
    # email.send_reset(message["email"])


@router.default
def handle_unknown(message: dict, metadata: MessageMetadata) -> None:
    # don't fail the batch just because we got an unrecognised event type
    logger.warning("no handler for %r (id=%s)", metadata.message_type, metadata.message_id)


@router.on_error
def on_error(exc: Exception, message: dict, metadata: MessageMetadata) -> None:
    logger.error("handler failed for %r: %s", metadata.message_type, exc, exc_info=True)
    # sentry_sdk.capture_exception(exc)


def handler(event: dict, context) -> dict:
    return router.dispatch(event)


# -----------------------------------------------------------------------
# Example 2: EventBridge → SQS
#
# EventBridge uses "detail-type" as its routing field and nests the
# actual payload inside "detail". Messages look like:
#
#   {
#     "version": "0",
#     "source": "com.mycompany.auth",
#     "detail-type": "UserSignedUp",
#     "detail": {
#       "user_id": "u-8821",
#       "email": "ali@example.com"
#     }
#   }
# -----------------------------------------------------------------------

eb_router = SQSRouter(message_type_field="detail-type", partial_failure=True)


@eb_router.on("UserSignedUp")
def handle_eb_signup(message: dict, metadata: MessageMetadata) -> None:
    detail = message.get("detail", {})
    logger.info("EventBridge signup: %s", detail["user_id"])


@eb_router.on("PasswordResetRequested")
def handle_eb_reset(message: dict, metadata: MessageMetadata) -> None:
    detail = message.get("detail", {})
    # email.send_reset(detail["email"])


def eb_handler(event: dict, context) -> dict:
    return eb_router.dispatch(event)


# -----------------------------------------------------------------------
# Example 3: Task / worker queue
#
# A queue where producers enqueue jobs to be processed asynchronously.
# The "action" field says what work to do. Messages look like:
#
#   {
#     "action": "send_welcome_email",
#     "payload": {
#       "user_id": "u-8821",
#       "template": "welcome_v2"
#     }
#   }
# -----------------------------------------------------------------------

task_router = SQSRouter(message_type_field="action", partial_failure=True)


@task_router.on("send_welcome_email")
def send_welcome(message: dict, metadata: MessageMetadata) -> None:
    p = message["payload"]
    logger.info("sending %s to user %s", p["template"], p["user_id"])
    # email.send(p["user_id"], p["template"])


@task_router.on("generate_report", "regenerate_report")
def generate_report(message: dict, metadata: MessageMetadata) -> None:
    p = message["payload"]
    logger.info("generating report %s for %s", p["report_type"], p["user_id"])
    # reports.generate(p["report_type"], p["user_id"])


@task_router.on("resize_image")
def resize_image(message: dict, metadata: MessageMetadata) -> None:
    p = message["payload"]
    # images.resize(p["s3_key"], p["width"], p["height"])


def task_handler(event: dict, context) -> dict:
    return task_router.dispatch(event)
