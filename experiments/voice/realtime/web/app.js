import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import { createRoom } from "./room.js";
import { PCMPlayer } from "./pcm-player.js";
import { consumeEvents } from "./stream-events.mjs";
import { AudioMouth } from "./audio-mouth.mjs";
import { MicrophoneInput } from "./microphone.mjs";
import { createSileroDetector } from "./silero-microphone.mjs";
import { ObjectVisuals } from "../../../../web/avatar/objects.js";
import { PetInteraction, petSessionTransition } from "./pet-interaction.mjs";
import { PetScene } from "./pet-scene.js";
import {
    InitiativeControls,
    initiativeButtonState,
    shouldSendClientStats,
    handleSessionStop,
} from "./initiative-controls.mjs";

const $ = (id) => document.getElementById(id);
const room = createRoom($("stage"));
const { renderer, scene, camera, orbit } = room;
let objectVisuals = null,
    petWatching = false,
    petMode = false;
let petView = null;
let state = null,
    session = null,
    cursor = 0,
    fence = 0,
    active = false,
    pending = false,
    audioAllowed = false,
    freezeMotion = false,
    connected = false;
let vrm = null,
    motionId = null,
    motionSequence = -1,
    motionFrames = [],
    boneNodes = [],
    hips = null,
    avatarError = null,
    connectionError = null;
let lastNow = 0,
    mouth = null,
    visiblePose = false,
    renderedFrames = 0;
const q1 = new THREE.Quaternion(),
    q2 = new THREE.Quaternion(),
    parentQ = new THREE.Quaternion(),
    root = new THREE.Vector3(),
    root2 = new THREE.Vector3();
const terminal = new Set([
    "ready",
    "idle",
    "stopped",
    "complete",
    "completed",
    "finished",
    "failed",
    "error",
]);
const labels = {
    loading: "Chargement…",
    initializing: "Préparation…",
    starting: "Préparation de l’essai…",
    ready: "Prête",
    idle: "Prête",
    thinking: "Ariane réfléchit…",
    generating: "Ariane réfléchit…",
    synthesizing: "Préparation de la voix…",
    speaking: "Ariane parle",
    listening: "Je vous écoute…",
    transcribing: "Transcription locale…",
    running: "Essai en cours",
    moving: "En mouvement",
    stopping: "Arrêt…",
    stopped: "Essai arrêté",
    complete: "Essai terminé",
    completed: "Essai terminé",
    finished: "Essai terminé",
    failed: "Essai interrompu",
    error: "Essai indisponible",
};
const petLabels = {
    starting: "Préparation de la boîte…",
    running: "Dans sa boîte",
    failed: "Une activité s’est interrompue",
    error: "Boîte indisponible",
};
function message(error) {
    return typeof error === "string"
        ? error
        : (error?.message ?? "Connexion indisponible.");
}
function showError(error) {
    $("error").textContent = error ? message(error) : "";
    $("error").hidden = !error;
}
function telemetry(event, id, metrics, whichSession = session) {
    if (!whichSession) return;
    if (
        event === "client_stats" &&
        petMode &&
        document.visibilityState !== "visible"
    )
        return;
    void fetch("/telemetry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event, session_id: whichSession, id, metrics }),
        signal: AbortSignal.timeout(1200),
    }).catch(() => {});
}
const audio = new PCMPlayer({
    onStats(stats) {
        $("played").textContent =
            `${(stats.played_frames / 48000).toLocaleString("fr", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
        $("frames").textContent = stats.played_frames.toLocaleString("fr");
        $("underflows").textContent = String(stats.underflows);
        $("buffered").textContent =
            `${(stats.buffered_frames / 48000).toFixed(1).replace(".", ",")} s`;
    },
    onSpeech(text) {
        $("subtitle").textContent = text;
        $("subtitle").hidden = !text;
        if (!text) mouth?.reset();
    },
    onPlayback(event, whichSession, id, metrics) {
        telemetry(event, id, metrics, whichSession);
    },
});
async function request(path, body, timeout = 6000) {
    const response = await fetch(path, {
        cache: "no-store",
        ...(body !== undefined
            ? {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(body),
              }
            : {}),
        signal: AbortSignal.timeout(timeout),
    });
    const data = await response.json();
    if (!response.ok) {
        const error = new Error(
            message(data.error ?? `Requête refusée (${response.status}).`),
        );
        error.httpStatus = response.status;
        throw error;
    }
    return data;
}
const microphone = new MicrophoneInput({
    createContext: () =>
        new AudioContext({ sampleRate: 48000, latencyHint: "interactive" }),
    getUserMedia: (constraints) => {
        if (!navigator.mediaDevices?.getUserMedia)
            throw new Error(
                "Le microphone nécessite un navigateur compatible sur localhost ou HTTPS.",
            );
        return navigator.mediaDevices.getUserMedia(constraints);
    },
    createDetector: createSileroDetector,
    request: (path, body) => request(path, body, 20000),
    canListen: () =>
        connected && state?.ready && state?.asr?.state === "ready" && !pending,
    interrupt: () => {
        petView?.cancel();
        const epoch = stopLocal(false);
        active = true;
        showError(null);
        return epoch;
    },
    adoptSession: (result, epoch) => {
        if (epoch !== fence) return false;
        session = result.session_id;
        cursor = result.cursor;
        // The body remains authoritative while capture and transcription run.
        freezeMotion = false;
        return true;
    },
    allowAudio: (whichSession, epoch) => {
        if (epoch !== fence || session !== whichSession) return false;
        audio.reset(session);
        audioAllowed = true;
        active = true;
        return true;
    },
    onState: () => controls(),
});
const initiativeControls = new InitiativeControls({
    request: (path, body) => request(path, body, 20000),
    enableAudio: () => audio.enable(),
    current: () => ({ fence, session, cursor, audioAllowed }),
    apply: (result) => {
        if (result.resetAudio) {
            stopLocal(false);
            session = result.session;
            cursor = result.cursor;
            audio.reset(session);
        } else if (result.enableAudio && !audio.session) {
            // A previous local stop can leave this session unbound. Reattach
            // without discarding samples, statistics or the event cursor.
            audio.session = session;
        }
        audioAllowed = result.audioAllowed;
        if (state?.mode === "pet" && result.enableAudio) petWatching = true;
        if (result.enableAudio || result.interrupted) freezeMotion = false;
        if (result.interrupted) active = false;
        state = { ...state, initiative: result.initiative };
        if (result.enableAudio && audioAllowed && session)
            telemetry("client_stats", null, {
                ...audio.stats,
                rendered_frames: renderedFrames,
            });
    },
    onChange: () => controls(),
    onError: (error) => showError(error),
});
const petInteraction = new PetInteraction({
    current: () => ({
        ready:
            petMode &&
            petWatching &&
            session &&
            connected &&
            state?.ready &&
            !pending,
        revision: state?.pet?.command_revision,
        catalog: state?.pet,
    }),
    request: async (path, body, { cleanup } = {}) => {
        if (cleanup) return request(path, body, 20000);
        microphone.cancelInput();
        const before = { session, cursor, audioAllowed, watching: petWatching };
        before.fence = stopLocal(false);
        try {
            const result = await request(path, body, 20000);
            return { ...result, clientState: before };
        } catch (error) {
            // A refused intervention does not change the server session. Re-arm
            // future speech, never the discarded PCM or a newer user turn.
            if ([400, 409].includes(error.httpStatus)) {
                const restored = petSessionTransition(
                    { fence, session, cursor },
                    before,
                );
                if (restored) applyPetSession(restored);
            }
            throw error;
        }
    },
    onReply: (result) => {
        const transition = petSessionTransition(
            { fence, session, cursor },
            result.clientState,
            result,
        );
        if (!transition) return false;
        applyPetSession(transition);
        state = {
            ...state,
            pet: { ...state.pet, command_revision: result.command_revision },
        };
        // The acknowledgement can render its observed objects immediately; the avatar
        // keeps using the controller's prepared motion stream, never a client transform.
        if (result.observation?.objects && objectVisuals)
            objectVisuals.display(result.observation.objects);
        $("pet-action-status").textContent = "";
        $("pet-action-status").hidden = true;
        showError(null);
        return true;
    },
    onError: (error) => {
        $("pet-action-status").textContent = message(error);
        $("pet-action-status").hidden = false;
    },
    onChange: () => {
        petView?.update();
        controls();
    },
});
function applyPetSession(transition) {
    session = transition.session;
    cursor = transition.cursor;
    petWatching = transition.watching;
    active = false;
    freezeMotion = false;
    audio.reset(transition.audioAllowed ? session : null);
    audioAllowed = transition.audioAllowed;
    if (petWatching && audioAllowed)
        telemetry("client_stats", null, {
            ...audio.stats,
            rendered_frames: renderedFrames,
        });
}
function petControls() {
    if (!petMode) return;
    $("pet-placement-control").hidden = petInteraction.model !== "plush";
    $("pet-placement").value = petInteraction.placement;
    $("pet-placement").disabled = petInteraction.busy;
    const ready =
        petWatching && session && connected && state?.ready && !pending;
    for (const button of document.querySelectorAll("[data-pet-model]")) {
        button.disabled =
            !ready ||
            petInteraction.busy ||
            !petInteraction.available("spawn") ||
            !state.pet?.object_models?.includes(button.dataset.petModel);
        button.setAttribute(
            "aria-pressed",
            String(button.dataset.petModel === petInteraction.model),
        );
    }
    $("pet-move").disabled =
        !ready ||
        petInteraction.busy ||
        !petInteraction.available("grab_begin");
    $("pet-throw").disabled =
        !ready || petInteraction.busy || !petInteraction.available("throw");
    $("pet-move").setAttribute(
        "aria-pressed",
        String(petInteraction.mode === "move" && !petInteraction.model),
    );
    $("pet-throw").setAttribute(
        "aria-pressed",
        String(petInteraction.mode === "throw" && !petInteraction.model),
    );
    $("pet-cancel").hidden = !petInteraction.operation && !petInteraction.model;
    const phase = petInteraction.operation?.phase;
    $("pet-hint").textContent =
        phase === "acquiring"
            ? "Arrêt du mouvement avant la saisie…"
            : phase === "committing"
              ? "Dépôt en cours de confirmation…"
              : petInteraction.operation
                ? "Prévisualisation · relâchez pour confirmer. Échap pour annuler."
                : petInteraction.model
                  ? "Cliquez dans la boîte pour poser l’objet. Échap pour annuler."
                  : petInteraction.mode === "throw"
                    ? "Depuis la balle, tirez une flèche puis relâchez pour lancer."
                    : "Faites glisser Ariane ou un objet. Le clic droit tourne la vue.";
    $("stage").dataset.gesture = petInteraction.operation
        ? "dragging"
        : petInteraction.model
          ? "placing"
          : "ready";
}
petView = new PetScene({
    renderer,
    scene,
    camera,
    orbit,
    interaction: petInteraction,
    objects: () => objectVisuals,
    avatar: () => vrm?.scene,
    enabled: () =>
        petMode && petWatching && connected && state?.ready && !pending,
    geometry: () => state?.pet?.object_geometry,
});
for (const button of document.querySelectorAll("[data-pet-model]"))
    button.onclick = () => {
        $("pet-action-status").hidden = true;
        petInteraction.selectModel(button.dataset.petModel);
    };
$("pet-move").onclick = () => petInteraction.setMode("move");
$("pet-throw").onclick = () => petInteraction.setMode("throw");
$("pet-cancel").onclick = () => petView.cancel();
$("pet-placement").onchange = (event) =>
    petInteraction.setPlacement(event.target.value);
addEventListener("keydown", (event) => {
    if (event.key === "Escape") petView.cancel();
});
addEventListener("blur", () => petView.cancel());
addEventListener("visibilitychange", () => {
    if (document.hidden) petView.cancel();
});
function controls() {
    const isPet = state?.mode === "pet";
    if (isPet !== petMode) {
        petMode = isPet;
        document.body.classList.toggle("pet-mode", isPet);
        document.querySelectorAll(".pet-only").forEach((element) => {
            element.hidden = !isPet;
        });
        $("initiative-heading").textContent = isPet
            ? "Sa vie dans la boîte"
            : "Initiative";
        $("message").placeholder = isPet
            ? "Un mot à Ariane…"
            : "Écrivez à Ariane…";
        $("microphone-help").open = !isPet;
        room.setMode(state?.mode);
    }
    $("pet-watch").disabled = pending || !connected || !state?.ready || !vrm;
    $("pet-watch").hidden = !isPet || (petWatching && audioAllowed);
    petControls();
    const initiative = state?.initiative;
    const hasInitiative = initiative != null;
    $("initiative-add-budget").hidden = !isPet || !hasInitiative;
    $("initiative-add-budget").disabled =
        !hasInitiative ||
        initiative.remaining > 990 ||
        initiativeControls.pending ||
        pending ||
        !connected ||
        !state?.ready;
    $("initiative-budget").disabled =
        hasInitiative || initiativeControls.pending;
    $("initiative-interval").disabled =
        hasInitiative || initiativeControls.pending;
    if (hasInitiative) {
        $("initiative-budget").value = initiative.remaining + initiative.used;
        $("initiative-interval").value = initiative.interval ?? "";
    }
    $("cadence-note").hidden =
        isPet && $("initiative-interval").value.trim() !== "";
    $("initiative-toggle").disabled =
        pending ||
        initiativeControls.pending ||
        !connected ||
        !state?.ready ||
        microphone.busy ||
        (hasInitiative && initiative.paused && initiative.remaining === 0);
    $("initiative-toggle").textContent = initiativeButtonState(
        initiative,
        audioAllowed,
    ).label;
    if (isPet && (!initiative || !initiative.paused) && audioAllowed)
        $("initiative-toggle").textContent = initiative
            ? "Pause de vie"
            : "Laisser vivre";
    $("initiative-status").textContent = initiativeControls.pending
        ? "Demande en cours…"
        : !hasInitiative
          ? "Désactivée"
          : `${initiative.paused ? "En pause" : initiative.remaining ? "Active" : "Budget épuisé"} · ${initiative.remaining} appel${initiative.remaining > 1 ? "s" : ""} restant${initiative.remaining > 1 ? "s" : ""} · ${initiative.used} utilisé${initiative.used > 1 ? "s" : ""}`;
    const transcript =
        typeof state?.transcript === "string" ? state.transcript.trim() : "";
    $("transcript").textContent = transcript ? `Vous : ${transcript}` : "";
    $("transcript").hidden = !transcript;
    const inputError =
        typeof state?.input_error === "string" ? state.input_error : "";
    $("input-error").textContent = inputError;
    $("input-error").hidden = !inputError;
    $("start").disabled =
        pending ||
        active ||
        microphone.busy ||
        !connected ||
        !state?.ready ||
        !vrm ||
        Boolean(avatarError);
    $("stop").disabled =
        !active &&
        !pending &&
        !microphone.enabled &&
        !microphone.busy &&
        !(hasInitiative && !initiative.paused);
    $("message").disabled = !connected || !state?.ready || pending;
    $("send").disabled = $("message").disabled;
    $("scenario").disabled = active || pending;
    $("microphone").textContent = microphone.enabled
        ? "Couper le micro"
        : "Activer le micro";
    $("microphone").setAttribute("aria-pressed", String(microphone.enabled));
    $("microphone").disabled =
        !microphone.enabled &&
        (pending ||
            !connected ||
            !state?.ready ||
            state?.asr?.state !== "ready");
    const micLabels = {
        off: "Micro coupé",
        opening: "Autorisation et chargement du détecteur…",
        ready: "Micro actif · parlez pour interrompre Ariane",
        listening: "Écoute · 12 secondes maximum",
        transcribing: "Transcription locale…",
        failed: "Micro indisponible",
    };
    $("microphone-status").textContent =
        microphone.error ||
        (state?.asr?.state === "loading"
            ? "Préparation de la transcription locale…"
            : state?.asr?.state === "failed"
              ? state.asr.error || "Transcription locale indisponible."
              : state?.asr?.state === "disabled"
                ? "Transcription locale désactivée."
                : micLabels[microphone.phase]);
    if (avatarError) {
        $("status").textContent = "Avatar indisponible";
        return;
    }
    if (connectionError) {
        $("status").textContent = "Connexion interrompue";
        return;
    }
    if (!vrm) {
        $("status").textContent = "Chargement de l’avatar…";
        return;
    }
    if (pending) {
        $("status").textContent = "Demande en cours…";
        return;
    }
    if (freezeMotion && !active) {
        $("status").textContent = isPet ? "En pause" : "Essai arrêté";
        return;
    }
    const phase = state?.phase ?? state?.status;
    $("status").textContent =
        (isPet &&
        [
            "ready",
            "idle",
            "stopped",
            "complete",
            "completed",
            "finished",
        ].includes(phase)
            ? initiative?.paused
                ? "En pause"
                : "Dans sa boîte"
            : ((isPet ? petLabels[phase] : null) ?? labels[phase])) ??
        (state?.ready ? (active ? "Essai en cours" : "Prête") : "Préparation…");
}
function stopLocal(freeze = true) {
    const stats = { ...audio.stats };
    fence++;
    audioAllowed = false;
    freezeMotion = freeze;
    const cutoff = audio.reset(null);
    mouth?.reset();
    telemetry("client_stats", null, {
        ...stats,
        stop_request_to_mute_call_ms: cutoff,
        rendered_frames: renderedFrames,
    });
    return fence;
}
async function command(path, body) {
    petView?.cancel();
    if (path === "/stop") microphone.disable();
    else microphone.cancelInput();
    const epoch = stopLocal(path === "/stop");
    pending = true;
    showError(null);
    controls();
    try {
        if (path !== "/stop") await audio.enable();
        if (epoch !== fence) return;
        const result = await request(path, body, 20000);
        if (epoch !== fence) return;
        if (
            typeof result.session_id !== "string" ||
            !Number.isSafeInteger(result.cursor)
        )
            throw new Error("Réponse de session invalide.");
        session = result.session_id;
        cursor = result.cursor;
        active = path !== "/stop";
        audioAllowed = active;
        freezeMotion = !active;
        audio.reset(active ? session : null);
        if (path === "/start") {
            motionFrames = [];
            motionSequence = -1;
            renderedFrames = 0;
        }
    } catch (error) {
        if (epoch === fence) {
            active = false;
            audioAllowed = false;
            audio.reset();
            showError(error);
        }
    } finally {
        if (epoch === fence) {
            pending = false;
            controls();
        }
    }
}
$("start-form").onsubmit = (event) => {
    event.preventDefault();
    const scenario = $("scenario").value.trim();
    if (!scenario) {
        $("scenario").focus();
        return;
    }
    void command("/start", { scenario });
};
$("say-form").onsubmit = (event) => {
    event.preventDefault();
    const text = $("message").value.trim();
    if (!text || !connected || !state?.ready || pending) return;
    $("message").value = "";
    void command("/say", { text });
};
$("stop").onclick = () => void command("/stop", {});
$("pet-watch").onclick = async () => {
    const epoch = fence;
    pending = true;
    controls();
    try {
        await audio.enable();
        if (epoch !== fence) return;
        const result = await request("/pet_watch", {}, 20000);
        if (epoch !== fence) return;
        if (
            typeof result.session_id !== "string" ||
            !Number.isSafeInteger(result.cursor)
        )
            throw new Error("Ouverture de la boîte non confirmée.");
        if (session !== result.session_id) {
            stopLocal(false);
            session = result.session_id;
            cursor = result.cursor;
            audio.reset(session);
        } else audio.session = session;
        audioAllowed = true;
        freezeMotion = false;
        petWatching = true;
        state = { ...state, initiative: result.initiative };
        telemetry("client_stats", null, {
            ...audio.stats,
            rendered_frames: renderedFrames,
        });
    } catch (error) {
        if (epoch === fence) showError(error);
    } finally {
        pending = false;
        controls();
    }
};
$("initiative-form").onsubmit = (event) => {
    event.preventDefault();
    if (
        pending ||
        initiativeControls.pending ||
        !connected ||
        !state?.ready ||
        microphone.busy
    )
        return;
    showError(null);
    try {
        petView?.cancel();
        if (state.initiative)
            void initiativeControls.pause(
                initiativeButtonState(state.initiative, audioAllowed).paused,
            );
        else {
            const interval = $("initiative-interval").value.trim();
            void initiativeControls.configure(
                Number($("initiative-budget").value),
                interval ? Number(interval) : null,
            );
        }
    } catch (error) {
        showError(error);
    }
};
$("initiative-add-budget").onclick = () => {
    if (
        state?.mode !== "pet" ||
        !state.initiative ||
        state.initiative.remaining > 990 ||
        pending ||
        initiativeControls.pending ||
        !connected ||
        !state.ready
    )
        return;
    showError(null);
    void initiativeControls.addBudget(10);
};
$("microphone").onclick = () => {
    if (microphone.enabled) {
        microphone.disable();
        return;
    }
    // Both contexts are created/resumed in this explicit user gesture.
    const playbackReady = audio.enable();
    const microphoneReady = microphone.enable();
    const resource = microphone.resource;
    void Promise.all([playbackReady, microphoneReady]).catch((error) => {
        if (microphone.live(resource)) microphone.fail(error);
    });
};
$("wide").onclick = () => {
    room.frame();
};
$("close").onclick = () => {
    room.frame(true);
};

function receiveMotion(motion) {
    if (!vrm || freezeMotion || !motion) return;
    const sameBoneOrder =
        Array.isArray(motion.bone_names) &&
        motion.bone_names.length === boneNodes.length &&
        boneNodes.every(({ name, index }) => motion.bone_names[index] === name);
    if (
        motion.sequence === motionSequence &&
        motion.id === motionId &&
        sameBoneOrder
    )
        return;
    if (
        motion.rotation_space !== "normalized-bone-world" ||
        motion.root_space !== "world" ||
        !Array.isArray(motion.bone_names) ||
        !Array.isArray(motion.frames) ||
        motion.frames.length !== 1
    )
        throw new Error("Format des mouvements indisponible.");
    const frame = motion.frames[0];
    if (
        !Number.isSafeInteger(motion.sequence) ||
        !Number.isFinite(motion.scale) ||
        motion.scale <= 0 ||
        !Array.isArray(frame.root_position) ||
        frame.root_position.length !== 3 ||
        !frame.root_position.every(Number.isFinite) ||
        !Array.isArray(frame.rotations) ||
        frame.rotations.length !== motion.bone_names.length
    )
        throw new Error("Pose reçue invalide.");
    for (const rotation of frame.rotations)
        if (
            !Array.isArray(rotation) ||
            rotation.length !== 4 ||
            !rotation.every(Number.isFinite) ||
            Math.abs(Math.hypot(...rotation) - 1) > 0.01
        )
            throw new Error("Rotation reçue invalide.");
    if (motion.id === motionId && motion.sequence < motionSequence) return;
    if (motion.id !== motionId || !sameBoneOrder) {
        // Checkpoints and fresh preparations can serialize the same controller
        // in different bone orders. Never interpolate across those layouts.
        motionFrames = [];
        motionId = motion.id;
        motionSequence = -1;
        boneNodes = motion.bone_names
            .map((name, index) => {
                const node = vrm.humanoid.getNormalizedBoneNode(name);
                if (!node) throw new Error(`Articulation absente : ${name}`);
                let depth = 0;
                for (let p = node.parent; p; p = p.parent) depth++;
                return { name, node, index, depth };
            })
            .sort((a, b) => a.depth - b.depth);
    }
    vrm.scene.scale.setScalar(motion.scale);
    motionSequence = motion.sequence;
    const now = performance.now(),
        age = Date.now() - motion.sampled_at_unix_ms;
    const at = Number.isFinite(age) && Math.abs(age) < 2000 ? now - age : now;
    if (motionFrames.length && at <= motionFrames.at(-1).at) return;
    motionFrames.push({ at, frame });
    if (motionFrames.length > 8) motionFrames.shift();
}
function drawPose(now) {
    if (!motionFrames.length) return;
    const target = now - 100;
    let a = motionFrames[0],
        b = a;
    for (const point of motionFrames) {
        if (point.at <= target) a = point;
        else {
            b = point;
            break;
        }
        b = point;
    }
    const blend =
        a === b
            ? 0
            : THREE.MathUtils.clamp((target - a.at) / (b.at - a.at), 0, 1);
    for (const { node, index } of boneNodes) {
        node.parent.updateWorldMatrix(true, false);
        q1.fromArray(a.frame.rotations[index]).slerp(
            q2.fromArray(b.frame.rotations[index]),
            blend,
        );
        node.quaternion.copy(
            node.parent.getWorldQuaternion(parentQ).invert().multiply(q1),
        );
        node.updateMatrixWorld(true);
    }
    root.fromArray(a.frame.root_position).lerp(
        root2.fromArray(b.frame.root_position),
        blend,
    );
    hips.parent.updateWorldMatrix(true, false);
    hips.position.copy(hips.parent.worldToLocal(root));
    hips.updateMatrixWorld(true);
    vrm.scene.visible = true;
    visiblePose = true;
}
async function pollState() {
    const epoch = fence;
    const requestedSession = session;
    const duringInputStart = microphone.waitingForStart;
    const duringInitiativeChange = initiativeControls.pending;
    const duringPetChange = petInteraction.pending > 0;
    try {
        if (pending) return;
        const next = await request("/state.json", undefined, 3000);
        if (epoch !== fence) return;
        // A read begun before input_start was acknowledged may still describe
        // the previous session. Its observed body is usable, not its audio fence.
        if (requestedSession !== session) {
            receiveMotion(next.motion);
            return;
        }
        state = next;
        connected = true;
        connectionError = null;
        if (next.pet?.object_geometry && !objectVisuals)
            objectVisuals = new ObjectVisuals(scene, next.pet.object_geometry);
        if (objectVisuals && next.body_state?.observation?.objects)
            objectVisuals.display(next.body_state.observation.objects);
        const avatarPosition = next.body_state?.observation?.avatar?.position;
        if (vrm && avatarPosition)
            vrm.scene.userData.petRoot = [...avatarPosition];
        if (
            session &&
            next.session_id &&
            next.session_id !== session &&
            !duringInputStart &&
            !microphone.waitingForStart &&
            !duringInitiativeChange &&
            !initiativeControls.pending &&
            !duringPetChange &&
            !petInteraction.pending
        ) {
            microphone.cancelInput();
            stopLocal(false);
            active = false;
            session = null;
            petWatching = false;
            petView.cancel();
            showError(
                next.mode === "pet"
                    ? "La boîte a changé de session. Rouvrez-la pour activer la voix."
                    : "La session a changé. Démarrez un nouvel essai.",
            );
        }
        if (!pending) {
            if (terminal.has(next.status) || terminal.has(next.phase))
                active = false;
            else if (
                next.turn_source === "initiative" &&
                audioAllowed &&
                next.session_id === session
            )
                active = true;
        }
        if (!pending) receiveMotion(next.motion);
        microphone.observe(next.input);
        if (
            microphone.enabled &&
            ["failed", "disabled"].includes(next.asr?.state)
        )
            microphone.fail(
                new Error(
                    next.asr.error || "Transcription locale indisponible.",
                ),
            );
        if (next.error || next.body_error || next.body_presence?.error)
            showError(
                next.error ||
                    next.body_error ||
                    (next.mode === "pet"
                        ? "Les gestes au repos sont interrompus. Cliquez sur Pause de vie, puis Reprendre pour réessayer."
                        : next.body_presence.error),
            );
    } catch (error) {
        if (epoch !== fence) return;
        connectionError = message(error);
        connected = false;
        petView.cancel();
        microphone.disable();
        if (audioAllowed) {
            stopLocal(true);
            active = false;
        }
        showError(error);
    } finally {
        controls();
        setTimeout(pollState, 50);
    }
}
async function pollEvents() {
    const epoch = fence;
    try {
        if (!audioAllowed || !session || pending) return;
        const next = await request(`/events?after=${cursor}`, undefined, 3000);
        if (epoch !== fence || next.session_id !== session || !audioAllowed)
            return;
        cursor = consumeEvents(next, session, cursor, (event) => {
            if (!audioAllowed) return;
            if (
                handleSessionStop(event, {
                    disableMicrophone: () => microphone.disable(),
                    stopLocal,
                    resumeEvents: () => {
                        // A delayed audio-only stop must not undo a newer resume.
                        audio.session = session;
                        audioAllowed = true;
                    },
                    onStopped: () => {
                        active = false;
                        controls();
                    },
                })
            )
                return;
            audio.accept(event);
        });
    } catch (error) {
        if (epoch === fence) {
            microphone.disable();
            stopLocal(true);
            active = false;
            showError(error);
            controls();
        }
    } finally {
        setTimeout(pollEvents, 35);
    }
}
new ResizeObserver(() => {
    const { clientWidth: w, clientHeight: h } = $("stage");
    if (!w || !h) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
}).observe($("stage"));
renderer.setAnimationLoop((now) => {
    const dt = lastNow ? Math.min(0.1, (now - lastNow) / 1000) : 0;
    lastNow = now;
    if (vrm) {
        if (!freezeMotion) drawPose(now);
        mouth?.update(audio.renderedRms, dt);
        const phase = (now / 1000 + 1.2) % 4.3;
        vrm.expressionManager?.setValue(
            "blink",
            phase < 0.16 ? Math.sin((phase / 0.16) * Math.PI) : 0,
        );
        vrm.update(Math.min(dt, 0.034));
    }
    orbit.update();
    petView.update();
    renderer.render(scene, camera);
    if (active && visiblePose) renderedFrames++;
});
try {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync("/avatar.vrm");
    vrm = gltf.userData.vrm;
    if (!vrm) throw new Error("Le modèle VRM est absent.");
    mouth = new AudioMouth(vrm.expressionManager);
    if (!mouth.expression)
        throw new Error(
            "Cet avatar ne possède aucune ouverture de bouche compatible.",
        );
    hips = vrm.humanoid.getNormalizedBoneNode("hips");
    vrm.scene.visible = false;
    scene.add(vrm.scene);
    vrm.scene.traverse((node) => {
        if (node.isMesh) {
            node.castShadow = true;
            node.receiveShadow = true;
            node.frustumCulled = false;
        }
    });
    vrm.update(0);
    scene.updateMatrixWorld(true);
} catch (error) {
    avatarError = message(error);
    showError(error);
}
controls();
void pollState();
void pollEvents();
setInterval(() => {
    if (
        shouldSendClientStats({
            session,
            audioAllowed,
            active,
            initiative: state?.initiative,
            petMode,
            petWatching,
            visible: document.visibilityState === "visible",
        })
    )
        telemetry("client_stats", null, {
            ...audio.stats,
            rendered_frames: renderedFrames,
        });
}, 5000);
addEventListener("pagehide", () => {
    petView.cancel();
    microphone.disable();
    stopLocal(true);
});
window.arianeRealtime = {
    stats: () => ({
        ...audio.stats,
        session_id: session,
        active,
        cursor,
        motion_sequence: motionSequence,
        avatar_visible: visiblePose,
        mouth_expression: mouth?.expression,
        mouth_weight: mouth?.value,
        rendered_rms: audio.renderedRms,
        microphone: microphone.snapshot(),
        initiative: state?.initiative ?? null,
        turn_source: state?.turn_source ?? null,
    }),
    stopLocal: () => {
        microphone.disable();
        stopLocal(true);
        active = false;
        controls();
    },
};
