import json
import pytest

from sqs_router import SQSRouter
from sqs_router.exceptions import HandlerError, InvalidMessageBodyError
from conftest import make_event, make_record, make_sns_wrapped_record


def test_invalid_json_raises():
    router = SQSRouter(message_type_field="event_type")

    @router.on("x")
    def h(m, md): pass

    with pytest.raises(InvalidMessageBodyError) as exc_info:
        router.dispatch(make_event(make_record("not json")))

    assert "not valid JSON" in str(exc_info.value)


def test_invalid_json_preserves_body():
    router = SQSRouter(message_type_field="event_type")

    @router.on("x")
    def h(m, md): pass

    with pytest.raises(InvalidMessageBodyError) as exc_info:
        router.dispatch(make_event(make_record("{broken")))

    assert exc_info.value.body == "{broken"


def test_all_records_in_batch_processed():
    router = SQSRouter(message_type_field="event_type")
    processed = []

    @router.on("tick")
    def h(m, md):
        processed.append(m["n"])

    router.dispatch(make_event(
        make_record({"event_type": "tick", "n": 1}, "m1"),
        make_record({"event_type": "tick", "n": 2}, "m2"),
        make_record({"event_type": "tick", "n": 3}, "m3"),
    ))

    assert sorted(processed) == [1, 2, 3]


def test_without_partial_failure_stops_on_first_error():
    router = SQSRouter(message_type_field="event_type")
    processed = []

    @router.on("tick")
    def h(m, md):
        if m["n"] == 2:
            raise RuntimeError("second one fails")
        processed.append(m["n"])

    with pytest.raises(HandlerError):
        router.dispatch(make_event(
            make_record({"event_type": "tick", "n": 1}, "m1"),
            make_record({"event_type": "tick", "n": 2}, "m2"),
            make_record({"event_type": "tick", "n": 3}, "m3"),
        ))

    # only the first record was processed before the exception
    assert processed == [1]


def test_partial_failure_continues_after_error():
    router = SQSRouter(message_type_field="event_type", partial_failure=True)
    processed = []

    @router.on("tick")
    def h(m, md):
        if m["n"] == 2:
            raise RuntimeError("this one fails")
        processed.append(m["n"])

    result = router.dispatch(make_event(
        make_record({"event_type": "tick", "n": 1}, "m1"),
        make_record({"event_type": "tick", "n": 2}, "m2"),
        make_record({"event_type": "tick", "n": 3}, "m3"),
    ))

    assert sorted(processed) == [1, 3]
    assert result == {"batchItemFailures": [{"itemIdentifier": "m2"}]}


def test_partial_failure_empty_when_all_succeed():
    router = SQSRouter(message_type_field="event_type", partial_failure=True)

    @router.on("ok")
    def h(m, md): pass

    result = router.dispatch(make_event(make_record({"event_type": "ok"})))
    assert result == {"batchItemFailures": []}


def test_partial_failure_reports_multiple_failures():
    router = SQSRouter(message_type_field="event_type", partial_failure=True)

    @router.on("flaky")
    def h(m, md):
        raise RuntimeError("always")

    result = router.dispatch(make_event(
        make_record({"event_type": "flaky"}, "m1"),
        make_record({"event_type": "flaky"}, "m2"),
    ))

    ids = {f["itemIdentifier"] for f in result["batchItemFailures"]}
    assert ids == {"m1", "m2"}


def test_sns_wrapped_message_unwrapped():
    router = SQSRouter(message_type_field="event_type")
    out = []

    @router.on("user_signup")
    def h(m, md):
        out.append(m["user_id"])

    router.dispatch(make_event(
        make_sns_wrapped_record({"event_type": "user_signup", "user_id": "u-8821"})
    ))

    assert out == ["u-8821"]


def test_eventbridge_detail_type_routing():
    # EventBridge events forwarded to SQS use "detail-type" as the routing field
    router = SQSRouter(message_type_field="detail-type")
    out = []

    @router.on("UserSignedUp")
    def h(m, md):
        out.append(m["detail"]["user_id"])

    body = {
        "version": "0",
        "source": "com.mycompany.auth",
        "detail-type": "UserSignedUp",
        "detail": {"user_id": "u-8821"},
    }
    router.dispatch(make_event(make_record(body)))
    assert out == ["u-8821"]


def test_custom_extractor():
    # custom extractor receives the raw SQS record dict and returns
    # the parsed message — useful for non-standard envelope formats
    def extractor(record):
        outer = json.loads(record["body"])
        return json.loads(outer["data"])

    router = SQSRouter(message_type_field="action", message_extractor=extractor)
    out = []

    @router.on("resize_image")
    def h(m, md):
        out.append(m["s3_key"])

    body_str = json.dumps({"data": json.dumps({"action": "resize_image", "s3_key": "uploads/img.jpg"})})
    router.dispatch(make_event(make_record(body_str)))

    assert out == ["uploads/img.jpg"]


def test_successful_dispatch_returns_empty_dict():
    router = SQSRouter(message_type_field="event_type")

    @router.on("ping")
    def h(m, md): pass

    assert router.dispatch(make_event(make_record({"event_type": "ping"}))) == {}
