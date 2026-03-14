# sqs-router

Decorator-based message routing for Lambda functions that consume SQS.

```python
from sqs_router import SQSRouter

router = SQSRouter(message_type_field="event_type")

@router.on("user_signup")
def handle_signup(message, metadata):
    provision_account(message["user_id"])

def handler(event, context):
    return router.dispatch(event)
```

---

SQS messages are just bytes. There's no built-in concept of message type — SQS doesn't know or care what's in the body. The `message_type_field` is a field *your team* puts in the JSON body. Different teams use `"type"`, `"event_type"`, `"action"`, `"detail-type"` — whatever your producers send, `sqs-router` routes on it.

The pattern it replaces is this, which every SQS Lambda eventually grows into:

```python
def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        t = body.get("event_type")
        if t == "user_signup":
            handle_signup(body)
        elif t == "user_deleted":
            handle_deletion(body)
        elif t == "password_reset":
            handle_reset(body)
        else:
            logger.warning("unknown: %s", t)
```

It works until you have fifteen event types and someone forgets to handle errors properly or implement partial batch failure. `sqs-router` is the standard pattern for this.

## Install

```
pip install sqs-router
```

No dependencies. Python 3.9+.

## Message format

Your producer decides the format. Pick a field name and stick to it.

A common internal microservice convention:

```json
{
  "event_type": "user_signup",
  "user_id": "u-8821",
  "email": "ali@example.com",
  "ts": "2025-03-14T10:00:00Z"
}
```

An EventBridge event forwarded to SQS:

```json
{
  "source": "com.mycompany.auth",
  "detail-type": "UserSignedUp",
  "detail": {
    "user_id": "u-8821",
    "email": "ali@example.com"
  }
}
```

A job/task queue convention:

```json
{
  "action": "send_welcome_email",
  "payload": {
    "user_id": "u-8821",
    "template": "welcome_v2"
  }
}
```

Configure `message_type_field` to match whatever your producers send.

## Quickstart

```python
from sqs_router import SQSRouter

router = SQSRouter(message_type_field="event_type")

@router.on("user_signup")
def handle_signup(message, metadata):
    create_account(message["user_id"])

@router.on("user_deleted")
def handle_deletion(message, metadata):
    deactivate_account(message["user_id"])

def handler(event, context):
    return router.dispatch(event)
```

## Registering handlers

One type:

```python
@router.on("send_email")
def handle(message, metadata):
    send(message["to"], message["template"])
```

Multiple types on one handler:

```python
@router.on("charge.succeeded", "charge.refunded")
def handle_charge(message, metadata):
    # differentiate inside the handler if needed
    if metadata.message_type == "charge.refunded":
        issue_refund(message)
```

`on_many` is an alias for `on` — use whichever reads better when passing many types.

Catch-all for anything without a registered handler:

```python
@router.default
def fallback(message, metadata):
    logger.warning("no handler for %s", metadata.message_type)
```

Without a default, unhandled message types raise `UnknownMessageTypeError`. Pass `raise_on_unhandled=False` to silently skip them instead.

## EventBridge → SQS

EventBridge is one of the most common ways to fan out events to SQS. The `detail-type` field is EventBridge's routing field:

```python
router = SQSRouter(message_type_field="detail-type")

@router.on("UserSignedUp")
def handle(message, metadata):
    detail = message.get("detail", {})
    create_account(detail["user_id"])

@router.on("PasswordResetRequested")
def handle_reset(message, metadata):
    send_reset_email(message["detail"]["email"])
```

## SNS → SQS

When SNS delivers to SQS it wraps the payload in a Notification envelope. The router unwraps it automatically — route on whatever field is in the inner message body.

## metadata

Every handler gets a `MessageMetadata` object as the second argument:

```python
@router.on("send_email")
def handle(message, metadata):
    metadata.message_id       # SQS message ID
    metadata.queue_name       # parsed from the event source ARN
    metadata.message_type     # the routing field value
    metadata.receive_count    # how many times SQS has delivered this message
    metadata.receipt_handle   # if you need to manually ack/delete
    metadata.attributes       # raw SQS system attributes dict
```

`receive_count` is how you detect messages that keep failing:

```python
@router.on("send_email")
def handle(message, metadata):
    if metadata.receive_count > 3:
        # something is persistently wrong — log and let it go to the DLQ
        logger.error(
            "giving up on message %s after %d attempts",
            metadata.message_id,
            metadata.receive_count,
        )
        return
    send(message["to"], message["template"])
```

## Partial batch failure

By default, if one message in a batch of ten fails, Lambda retries all ten — including the nine that already succeeded. The correct behaviour is partial batch failure: tell Lambda exactly which messages failed so only those get retried.

```python
router = SQSRouter(message_type_field="event_type", partial_failure=True)
```

The router catches exceptions per-record, continues processing the rest of the batch, and returns the right response to Lambda:

```json
{"batchItemFailures": [{"itemIdentifier": "failed-message-id"}]}
```

You also need to enable `ReportBatchItemFailures` on the Lambda event source mapping. See the [AWS docs](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html#services-sqs-batchfailurereporting).

## Error hook

```python
@router.on_error
def on_error(exc, message, metadata):
    sentry_sdk.capture_exception(exc)
```

Don't re-raise in the hook — the router handles propagation.

## Custom envelope formats

If your messages have a non-standard structure, pass a callable that receives the raw SQS record dict and returns a parsed message dict:

```python
def unwrap(record):
    # e.g. your producer base64-encodes the body, or nests it differently
    outer = json.loads(record["body"])
    return json.loads(outer["payload"])

router = SQSRouter(message_type_field="event_type", message_extractor=unwrap)
```

## Configuration

```python
SQSRouter(
    message_type_field="event_type",  # required — the field you route on
    raise_on_unhandled=True,          # raise if no handler matches and no default set
    partial_failure=False,            # enable partial batch failure response
    message_extractor=None,           # custom body parser
)
```

There's no default for `message_type_field` that makes sense universally — use the field name your producers actually send.

## Exceptions

```python
from sqs_router import (
    SQSRouterError,           # base class
    InvalidMessageBodyError,  # body isn't valid JSON
    MissingTypeFieldError,    # routing field not found in message
    UnknownMessageTypeError,  # no handler for this type
    HandlerError,             # a handler raised an exception
)
```

## Tests

```bash
pip install -e .
pip install pytest
pytest
```

---

MIT · [Aditya Ganti](https://github.com/AdityaAudi)
