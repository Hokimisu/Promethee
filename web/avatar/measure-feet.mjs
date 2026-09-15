// Geometry qualification only: omit textures, but load the same VRM skin and constraints.
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { Box3, Texture, Vector3 } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import { CoreRetarget, validateArmProfile } from "./retarget.js";
import { FootGeometry, footSurfaceSummary } from "./foot-geometry.js";
import { FootPlantingTrial } from "./foot-planting-trial.js";

const [avatarPath, motionPath, outputPath, mode] = process.argv.slice(2);
if (mode && !["--settle", "--plant"].includes(mode))
    throw new Error("Unknown measurement option.");
if (!avatarPath || !motionPath || !outputPath)
    throw new Error(
        "Usage: node measure-feet.mjs AVATAR.vrm MOTION.json REPORT.json",
    );
const bytes = readFileSync(avatarPath);
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
if (
    sha256(bytes) !==
    "12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2"
)
    throw new Error("Use the qualified pixiv asset.");
const motionBytes = readFileSync(motionPath);
const data = JSON.parse(motionBytes);
if (
    !Array.isArray(data.frames) ||
    data.frames.length < 1 ||
    data.frames.length > 1200
)
    throw new Error("Expected 1 to 1200 frames exported by the avatar viewer.");
const loader = new GLTFLoader();
loader.register((parser) => {
    parser.loadTexture = async () => new Texture();
    return new VRMLoaderPlugin(parser);
});
const gltf = await loader.parseAsync(
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    "",
);
const vrm = gltf.userData.vrm;
vrm.update(0);
vrm.scene.updateMatrixWorld(true);
const hipY = vrm.humanoid
    .getNormalizedBoneNode("hips")
    .getWorldPosition(new Vector3()).y;
const scale =
    -Math.min(...data.skeleton.neutral_joints.map((p) => p[1])) /
    (hipY - new Box3().setFromObject(vrm.scene, true).min.y);
validateArmProfile(vrm, data.skeleton, scale, data.avatar_profile);
const retarget = new CoreRetarget(vrm, data.skeleton, scale);
const geometry = new FootGeometry(vrm);
const hands = [
    ...new Set(
        (data.objects ?? []).flatMap((objects) =>
            Object.values(objects).flatMap((obj) =>
                obj.spatial.attachment ? [obj.spatial.attachment.joint] : [],
            ),
        ),
    ),
];
const samples = [];
const offsets = [];
let maximumHandError = 0;
let maximumHipError = 0;
let maximumJointStep = 0;
let previousJoints = null;
let failure = null;
let planting;
try {
    if (mode === "--plant") {
        const collect = new FootPlantingTrial(vrm, retarget, geometry, {
            collect: true,
        });
        for (const [index, frame] of data.frames.entries())
            collect.apply(frame, data.foot_contacts?.[index], hands);
        const plan = [...collect.required];
        for (let i = 1; i < plan.length; i++)
            plan[i] = Math.max(plan[i], plan[i - 1] - 0.013);
        for (let i = plan.length - 2; i >= 0; i--)
            plan[i] = Math.max(plan[i], plan[i + 1] - 0.013);
        planting = new FootPlantingTrial(vrm, retarget, geometry, { plan });
    }
    for (const [index, frame] of data.frames.entries()) {
        retarget.apply(frame, hands);
        let offset = 0;
        if (mode === "--plant")
            offset = planting.apply(frame, data.foot_contacts?.[index], hands);
        if (mode === "--settle") {
            const before = geometry.sample();
            offset = -Math.min(
                ...Object.values(before).flatMap((foot) =>
                    foot.map((p) => p[1]),
                ),
            );
            if (Math.abs(offset) > 0.05)
                throw new Error("VRM settling exceeds 5 cm.");
            if (offsets.length && Math.abs(offset - offsets.at(-1)) > 0.015)
                throw new Error(
                    "VRM settling changes by more than 15 mm/frame.",
                );
            const positions = frame.positions.map((p) => [...p]);
            positions[0][1] += offset;
            // Preserve observed hand targets; only the appearance pelvis is lowered.
            retarget.apply({ ...frame, positions }, hands);
        }
        offsets.push(offset);
        if (
            offsets.length > 1 &&
            Math.abs(offset - offsets.at(-2)) > 0.015 + 1e-8
        )
            throw new Error(
                "Combined VRM root correction exceeds 15 mm/frame.",
            );
        for (const hand of hands) {
            const bone = hand === "RightHand" ? "rightHand" : "leftHand";
            maximumHandError = Math.max(
                maximumHandError,
                vrm.humanoid
                    .getRawBoneNode(bone)
                    .getWorldPosition(new Vector3())
                    .distanceTo(
                        new Vector3(
                            ...frame.positions[
                                data.skeleton.joint_names.indexOf(hand)
                            ],
                        ),
                    ),
            );
        }
        maximumHipError = Math.max(
            maximumHipError,
            vrm.humanoid
                .getRawBoneNode("hips")
                .getWorldPosition(new Vector3())
                .distanceTo(new Vector3(...frame.positions[0])),
        );
        samples.push(geometry.sample());
        const joints = retarget.bones.map(({ node }) =>
            node.getWorldPosition(new Vector3()),
        );
        if (previousJoints)
            maximumJointStep = Math.max(
                maximumJointStep,
                ...joints.map((point, i) =>
                    point.distanceTo(previousJoints[i]),
                ),
            );
        previousJoints = joints;
    }
} catch (error) {
    failure = error.message;
}
const speeds = [];
for (let t = 1; t < samples.length; t++) {
    for (const side of ["left", "right"]) {
        samples[t][side].forEach((p, index) => {
            const previous = samples[t - 1][side][index];
            if (Math.abs(p[1]) <= 0.0001 && Math.abs(previous[1]) <= 0.0001)
                speeds.push(
                    Math.hypot(p[0] - previous[0], p[2] - previous[2]) * 20,
                );
        });
    }
}
speeds.sort((a, b) => a - b);
const at95 = (speeds.length - 1) * 0.95;
const report = {
    purpose: "VRM geometry qualification; exclude from personal memory",
    error: failure,
    frames_requested: data.frames.length,
    frames_measured: samples.length,
    avatar_sha256: sha256(bytes),
    motion_sha256: sha256(motionBytes),
    measurement_source_sha256: sha256(readFileSync(new URL(import.meta.url))),
    planting_source_sha256: sha256(
        readFileSync(new URL("./foot-planting-trial.js", import.meta.url)),
    ),
    uniform_scale: scale,
    maximum_joint_step_m: samples.length > 1 ? maximumJointStep : null,
    maximum_hip_error_m: samples.length ? maximumHipError : null,
    maximum_attached_hand_error_m:
        samples.length && hands.length ? maximumHandError : null,
    measured_attached_hands: hands,
    minimum_root_offset_m: offsets.length ? Math.min(...offsets) : null,
    maximum_root_offset_m: offsets.length ? Math.max(...offsets) : null,
    root_offsets_m: offsets,
    surface_vertex_pairs: speeds.length,
    surface_speed_max_m_s: speeds.at(-1) ?? null,
    surface_speed_p95_m_s: speeds.length
        ? speeds[Math.floor(at95)] +
          (speeds[Math.ceil(at95)] - speeds[Math.floor(at95)]) * (at95 % 1)
        : null,
    foot_surface: samples.length ? footSurfaceSummary(samples) : null,
    frames_with_any_surface_contact: samples.filter((sample) =>
        Object.values(sample).some((foot) =>
            foot.some((p) => Math.abs(p[1]) <= 0.0001),
        ),
    ).length,
    contact_tolerance_m: 0.0001,
    textures_loaded: false,
    floor_correction_applied: Boolean(mode) && samples.length > 0,
    correction_mode: mode ?? "none",
    physical_support_validated: false,
};
writeFileSync(outputPath, JSON.stringify(report, null, 2), { flag: "wx" });
console.log(JSON.stringify(report, null, 2));
