import * as THREE from "three";

const labels = {
    accepted: "Accepté",
    running: "En cours",
    completed: "Terminé",
    cancelled: "Arrêté",
    failed: "Non réalisé",
    rejected: "Refusé",
    interrupted: "Interrompu",
};

async function request(path, body) {
    const response = await fetch(path, {
        ...(body
            ? {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(body),
              }
            : {}),
        signal: AbortSignal.timeout(1500),
    });
    const result = await response.json();
    if (!response.ok)
        throw new Error(result.error ?? "Connexion indisponible.");
    return result;
}

export function startLive({
    data,
    vrm,
    retarget,
    objects,
    scene,
    renderer,
    camera,
    orbit,
    status,
}) {
    document.querySelector("#playback").hidden = true;
    document.querySelector("#diagnostics").hidden = true;
    const panel = document.querySelector("#live");
    panel.hidden = false;
    const result = document.querySelector("#live-result"),
        stop = document.querySelector("#live-stop");
    const target = document.querySelector("#object-target");
    let latest = null,
        healthy = false,
        busy = false,
        lastFrame = -1;
    let renderError = null;
    const weights = { RightHand: 0, LeftHand: 0 };
    const buttons = [...panel.querySelectorAll("button[data-kind]")];
    function availability() {
        for (const button of buttons)
            button.disabled =
                busy ||
                !healthy ||
                renderError !== null ||
                !data.actions.includes(button.dataset.kind) ||
                ["accepted", "running"].includes(latest?.execution?.status);
        stop.disabled =
            busy ||
            !["accepted", "running"].includes(latest?.execution?.status);
    }
    availability();
    function show(item) {
        result.textContent = `${labels[item.status] ?? item.status}${item.cancel_requested && !["cancelled", "completed", "failed", "interrupted"].includes(item.status) ? " · arrêt demandé" : ""}${item.error ? " · " + item.error.message : ""}`;
    }
    function position(prefix, dimensions) {
        return dimensions.map((axis) => {
            const input = document.querySelector(`#${prefix}-${axis}`);
            if (
                !input.reportValidity() ||
                !Number.isFinite(input.valueAsNumber)
            )
                throw new Error("Renseigner les coordonnées.");
            return input.valueAsNumber;
        });
    }
    async function submit(action) {
        busy = true;
        availability();
        try {
            const world = await request("/world.json");
            show(
                await request("/action", {
                    request_id: "web-" + crypto.randomUUID(),
                    expected_revision: world.revision,
                    action,
                }),
            );
        } catch (error) {
            result.textContent = error.message;
        } finally {
            busy = false;
            availability();
        }
    }
    const actions = {
        spawn: () => ({
            kind: "spawn",
            args: {
                object_id: document.querySelector("#object-name").value,
                asset: document.querySelector("#object-model").value,
                position: position("object", ["x", "y", "z"]),
            },
        }),
        take: () => ({ kind: "take", args: { object_id: target.value } }),
        place: () => ({
            kind: "place",
            args: { position: position("object", ["x", "y", "z"]) },
        }),
        move: () => ({
            kind: "move",
            args: { position: position("move", ["x", "z"]) },
        }),
        posture: () => ({
            kind: "posture",
            args: { name: document.querySelector("#live-posture").value },
        }),
    };
    for (const button of buttons)
        button.onclick = () => {
            try {
                void submit(actions[button.dataset.kind]());
            } catch (error) {
                result.textContent = error.message;
            }
        };
    stop.onclick = async () => {
        const requestId = latest?.execution?.request_id;
        if (!requestId) return;
        busy = true;
        availability();
        try {
            show(await request("/cancel", { request_id: requestId }));
        } catch (error) {
            result.textContent = error.message;
        } finally {
            busy = false;
            availability();
        }
    };
    const edges = data.skeleton.parents.flatMap((parent, index) =>
        parent < 0 ? [] : [[parent, index]],
    );
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(new Float32Array(edges.length * 6), 3),
    );
    const source = new THREE.LineSegments(
        geometry,
        new THREE.LineBasicMaterial({ color: 0x8eefff, depthTest: false }),
    );
    source.visible = false;
    source.renderOrder = 20;
    scene.add(source);
    document.querySelector("#live-skeleton").onchange = (event) => {
        source.visible = event.target.checked;
    };
    const root = data.frames[0].positions[0];
    orbit.target.set(root[0], 1, root[2]);
    camera.position.set(root[0] + 3, 2, root[2] + 5.3);
    orbit.update();
    let previousTime = null;
    renderer.setAnimationLoop((now) => {
        if (latest && healthy && renderError === null) {
            const seconds =
                previousTime === null
                    ? 0
                    : Math.min(0.1, (now - previousTime) / 1000);
            const heldHands = new Set(
                Object.values(latest.observation.objects).flatMap((obj) =>
                    obj.spatial.attachment
                        ? [obj.spatial.attachment.joint]
                        : [],
                ),
            );
            for (const name of Object.keys(weights)) {
                const desired = latest.alignment_hands.includes(name) ? 1 : 0;
                weights[name] +=
                    Math.sign(desired - weights[name]) *
                    Math.min(Math.abs(desired - weights[name]), seconds / 0.25);
                if (heldHands.has(name)) weights[name] = 1;
            }
            try {
                retarget.apply(
                    latest.observation.pose,
                    Object.keys(weights).filter((name) => weights[name] > 0),
                    weights,
                );
                objects.display(latest.observation.objects);
                geometry.attributes.position.array.set(
                    edges.flatMap((edge) =>
                        edge.flatMap(
                            (joint) => latest.observation.pose.positions[joint],
                        ),
                    ),
                );
                geometry.attributes.position.needsUpdate = true;
            } catch (error) {
                renderError = `Affichage indisponible : ${error.message}. Recharger la page.`;
                status.textContent = renderError;
                availability();
            }
        }
        previousTime = now;
        renderer.render(scene, camera);
    });
    async function poll() {
        try {
            const state = await request("/state.json");
            if (state.controller_session !== data.controller_session)
                throw new Error("Session redémarrée : recharger la page.");
            if (state.sequence > lastFrame) {
                latest = state;
                lastFrame = state.sequence;
                const selected = target.value;
                const ids = Object.keys(state.observation.objects);
                if (JSON.stringify(ids) !== target.dataset.ids) {
                    target.replaceChildren(
                        new Option("Choisir un objet", ""),
                        ...ids.map((id) => new Option(id, id)),
                    );
                    target.value = ids.includes(selected) ? selected : "";
                    target.dataset.ids = JSON.stringify(ids);
                }
                if (state.execution) show(state.execution);
            }
            healthy = true;
            status.textContent =
                renderError ??
                `Session en direct · cinématique · ${state.message}`;
        } catch (error) {
            healthy = false;
            status.textContent =
                renderError ?? `${error.message} Dernière pose affichée.`;
        }
        availability();
        setTimeout(poll, 50);
    }
    void poll();
}
