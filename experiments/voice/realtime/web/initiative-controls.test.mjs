// CPU protocol tests with explicit HTTP/audio doubles. No initiative/model is run.
import test from "node:test";
import assert from "node:assert/strict";
import {
    InitiativeControls,
    initiativeButtonState,
    initiativeConfiguration,
    initiativeTransition,
    shouldSendClientStats,
    handleSessionStop,
} from "./initiative-controls.mjs";

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => {
        resolve = yes;
        reject = no;
    });
    return { promise, resolve, reject };
}
const flush = async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
};
const initiative = { remaining: 3, used: 0, paused: false, interval: 20 };
function response(overrides = {}) {
    return {
        initiative,
        session_id: "session",
        cursor: 40,
        interrupted: false,
        ...overrides,
    };
}
function harness({ enable } = {}) {
    const state = {
        fence: 4,
        session: "session",
        cursor: 12,
        audioAllowed: true,
    };
    const calls = [],
        applied = [],
        errors = [];
    let enables = 0;
    const controls = new InitiativeControls({
        current: () => state,
        enableAudio: () => {
            enables++;
            return enable?.promise ?? Promise.resolve();
        },
        request: (path, body) => {
            const request = { path, body, ...deferred() };
            calls.push(request);
            return request.promise;
        },
        apply: (result) => applied.push(result),
        onError: (error) => errors.push(error),
    });
    return {
        controls,
        state,
        calls,
        applied,
        errors,
        get enables() {
            return enables;
        },
    };
}

test("construction sends no automatic configuration; explicit activation enables audio first", async () => {
    const enable = deferred(),
        h = harness({ enable });
    assert.equal(h.calls.length, 0);
    assert.equal(h.enables, 0);
    h.state.session = null;
    h.state.audioAllowed = false;
    const activating = h.controls.configure(3, 20);
    assert.equal(h.enables, 1);
    assert.equal(h.calls.length, 0);
    enable.resolve();
    await flush();
    assert.deepEqual(h.calls[0].body, { budget: 3, interval: 20 });
    assert.equal(h.calls[0].path, "/initiative_configure");
    h.calls[0].resolve(response());
    assert.equal(await activating, true);
    assert.equal(h.applied[0].resetAudio, true);
    assert.equal(h.applied[0].audioAllowed, true);
    assert.equal(h.applied[0].cursor, 40);
});

test("pause with unchanged SID preserves an ongoing user reply and its unread cursor", async () => {
    const h = harness();
    const pausing = h.controls.pause(true);
    assert.equal(h.enables, 0);
    assert.deepEqual(h.calls[0].body, { paused: true });
    h.calls[0].resolve(
        response({ initiative: { ...initiative, paused: true } }),
    );
    assert.equal(await pausing, true);
    const effect = h.applied[0];
    assert.equal(effect.resetAudio, false);
    assert.equal(effect.cursor, 12); // ACK cursor must not skip ongoing PCM events.
    assert.equal(effect.audioAllowed, true);
    assert.equal(effect.interrupted, false);
});

test("explicit budget refill preserves a paused life and does not enable voice or reset audio", async () => {
    const h = harness();
    h.state.audioAllowed = false;
    const adding = h.controls.addBudget(10);
    assert.equal(h.enables, 0);
    assert.equal(h.calls[0].path, "/initiative_budget");
    assert.deepEqual(h.calls[0].body, { add_budget: 10 });
    h.calls[0].resolve(
        response({
            initiative: { ...initiative, remaining: 10, used: 3, paused: true },
        }),
    );
    assert.equal(await adding, true);
    const effect = h.applied[0];
    assert.equal(effect.initiative.remaining, 10);
    assert.equal(effect.initiative.paused, true);
    assert.equal(effect.audioAllowed, false);
    assert.equal(effect.enableAudio, false);
    assert.equal(effect.resetAudio, false);
    assert.equal(effect.session, "session");
    assert.equal(effect.cursor, 12);
    assert.equal(effect.interrupted, false);
});

test("a late budget acknowledgement cannot revive a session after stop", async () => {
    const h = harness();
    const adding = h.controls.addBudget(10);
    h.state.fence++;
    h.calls[0].resolve(
        response({ initiative: { ...initiative, remaining: 10 } }),
    );
    assert.equal(await adding, false);
    assert.equal(h.enables, 0);
    assert.equal(h.applied.length, 0);
});

test("budget can be refilled before opening the box without creating an audio session", async () => {
    const h = harness();
    h.state.session = null;
    h.state.audioAllowed = false;
    const adding = h.controls.addBudget(10);
    h.calls[0].resolve(
        response({
            session_id: "",
            initiative: { ...initiative, paused: true, remaining: 10 },
        }),
    );
    assert.equal(await adding, true);
    assert.equal(h.enables, 0);
    assert.equal(h.applied[0].session, null);
    assert.equal(h.applied[0].resetAudio, false);
    assert.equal(h.applied[0].audioAllowed, false);
    assert.equal(h.applied[0].initiative.paused, true);
});

test("budget reply cannot introduce a new session or interrupt current speech", async () => {
    const h = harness();
    const adding = h.controls.addBudget(10);
    h.calls[0].resolve(response({ session_id: "unexpected" }));
    assert.equal(await adding, false);
    assert.equal(h.applied.length, 0);
    assert.equal(h.enables, 0);
    assert.match(h.errors[0].message, /session/);
});

test("pause that interrupts an autonomous turn adopts the new SID and cursor", async () => {
    const h = harness();
    const pausing = h.controls.pause(true);
    h.calls[0].resolve(
        response({
            session_id: "after-pause",
            interrupted: true,
            initiative: { ...initiative, paused: true, used: 1, remaining: 2 },
        }),
    );
    await pausing;
    assert.equal(h.applied[0].resetAudio, true);
    assert.equal(h.applied[0].session, "after-pause");
    assert.equal(h.applied[0].cursor, 40);
    assert.equal(h.applied[0].interrupted, true);
    assert.equal(h.enables, 0);
});

test("resume requires an audio gesture but does not reset the current session", async () => {
    const h = harness();
    h.state.audioAllowed = false;
    const resuming = h.controls.pause(false);
    await flush();
    assert.equal(h.enables, 1);
    assert.equal(h.calls[0].path, "/initiative_pause");
    h.calls[0].resolve(response());
    await resuming;
    assert.equal(h.applied[0].resetAudio, false);
    assert.equal(h.applied[0].audioAllowed, true);
    assert.equal(h.applied[0].cursor, 12);
});

test("reloaded active initiative enables voice without toggling pause or changing its budget", async () => {
    const h = harness();
    h.state.audioAllowed = false;
    const persisted = { ...initiative, remaining: 1, used: 2 };
    const button = initiativeButtonState(persisted, h.state.audioAllowed);
    assert.deepEqual(button, { label: "Activer la voix", paused: false });
    const enabling = h.controls.pause(button.paused);
    await flush();
    assert.equal(h.enables, 1);
    assert.equal(h.calls[0].path, "/initiative_pause");
    assert.deepEqual(h.calls[0].body, { paused: false });
    h.calls[0].resolve(response({ initiative: persisted }));
    assert.equal(await enabling, true);
    assert.deepEqual(h.applied[0].initiative, persisted);
    assert.equal(h.applied[0].audioAllowed, true);
    assert.equal(h.applied[0].resetAudio, false);
    assert.equal(h.applied[0].cursor, 12);
    assert.deepEqual(initiativeButtonState(persisted, true), {
        label: "Mettre en pause",
        paused: true,
    });
    assert.deepEqual(
        initiativeButtonState({ ...persisted, paused: true }, false),
        { label: "Reprendre", paused: false },
    );
    assert.deepEqual(initiativeButtonState(null, false), {
        label: "Activer",
        paused: null,
    });
});

for (const source of [
    "microphone input_start",
    "typed reply",
    "scene stop",
    "pagehide",
])
    test(`late initiative ACK cannot replace the session after ${source}`, async () => {
        const h = harness();
        const pending = h.controls.configure(3, null);
        await flush();
        h.state.fence++;
        h.state.session = "newer";
        h.calls[0].resolve(response({ session_id: "obsolete" }));
        assert.equal(await pending, false);
        assert.deepEqual(h.applied, []);
        assert.deepEqual(h.errors, []);
        assert.equal(h.controls.pending, false);
    });

test("user interruption during AudioContext resume prevents even sending old configuration", async () => {
    const enable = deferred(),
        h = harness({ enable });
    const pending = h.controls.configure(3, 20);
    h.state.fence++;
    enable.resolve();
    assert.equal(await pending, false);
    assert.equal(h.calls.length, 0);
});

test("configuration error stays visible without applying an audio transition or retrying", async () => {
    const h = harness();
    const pending = h.controls.configure(3, 20);
    await flush();
    assert.equal(await h.controls.configure(3, 20), false);
    h.calls[0].reject(new Error("Already configured"));
    assert.equal(await pending, false);
    assert.equal(h.calls.length, 1);
    assert.equal(h.applied.length, 0);
    assert.match(h.errors[0].message, /Already configured/);
    assert.equal(h.controls.pending, false);
});

test("budget and cadence are explicit and bounded, with no replacement defaults", () => {
    assert.deepEqual(initiativeConfiguration(3, null), {
        budget: 3,
        interval: null,
    });
    assert.deepEqual(initiativeConfiguration(2, 1.5), {
        budget: 2,
        interval: 1.5,
    });
    for (const budget of [true, "3", null, 0, -1, 2.5, 1001, Infinity])
        assert.throws(() => initiativeConfiguration(budget, 20), /budget/);
    for (const interval of [true, "20", 0, -1, 0.5, NaN, Infinity])
        assert.throws(() => initiativeConfiguration(3, interval), /cadence/);
    assert.throws(() => harness().controls.pause(1), /booléen/);
});

test("malformed ACK cannot authorize audio or alter the event cursor", () => {
    const h = harness();
    for (const invalid of [
        response({ session_id: null }),
        response({ cursor: -1 }),
        response({ interrupted: "true" }),
        response({ initiative: null }),
        response({ initiative: { ...initiative, remaining: 1.5 } }),
    ])
        assert.throws(
            () => initiativeTransition(h.state, invalid, true),
            /invalide/,
        );
});

test("heartbeat supports idle enabled initiative, but no disabled audio or paused idle session", () => {
    const base = {
        session: "s",
        audioAllowed: true,
        active: false,
        initiative,
    };
    assert.equal(shouldSendClientStats(base), true);
    assert.equal(
        shouldSendClientStats({
            ...base,
            initiative: { ...initiative, paused: true },
        }),
        false,
    );
    assert.equal(
        shouldSendClientStats({ ...base, audioAllowed: false }),
        false,
    );
    assert.equal(shouldSendClientStats({ ...base, session: null }), false);
    assert.equal(shouldSendClientStats({ ...base, initiative: null }), false);
    assert.equal(
        shouldSendClientStats({ ...base, initiative: null, active: true }),
        true,
    );
});

test("hidden pet tab cannot keep life active through the qualification heartbeat branch", () => {
    const viewing = {
        session: "pet",
        audioAllowed: true,
        active: true,
        initiative,
        petMode: true,
        petWatching: true,
        visible: false,
    };
    assert.equal(shouldSendClientStats(viewing), false);
    assert.equal(shouldSendClientStats({ ...viewing, visible: true }), true);
    assert.equal(
        shouldSendClientStats({
            ...viewing,
            visible: true,
            active: false,
            initiative: null,
        }),
        true,
    );
    assert.equal(
        shouldSendClientStats({
            ...viewing,
            visible: true,
            petWatching: false,
        }),
        false,
    );
    assert.equal(
        shouldSendClientStats({
            ...viewing,
            visible: true,
            audioAllowed: false,
        }),
        false,
    );
});

test("audio-only stop preserves microphone and authoritative body; legacy stop retains full semantics", () => {
    const calls = [];
    const hooks = {
        disableMicrophone: () => calls.push("disable-microphone"),
        stopLocal: (freeze) => calls.push(["stop-local", freeze]),
        resumeEvents: () => calls.push("resume-events"),
        onStopped: () => calls.push("stopped"),
    };
    assert.equal(
        handleSessionStop({ event: "stop", body: false }, hooks),
        true,
    );
    assert.deepEqual(calls, [
        ["stop-local", false],
        "resume-events",
        "stopped",
    ]);
    calls.length = 0;
    assert.equal(handleSessionStop({ event: "stop" }, hooks), true);
    assert.deepEqual(calls, [
        "disable-microphone",
        ["stop-local", true],
        "stopped",
    ]);
    calls.length = 0;
    assert.equal(
        handleSessionStop(
            { event: "stop", id: "utterance", body: false },
            hooks,
        ),
        false,
    );
    assert.deepEqual(calls, []);
});
