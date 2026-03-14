import json
import boto3
from sqs_router import SQSRouter

# point boto3 at LocalStack
sqs = boto3.client(
    "sqs",
    endpoint_url="http://localhost:4566",
    region_name="us-east-1",
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

QUEUE_URL = "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/user-events"

# --- your router ---

router = SQSRouter(message_type_field="event_type", partial_failure=True)

@router.on("user_signup")
def handle_signup(message, metadata):
    if message["user_id"] == "bad-user":
        raise ValueError("this one fails on purpose")
    print(f"  processed: {message['user_id']}")


@router.on("password_reset_requested")
def handle_reset(message, metadata):
    print(f"  [password_reset] email={message['email']}")

@router.default
def fallback(message, metadata):
    print(f"  [unhandled] type={metadata.message_type}")

@router.on_error
def on_error(exc, message, metadata):
    print(f"  [error] {metadata.message_type} failed: {exc}")


# --- poll and dispatch (simulates what Lambda does) ---

def poll_and_dispatch():
    print("polling queue...")
    resp = sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=1,
    )

    messages = resp.get("Messages", [])
    if not messages:
        print("  no messages")
        return

    # build a fake Lambda SQS event from the raw SQS messages
    event = {
        "Records": [
            {
                "messageId": m["MessageId"],
                "receiptHandle": m["ReceiptHandle"],
                "body": m["Body"],
                "attributes": {
                    "ApproximateReceiveCount": "1",
                    "SentTimestamp": "1700000000000",
                },
                "messageAttributes": {},
                "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:user-events",
                "eventSource": "aws:sqs",
            }
            for m in messages
        ]
    }

    print(f"dispatching {len(messages)} message(s)...")
    router.dispatch(event)

    # delete successfully processed messages
    for m in messages:
        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=m["ReceiptHandle"])
    print("done")


if __name__ == "__main__":
    poll_and_dispatch()