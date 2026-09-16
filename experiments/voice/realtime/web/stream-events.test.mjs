import test from "node:test";
import assert from "node:assert/strict";
import { consumeEvents } from "./stream-events.mjs";

test("events preserve server order, including a terminal stop", () => {
    const accepted = [];
    const cursor = consumeEvents(
        {
            session_id: "new",
            cursor: 13,
            events: [
                {
                    session_id: "new",
                    cursor: 11,
                    event: "speech_start",
                    id: "next",
                },
                { session_id: "new", cursor: 12, event: "pcm", id: "next" },
                { session_id: "new", cursor: 13, event: "stop" },
            ],
        },
        "new",
        10,
        (event) => accepted.push(event.event),
    );
    assert.deepEqual(accepted, ["speech_start", "pcm", "stop"]);
    assert.equal(cursor, 13);
});

test("retention gaps fail before accepting any truncated audio", () => {
    let calls = 0;
    assert.throws(
        () =>
            consumeEvents(
                {
                    session_id: "s",
                    cursor: 9,
                    gap: true,
                    events: [{ session_id: "s", cursor: 9, event: "pcm" }],
                },
                "s",
                1,
                () => calls++,
            ),
        /perdu/,
    );
    assert.equal(calls, 0);
});

test("events from previous sessions advance global cursor without playing", () => {
    const accepted = [];
    const cursor = consumeEvents(
        {
            session_id: "new",
            cursor: 12,
            events: [
                { session_id: "old", cursor: 11, event: "pcm" },
                { session_id: "new", cursor: 12, event: "speech_start" },
            ],
        },
        "new",
        10,
        (event) => accepted.push(event.event),
    );
    assert.deepEqual(accepted, ["speech_start"]);
    assert.equal(cursor, 12);
});

test("stale response and retransmitted events do not replay or advance new session", () => {
    let calls = 0;
    assert.equal(
        consumeEvents(
            { session_id: "old", cursor: 50, events: [] },
            "new",
            10,
            () => calls++,
        ),
        10,
    );
    assert.equal(
        consumeEvents(
            {
                session_id: "new",
                cursor: 10,
                events: [{ session_id: "new", cursor: 10, event: "pcm" }],
            },
            "new",
            10,
            () => calls++,
        ),
        10,
    );
    assert.equal(calls, 0);
});
