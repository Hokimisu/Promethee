// Geometry qualification only: omit textures, but load the same VRM skin and constraints.
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { Box3, Texture, Vector3 } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import { CoreRetarget, validateArmProfile } from "./retarget.js";
import { FootGeometry, footSurfaceSummary } from "./foot-geometry.js";

const [avatarPath, motionPath, outputPath] = process.argv.slice(2);
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
let maximumHipError = 0;
for (const frame of data.frames) {
    retarget.apply(frame, hands);
    maximumHipError = Math.max(
        maximumHipError,
        vrm.humanoid
            .getRawBoneNode("hips")
            .getWorldPosition(new Vector3())
            .distanceTo(new Vector3(...frame.positions[0])),
    );
    samples.push(geometry.sample());
}
const report = {
    purpose: "VRM geometry qualification; exclude from personal memory",
    avatar_sha256: sha256(bytes),
    motion_sha256: sha256(motionBytes),
    uniform_scale: scale,
    maximum_hip_error_m: maximumHipError,
    foot_surface: footSurfaceSummary(samples),
    frames_with_any_surface_contact: samples.filter((sample) =>
        Object.values(sample).some((foot) =>
            foot.some((p) => Math.abs(p[1]) <= 0.0001),
        ),
    ).length,
    contact_tolerance_m: 0.0001,
    textures_loaded: false,
    floor_correction_applied: false,
    physical_support_validated: false,
};
writeFileSync(outputPath, JSON.stringify(report, null, 2), { flag: "wx" });
console.log(JSON.stringify(report, null, 2));
