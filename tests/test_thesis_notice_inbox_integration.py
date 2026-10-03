"""Static safety checks for production notice-inbox wiring."""

from pathlib import Path


_API_SOURCE = (Path(__file__).parents[1] / "app" / "api.py").read_text()


def test_inbox_persistence_happens_after_server_result_serialization():
    source = _API_SOURCE
    serialized = source.index("_result_dict = result.model_dump()")
    persisted = source.index("persist_notice_preview as _persist_notice_preview")
    emitted = source.index("yield _json.dumps(_result_dict).encode()")
    assert serialized < persisted < emitted


def test_inbox_path_has_no_outbound_delivery_calls():
    source = _API_SOURCE
    block = source[source.index("# Persist only server-produced eligible"):]
    block = block[:block.index("# Sprint 3C.1A")]
    for forbidden in ("send_", "email", "push", "webhook", "schedule"):
        assert forbidden not in block.lower()
