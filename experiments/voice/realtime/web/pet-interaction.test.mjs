import test from "node:test";
import assert from "node:assert/strict";
import {
    PetInteraction,
    boundedPoint,
    throwVelocity,
    petSessionTransition,
} from "./pet-interaction.mjs";

const bounds = { min: [-4.5, 0, -4.5], max: [4.5, 5, 4.5] };
const target = { kind: "object", id: "ball-observed-1", asset: "ball" };

test("refused intervention restores watching and future audio without rewinding its cursor", () => {
    const before = {
        fence: 4,
        session: "current",
        cursor: 20,
        watching: true,
        audioAllowed: true,
    };
    assert.deepEqual(
        petSessionTransition(
            { fence: 4, session: "current", cursor: 23 },
            before,
        ),
        { session: "current", cursor: 23, watching: true, audioAllowed: true },
    );
});

test("successful intervention preserves watching while adopting the confirmed new session", () => {
    const before = {
        fence: 4,
        session: "previous",
        cursor: 20,
        watching: true,
        audioAllowed: true,
    };
    assert.deepEqual(
        petSessionTransition(
            { fence: 4, session: "previous", cursor: 20 },
            before,
            { session_id: "confirmed", cursor: 30 },
        ),
        {
            session: "confirmed",
            cursor: 30,
            watching: true,
            audioAllowed: true,
        },
    );
});

test("a new user turn or stop defeats both refused and successful late pet replies", () => {
    const before = {
        fence: 4,
        session: "previous",
        cursor: 20,
        watching: true,
        audioAllowed: true,
    };
    const current = { fence: 5, session: "new-input", cursor: 40 };
    assert.equal(petSessionTransition(current, before), null);
    assert.equal(
        petSessionTransition(current, before, {
            session_id: "old-pet",
            cursor: 30,
        }),
        null,
    );
    assert.equal(petSessionTransition({ ...current, fence: 4 }, before), null);
});
function deferred() {
    let resolve, reject;
    const promise = new Promise((a, b) => {
        resolve = a;
        reject = b;
    });
    return { promise, resolve, reject };
}
function applied(body, extras = {}) {
    return {
        request_id: body.request_id,
        status: "applied",
        command_revision: 8,
        ...(body.action.kind === "grab_begin"
            ? { grab_id: body.request_id }
            : {}),
        ...extras,
    };
}
function fixture(handler) {
    const state = {
        ready: true,
        revision: 7,
        catalog: {
            bounds,
            object_models: ["ball", "plush"],
            supported_interventions: [
                "spawn",
                "grab_begin",
                "grab_end",
                "grab_cancel",
                "throw",
            ],
        },
    };
    const calls = [],
        replies = [],
        errors = [];
    let id = 0,
        allowReply = true;
    const pet = new PetInteraction({
        current: () => state,
        uuid: () => String(++id),
        request: async (path, body, options) => {
            const record = structuredClone({ path, body, options });
            calls.push(record);
            return handler ? handler(body, options) : applied(body);
        },
        onReply: (result) => {
            replies.push(result);
            return allowReply;
        },
        onError: (error) => errors.push(error),
    });
    return {
        pet,
        state,
        calls,
        replies,
        errors,
        stale() {
            allowReply = false;
        },
    };
}

test("catalogue availability is explicit; opening does not spawn or start life", () => {
    const { pet, calls, state } = fixture();
    assert.equal(calls.length, 0);
    assert.equal(pet.selectModel("chair"), false);
    state.catalog.supported_interventions = [];
    assert.equal(pet.selectModel("ball"), false);
    assert.equal(pet.setMode("throw"), false);
    assert.equal(calls.length, 0);
});

test("plush height is an explicit choice and each new palette selection starts on the floor", () => {
    const { pet, calls } = fixture();
    assert.equal(pet.selectModel("plush"), true);
    assert.equal(pet.placement, "floor");
    assert.equal(pet.setPlacement("high"), true);
    assert.equal(pet.placement, "high");
    assert.equal(calls.length, 0);
    assert.equal(pet.setPlacement("automatic"), false);
    pet.selectModel("ball");
    assert.equal(pet.placement, "floor");
    assert.equal(pet.setPlacement("high"), false);
    pet.selectModel("plush");
    assert.equal(pet.placement, "floor");
});

test("spawn uses the observed guard once and never mutates the observed world", async () => {
    const { pet, calls, state, replies } = fixture();
    const before = structuredClone(state);
    assert.equal(pet.selectModel("ball"), true);
    assert.equal(await pet.spawn([1, 0.06, 2]), true);
    assert.deepEqual(calls[0].body, {
        request_id: "pet-1",
        expected_command_revision: 7,
        action: {
            kind: "spawn",
            args: { model: "ball", position: [1, 0.06, 2] },
        },
    });
    assert.deepEqual(state, before);
    assert.equal(calls.length, 1);
    assert.equal(replies.length, 1);
    assert.equal(pet.model, null);
});

test("pointer release before begin ACK waits for the real grab ID and returned guard", async () => {
    const ack = deferred();
    const { pet, calls } = fixture((body) =>
        body.action.kind === "grab_begin" ? ack.promise : applied(body),
    );
    const begin = pet.begin(target, [0, 0.06, 0]);
    pet.move([1, 0.06, 2]);
    assert.equal(await pet.release(), false);
    assert.equal(calls.length, 1);
    assert.equal(pet.operation.phase, "acquiring");
    ack.resolve(applied(calls[0].body, { command_revision: 21 }));
    assert.equal(await begin, true);
    assert.deepEqual(calls[1].body.action, {
        kind: "grab_end",
        args: {
            grab_id: "pet-1",
            position: [1, 0.06, 2],
        },
    });
    assert.equal(calls[1].body.expected_command_revision, 21);
    assert.equal(pet.operation, null);
});

test("an avatar drop is an external planar relocation, never a walk command", async () => {
    const { pet, calls } = fixture();
    await pet.begin({ kind: "avatar" }, [0.1, 0, 0.2]);
    pet.move([0.8, 0, -1]);
    await pet.release();
    assert.deepEqual(calls[0].body.action.args, { target: "avatar" });
    assert.deepEqual(calls[1].body.action.args, {
        grab_id: "pet-1",
        position: [0.8, -1],
    });
    assert.equal(
        calls.some(({ body }) => body.action.kind === "move"),
        false,
    );
});

test("begin rejection never submits a finish or claims an observed displacement", async () => {
    const { pet, calls, replies, errors } = fixture(() => {
        throw new Error("revision_conflict");
    });
    assert.equal(await pet.begin(target, [0, 0.06, 0]), false);
    assert.equal(await pet.release(), false);
    assert.equal(calls.length, 1);
    assert.equal(replies.length, 0);
    assert.equal(errors[0].message, "revision_conflict");
    assert.equal(pet.operation, null);
});

test("cancel during begin releases the late ACK once; it never deposits", async () => {
    const ack = deferred();
    const { pet, calls, replies } = fixture((body) =>
        body.action.kind === "grab_begin" ? ack.promise : applied(body),
    );
    const begin = pet.begin(target, [0, 0.06, 0]);
    await pet.cancel();
    assert.equal(pet.operation, null);
    ack.resolve(applied(calls[0].body));
    assert.equal(await begin, false);
    assert.deepEqual(
        calls.map(({ body }) => body.action.kind),
        ["grab_begin", "grab_cancel"],
    );
    assert.deepEqual(calls[1].body.action.args, { grab_id: "pet-1" });
    assert.equal(calls[1].options.cleanup, true);
    assert.equal(replies.length, 1);
});

test("a changed session after begin cannot resume the drag or adopt cleanup audio", async () => {
    const { pet, calls, replies, stale } = fixture();
    stale();
    assert.equal(await pet.begin(target, [0, 0.06, 0]), false);
    assert.equal(pet.operation, null);
    assert.equal(replies.length, 1);
    assert.equal(calls[1].body.action.kind, "grab_cancel");
    assert.equal(calls[1].options.cleanup, true);
});

test("cancelling a confirmed drag twice releases one immutable grab without relocation", async () => {
    const { pet, calls } = fixture();
    await pet.begin(target, [0, 0.06, 0]);
    pet.move([2, 0.06, 2]);
    await Promise.all([pet.cancel(), pet.cancel()]);
    assert.deepEqual(
        calls.map(({ body }) => body.action.kind),
        ["grab_begin", "grab_cancel"],
    );
    assert.equal(calls[1].body.action.args.grab_id, "pet-1");
});

test("network failure at drop is visible and requests release without retrying the drop", async () => {
    const { pet, calls, errors } = fixture((body) => {
        if (body.action.kind === "grab_end") throw new Error("Disconnected");
        return applied(body);
    });
    await pet.begin(target, [0, 0.06, 0]);
    assert.equal(await pet.release(), false);
    assert.deepEqual(
        calls.map(({ body }) => body.action.kind),
        ["grab_begin", "grab_end", "grab_cancel"],
    );
    assert.equal(errors[0].message, "Disconnected");
    assert.equal(pet.operation, null);
});

test("a malformed receipt cannot be mistaken for an applied intervention", async () => {
    const { pet, replies, errors } = fixture((body) => ({
        ...applied(body),
        status: "accepted",
    }));
    pet.selectModel("plush");
    assert.equal(await pet.spawn([0, 0.11, 0]), false);
    assert.equal(replies.length, 0);
    assert.match(errors[0].message, /confirmée/);
});

test("throw is explicit and available for the ball only, preserving its release position", async () => {
    const { pet, calls } = fixture();
    assert.equal(pet.setMode("throw"), true);
    assert.equal(await pet.begin({ kind: "avatar" }, [0, 0, 0]), false);
    assert.equal(
        await pet.begin({ ...target, asset: "plush" }, [0, 0.1, 0]),
        false,
    );
    await pet.begin(target, [0, 0.06, 0]);
    pet.move([1, 0.06, 1]);
    await pet.release();
    const args = calls[1].body.action.args;
    assert.deepEqual(args.position, [0, 0.06, 0]);
    assert.deepEqual(args.velocity, throwVelocity([0, 0.06, 0], [1, 0.06, 1]));
    assert.ok(args.velocity[1] > 0 && Math.hypot(...args.velocity) < 6);
});

test("bounded preview does not silently fabricate new coordinates from NaN", () => {
    assert.deepEqual(boundedPoint([-20, 9, 30], bounds), [-4.5, 5, 4.5]);
    assert.throws(() => boundedPoint([NaN, 0, 0], bounds), /invalide/);
    assert.throws(() => boundedPoint([0, 0, 0], null), /Limites/);
    assert.deepEqual(throwVelocity([0, 0, 0], [0, 0, 0]), [0, 0, 0]);
});

test("simultaneous gestures do not submit a second begin or change the selected mode", async () => {
    const ack = deferred();
    const { pet, calls } = fixture((body) =>
        body.action.kind === "grab_begin" ? ack.promise : applied(body),
    );
    const first = pet.begin(target, [0, 0.06, 0]);
    assert.equal(await pet.begin({ kind: "avatar" }, [0, 0, 0]), false);
    assert.equal(pet.setMode("throw"), false);
    assert.equal(pet.selectModel("ball"), false);
    assert.equal(calls.length, 1);
    ack.resolve(applied(calls[0].body));
    await first;
    await pet.cancel();
});
