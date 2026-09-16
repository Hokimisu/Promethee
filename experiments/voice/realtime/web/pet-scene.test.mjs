// Real Three CPU ray tests, without WebGL, a browser, GPU or a model.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as THREE from "../../../../web/avatar/node_modules/three/build/three.module.js";
import { PetInteraction } from "./pet-interaction.mjs";

const threeUrl = new URL(
    "../../../../web/avatar/node_modules/three/build/three.module.js",
    import.meta.url,
).href;
const source = readFileSync(
    new URL("./pet-scene.js", import.meta.url),
    "utf8",
).replace('from "three"', `from ${JSON.stringify(threeUrl)}`);
const { PetScene } = await import(
    `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

function sceneFixture() {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.05, 100);
    camera.position.set(0, 3, 5);
    camera.lookAt(0, 0.06, 0);
    camera.updateMatrixWorld(true);
    const node = new THREE.Group();
    node.add(
        new THREE.Mesh(
            new THREE.SphereGeometry(0.06),
            new THREE.MeshBasicMaterial(),
        ),
    );
    node.position.set(0, 0.06, 0);
    scene.add(node);
    scene.updateMatrixWorld(true);
    const calls = [],
        listeners = new Map(),
        captured = new Set();
    let resolveBegin;
    const begin = new Promise((resolve) => {
        resolveBegin = resolve;
    });
    const state = {
        ready: true,
        revision: 4,
        catalog: {
            bounds: { min: [-4.5, 0, -4.5], max: [4.5, 5, 4.5] },
            object_models: ["ball"],
            supported_interventions: [
                "spawn",
                "grab_begin",
                "grab_end",
                "grab_cancel",
            ],
        },
    };
    const interaction = new PetInteraction({
        current: () => state,
        uuid: () => String(calls.length + 1),
        request: async (_path, body) => {
            calls.push(structuredClone(body));
            if (body.action.kind === "grab_begin") return begin;
            return {
                request_id: body.request_id,
                status: "applied",
                command_revision: 6,
            };
        },
    });
    const canvas = {
        getBoundingClientRect: () => ({
            left: 0,
            top: 0,
            width: 800,
            height: 800,
        }),
        addEventListener: (name, callback) => listeners.set(name, callback),
        setPointerCapture: (id) => captured.add(id),
        hasPointerCapture: (id) => captured.has(id),
        releasePointerCapture: (id) => captured.delete(id),
    };
    const orbit = { enabled: true };
    const viewport = new PetScene({
        renderer: { domElement: canvas },
        scene,
        camera,
        orbit,
        interaction,
        objects: () => ({
            nodes: new Map([["real-ball", { node, asset: "ball" }]]),
        }),
        avatar: () => null,
        enabled: () => true,
        geometry: () => ({
            ball: [{ center: [0, 0, 0], size: [0.12, 0.12, 0.12] }],
        }),
    });
    interaction.onChange = () => viewport.update();
    function event(x = 400, y = 400) {
        return {
            clientX: x,
            clientY: y,
            pointerId: 1,
            button: 0,
            stopImmediatePropagation() {},
            preventDefault() {},
        };
    }
    return {
        viewport,
        node,
        calls,
        orbit,
        captured,
        interaction,
        event,
        acknowledge() {
            resolveBegin({
                request_id: calls[0].request_id,
                grab_id: calls[0].request_id,
                status: "applied",
                command_revision: 5,
            });
        },
    };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));

function projectedEvent(fixture, point) {
    const projected = point.clone().project(fixture.viewport.camera);
    return fixture.event((projected.x + 1) * 400, (1 - projected.y) * 400);
}

test("torso drag tracks the grabbed visual point in perspective while submitting only planar root", async () => {
    const f = sceneFixture();
    const avatar = new THREE.Group();
    const torso = new THREE.Mesh(
        new THREE.BoxGeometry(0.4, 0.5, 0.2),
        new THREE.MeshBasicMaterial(),
    );
    torso.position.set(0.35, 1.3, -0.2);
    avatar.add(torso);
    avatar.userData.petRoot = [0.35, -0.2];
    avatar.updateMatrixWorld(true);
    f.viewport.avatar = () => avatar;
    f.viewport.objects = () => null;
    const camera = f.viewport.camera;
    camera.position.set(0.35, 1.6, 4);
    camera.lookAt(0.35, 1.3, -0.2);
    camera.updateMatrixWorld(true);
    const start = projectedEvent(
        f,
        torso.getWorldPosition(new THREE.Vector3()),
    );
    const grabbed = f.viewport.pick(start).point.clone();
    const finish = f.event(start.clientX + 24, start.clientY + 12);
    const oldFloorStart = f.viewport.onPlane(start, 0);
    const oldFloorEnd = f.viewport.onPlane(finish, 0);

    f.viewport.down(start);
    f.acknowledge();
    await settle();
    f.viewport.move(finish);
    const preview = f.interaction.operation.point;
    assert.equal(preview[1], 0);
    const delta = new THREE.Vector3(preview[0] - 0.35, 0, preview[2] + 0.2);
    assert.ok(
        delta.length() < 1,
        "a small screen gesture remains a local intervention",
    );
    assert.ok(
        oldFloorEnd.distanceTo(oldFloorStart) > delta.length() * 4,
        "the regression reproduces floor-plane amplification near the horizon",
    );
    const translatedGrab = projectedEvent(f, grabbed.clone().add(delta));
    assert.ok(Math.abs(translatedGrab.clientX - finish.clientX) < 1e-8);
    assert.ok(Math.abs(translatedGrab.clientY - finish.clientY) < 1e-8);
    assert.deepEqual(avatar.userData.petRoot, [0.35, -0.2]);
    f.viewport.up(finish);
    await settle();
    assert.deepEqual(f.calls[1].action.args.position, [preview[0], preview[2]]);
});

test("avatar pick refreshes stale skinned bounds after bone translation without enlarging the target", () => {
    const f = sceneFixture();
    const geometry = new THREE.BoxGeometry(0.4, 0.5, 0.2);
    const count = geometry.attributes.position.count;
    geometry.setAttribute(
        "skinIndex",
        new THREE.Uint16BufferAttribute(new Uint16Array(count * 4), 4),
    );
    const weights = new Float32Array(count * 4);
    for (let i = 0; i < count; i++) weights[i * 4] = 1;
    geometry.setAttribute(
        "skinWeight",
        new THREE.Float32BufferAttribute(weights, 4),
    );
    const mesh = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial());
    const bone = new THREE.Bone();
    mesh.add(bone);
    mesh.bind(new THREE.Skeleton([bone]));
    const avatar = new THREE.Group();
    avatar.add(mesh);
    avatar.updateMatrixWorld(true);
    mesh.computeBoundingSphere();
    mesh.computeBoundingBox();
    const staleCenter = mesh.boundingSphere.center.clone();
    bone.position.set(1.4, 1.3, 0);
    avatar.updateMatrixWorld(true);
    f.viewport.avatar = () => avatar;
    f.viewport.objects = () => null;
    const target = bone.getWorldPosition(new THREE.Vector3());
    f.viewport.camera.position.set(1.4, 1.6, 4);
    f.viewport.camera.lookAt(target);
    f.viewport.camera.updateMatrixWorld(true);
    const event = projectedEvent(f, target);
    f.viewport.cast(event);
    assert.equal(
        f.viewport.ray.intersectObject(avatar, true).length,
        0,
        "cached bounds incorrectly reject the translated torso before triangle testing",
    );
    const hit = f.viewport.pick(event);
    assert.equal(hit.target.kind, "avatar");
    assert.ok(mesh.boundingSphere.center.distanceTo(staleCenter) > 1);
    assert.ok(mesh.boundingBox.containsPoint(target));
    assert.ok(Math.abs(hit.point.x - 1.4) < 0.01);
});

test("pointer hit selects the observed ID; drag previews never move the real mesh", async () => {
    const f = sceneFixture();
    const original = f.node.position.clone();
    f.viewport.down(f.event());
    assert.equal(f.calls[0].action.args.object_id, "real-ball");
    assert.equal(f.orbit.enabled, false);
    assert.equal(f.captured.has(1), true);
    f.viewport.move(f.event(520, 450));
    assert.equal(f.viewport.marker.visible, true);
    assert.ok(f.node.position.equals(original));
    f.viewport.up(f.event(520, 450));
    assert.equal(f.calls.length, 1); // No end before the actual begin acknowledgement.
    assert.equal(f.orbit.enabled, true);
    assert.equal(f.captured.size, 0);
    f.acknowledge();
    await settle();
    assert.equal(f.calls[1].action.kind, "grab_end");
    assert.notDeepEqual(f.calls[1].action.args.position, original.toArray());
    assert.ok(f.node.position.equals(original)); // Observation polling alone moves it.
    assert.equal(f.viewport.marker.visible, false);
});

test("lost pointer cancellation restores camera controls and releases late server hold", async () => {
    const f = sceneFixture();
    f.viewport.down(f.event());
    f.viewport.cancel();
    assert.equal(f.orbit.enabled, true);
    assert.equal(f.viewport.marker.visible, false);
    f.acknowledge();
    await settle();
    assert.deepEqual(
        f.calls.map((call) => call.action.kind),
        ["grab_begin", "grab_cancel"],
    );
});

test("floor height comes from the published object geometry", () => {
    const f = sceneFixture();
    assert.equal(f.viewport.floor("ball"), 0.06);
    assert.equal(f.viewport.floor("invented-model"), null);
});

test("user-selected plush height reaches the unchanged spawn XYZ contract; ball stays on the floor", async () => {
    const f = sceneFixture();
    f.interaction.current().catalog.object_models.push("plush");
    f.viewport.geometry = () => ({
        ball: [{ center: [0, 0, 0], size: [0.12, 0.12, 0.12] }],
        plush: [{ center: [0, 0, 0], size: [0.2, 0.3, 0.2] }],
    });
    f.interaction.selectModel("plush");
    assert.equal(f.viewport.floor("plush"), 0.15);
    f.interaction.setPlacement("high");
    assert.equal(f.viewport.floor("plush"), 1.25);
    assert.equal(f.viewport.floor("ball"), 0.06);
    assert.equal(f.calls.length, 0);
    f.viewport.down(f.event());
    await settle();
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].action.kind, "spawn");
    assert.equal(f.calls[0].action.args.model, "plush");
    assert.equal(f.calls[0].action.args.position.length, 3);
    assert.ok(Math.abs(f.calls[0].action.args.position[1] - 1.25) < 1e-12);
});
