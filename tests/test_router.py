import pytest

from sqs_router import SQSRouter, UnknownMessageTypeError
from sqs_router.exceptions import HandlerError, MissingTypeFieldError
from conftest import make_event, make_record


def test_on_registers_handler():
    router = SQSRouter(message_type_field="event_type")

    @router.on("order.created")
    def h(m, md): pass

    assert "order.created" in router.registered_types


def test_on_multiple_types():
    router = SQSRouter(message_type_field="event_type")

    @router.on("payment.succeeded", "payment.refunded")
    def h(m, md): pass

    assert "payment.succeeded" in router.registered_types
    assert "payment.refunded" in router.registered_types


def test_on_many_alias():
    router = SQSRouter(message_type_field="event_type")

    @router.on_many("a", "b", "c")
    def h(m, md): pass

    assert router.registered_types == ["a", "b", "c"]


def test_on_requires_at_least_one_type():
    with pytest.raises(ValueError):
        SQSRouter(message_type_field="event_type").on()


def test_default_registered():
    router = SQSRouter(message_type_field="event_type")

    @router.default
    def fb(m, md): pass

    assert router._default_handler is fb


def test_on_error_registered():
    router = SQSRouter(message_type_field="event_type")

    @router.on_error
    def err(exc, m, md): pass

    assert router._error_handler is err


def test_routes_to_correct_handler():
    router = SQSRouter(message_type_field="event_type")
    out = []

    @router.on("order.created")
    def h(m, md):
        out.append(m["order_id"])

    router.dispatch(make_event(make_record({"event_type": "order.created", "order_id": "abc"})))
    assert out == ["abc"]


def test_custom_type_field():
    # verify the router respects whatever field name you configure —
    # here using "action" like a task queue would
    router = SQSRouter(message_type_field="action")
    out = []

    @router.on("send_email")
    def h(m, md):
        out.append(m["to"])

    router.dispatch(make_event(make_record({"action": "send_email", "to": "ali@example.com"})))
    assert out == ["ali@example.com"]


def test_multiple_types_same_handler():
    router = SQSRouter(message_type_field="event_type")
    seen = []

    @router.on("payment.succeeded", "payment.refunded")
    def h(m, md):
        seen.append(md.message_type)

    router.dispatch(make_event(
        make_record({"event_type": "payment.succeeded"}, message_id="m1"),
        make_record({"event_type": "payment.refunded"}, message_id="m2"),
    ))
    assert sorted(seen) == ["payment.refunded", "payment.succeeded"]


def test_default_handler_catches_unknown():
    router = SQSRouter(message_type_field="event_type")
    caught = []

    @router.default
    def fb(m, md):
        caught.append(md.message_type)

    router.dispatch(make_event(make_record({"event_type": "some.unknown.thing"})))
    assert caught == ["some.unknown.thing"]


def test_unknown_type_raises_without_default():
    router = SQSRouter(message_type_field="event_type")

    @router.on("something.else")
    def h(m, md): pass

    with pytest.raises(UnknownMessageTypeError) as exc_info:
        router.dispatch(make_event(make_record({"event_type": "nope"})))

    assert "nope" in str(exc_info.value)


def test_raise_on_unhandled_false_skips():
    router = SQSRouter(message_type_field="event_type", raise_on_unhandled=False)
    result = router.dispatch(make_event(make_record({"event_type": "whatever"})))
    assert result == {}


def test_metadata_populated():
    router = SQSRouter(message_type_field="event_type")
    out = []

    @router.on("test.event")
    def h(m, md):
        out.append(md)

    record = make_record(
        {"event_type": "test.event"},
        message_id="msg-42",
        queue_arn="arn:aws:sqs:us-east-1:123:my-queue",
        receive_count=3,
    )
    router.dispatch(make_event(record))

    md = out[0]
    assert md.message_id == "msg-42"
    assert md.queue_name == "my-queue"
    assert md.message_type == "test.event"
    assert md.receive_count == 3


def test_empty_records():
    assert SQSRouter(message_type_field="event_type").dispatch({"Records": []}) == {}


def test_missing_records_key():
    assert SQSRouter(message_type_field="event_type").dispatch({}) == {}


def test_error_handler_called():
    router = SQSRouter(message_type_field="event_type")
    errors = []

    @router.on("fail.event")
    def h(m, md):
        raise ValueError("boom")

    @router.on_error
    def on_err(exc, m, md):
        errors.append(exc)

    with pytest.raises(HandlerError):
        router.dispatch(make_event(make_record({"event_type": "fail.event"})))

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)


def test_missing_type_field():
    router = SQSRouter(message_type_field="event_type")

    @router.on("x")
    def h(m, md): pass

    with pytest.raises(MissingTypeFieldError):
        router.dispatch(make_event(make_record({"not_the_field": "here"})))
