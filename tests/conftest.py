import json


def make_record(
    body: dict | str,
    message_id: str = "msg-001",
    queue_arn: str = "arn:aws:sqs:us-east-1:123456789:test-queue",
    receive_count: int = 1,
) -> dict:
    raw = json.dumps(body) if isinstance(body, dict) else body
    return {
        "messageId": message_id,
        "receiptHandle": "fake-receipt",
        "body": raw,
        "attributes": {
            "ApproximateReceiveCount": str(receive_count),
            "SentTimestamp": "1700000000000",
        },
        "messageAttributes": {},
        "eventSourceARN": queue_arn,
        "eventSource": "aws:sqs",
    }


def make_event(*records) -> dict:
    return {"Records": list(records)}


def make_sns_wrapped_record(inner: dict, message_id: str = "msg-sns") -> dict:
    """Simulate a message delivered via SNS → SQS subscription."""
    envelope = {
        "Type": "Notification",
        "MessageId": "sns-msg-id",
        "TopicArn": "arn:aws:sns:us-east-1:123:my-topic",
        "Message": json.dumps(inner),
    }
    return make_record(envelope, message_id=message_id)
