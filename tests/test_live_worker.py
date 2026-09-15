import base64

import pytest

from promethee.live_worker import command, final_usage


@pytest.mark.parametrize(
    "event",
    [
        {"type": []},
        {"type": "session.input_audio.append", "audio": "!"},
        {"type": "session.input_audio.append", "audio": base64.b64encode(b"x").decode()},
        {"type": "session.input_audio.append", "audio": "AAAA" * 16001},
        {"type": "session.commentary.append", "content": "text"},
        {"type": "session.commentary.append", "content": "text", "delegation_id": []},
        {"type": "session.close", "extra": True},
        {"type": "response.create"},
    ],
)
def test_invalid_parent_event_is_rejected(event):
    with pytest.raises(ValueError):
        command(event)


def test_exact_opaque_delegation_and_pcm_are_preserved():
    event = {
        "type": "session.commentary.append",
        "event_id": "reply-1",
        "delegation_id": "item_Opaque-17",
        "content": "No body action confirmed.",
    }
    assert command(event) == event
    audio = {"type": "session.input_audio.append", "audio": "AAA="}
    assert command(audio) == audio


@pytest.mark.parametrize("seconds", [None, True, -1, float("nan"), float("inf"), "1"])
def test_missing_or_invalid_final_usage_never_counts_as_success(seconds):
    with pytest.raises(ValueError):
        final_usage(
            {"session": {"id": "s"}, "reason": "close_requested", "usage": {"seconds": seconds}}
        )


def test_abnormal_close_is_not_success_even_with_usage():
    event = {"session": {"id": "s"}, "reason": "connection_lost", "usage": {"seconds": 2.5}}
    with pytest.raises(ValueError):
        final_usage(event)
    event["reason"] = "close_requested"
    final_usage(event)
