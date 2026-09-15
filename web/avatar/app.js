import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import { CoreRetarget } from "./retarget.js";
import { ObjectVisuals } from "./objects.js";

const status = document.querySelector("#status"),
    slider = document.querySelector("#frame");
const play = document.querySelector("#play"),
    metrics = document.querySelector("#metrics");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.querySelector("#scene").append(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color("#20272a");
const camera = new THREE.PerspectiveCamera(
    35,
    innerWidth / innerHeight,
    0.01,
    100,
);
camera.position.set(2.6, 1.7, 4.2);
const orbit = new OrbitControls(camera, renderer.domElement);
orbit.target.set(0, 0.95, 0);
orbit.minDistance = 1;
orbit.maxDistance = 14;
orbit.maxPolarAngle = Math.PI * 0.49;
orbit.update();
scene.add(new THREE.HemisphereLight(0xffffff, 0x657573, 1.2));
const light = new THREE.DirectionalLight(0xffffff, 1.3);
light.position.set(2, 4, 3);
scene.add(light);
const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(20, 20),
    new THREE.MeshStandardMaterial({ color: "#303b3d", roughness: 1 }),
);
floor.rotation.x = -Math.PI / 2;
floor.position.y = -0.001;
scene.add(floor);
const grid = new THREE.GridHelper(10, 10, 0x536160, 0x3b4949);
grid.position.y = 0.001;
scene.add(grid);
addEventListener("resize", () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
});
renderer.setAnimationLoop(() => renderer.render(scene, camera));

try {
    const response = await fetch("/motion.json");
    if (!response.ok) throw new Error("Mouvement inaccessible.");
    const data = await response.json();
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync("/avatar.vrm");
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error("Le fichier ne contient pas de VRM.");
    scene.add(vrm.scene);
    vrm.update(0);
    scene.updateMatrixWorld(true);
    const restBounds = new THREE.Box3().setFromObject(vrm.scene, true);
    const hipY = vrm.humanoid
        .getNormalizedBoneNode("hips")
        .getWorldPosition(new THREE.Vector3()).y;
    const coreHipHeight = -Math.min(
        ...data.skeleton.neutral_joints.map((point) => point[1]),
    );
    const scale = coreHipHeight / (hipY - restBounds.min.y);
    if (!Number.isFinite(scale) || scale < 0.5 || scale > 2)
        throw new Error("Échelle de squelette incompatible.");
    const retarget = new CoreRetarget(vrm, data.skeleton, scale);
    const objects = new ObjectVisuals(scene, data.object_models ?? {});
    const attachedHands = [
        ...new Set(
            (data.objects ?? []).flatMap((frame) =>
                Object.values(frame).flatMap((object) =>
                    object.spatial.attachment
                        ? [object.spatial.attachment.joint]
                        : [],
                ),
            ),
        ),
    ];
    // Check the full clip before enabling playback, including the approach.
    vrm.scene.visible = false;
    if (attachedHands.length) {
        for (const frame of data.frames) retarget.apply(frame, attachedHands);
    }
    vrm.scene.visible = true;
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
    document.querySelector("#skeleton").onchange = (event) => {
        source.visible = event.target.checked;
    };
    let index = 0,
        playing = false,
        anchor = 0,
        anchorFrame = 0;
    function display(frame) {
        index = frame;
        retarget.apply(data.frames[index], attachedHands);
        objects.display(data.objects?.[index] ?? {});
        geometry.attributes.position.array.set(
            edges.flatMap((edge) =>
                edge.flatMap((joint) => data.frames[index].positions[joint]),
            ),
        );
        geometry.attributes.position.needsUpdate = true;
        slider.value = index;
        document.querySelector("#time").textContent =
            `${(index / data.fps).toFixed(1)} s`;
    }
    function pause() {
        playing = false;
        play.textContent = "Lire";
    }
    slider.max = data.frames.length - 1;
    slider.disabled = false;
    play.disabled = false;
    slider.oninput = () => {
        pause();
        display(Number(slider.value));
    };
    play.onclick = () => {
        if (playing) {
            pause();
            return;
        }
        if (index === data.frames.length - 1) display(0);
        playing = true;
        anchor = performance.now();
        anchorFrame = index;
        play.textContent = "Pause";
    };
    renderer.setAnimationLoop((now) => {
        if (playing) {
            const frame = Math.min(
                data.frames.length - 1,
                anchorFrame + Math.floor(((now - anchor) * data.fps) / 1000),
            );
            if (frame !== index) display(frame);
            if (frame === data.frames.length - 1) pause();
        }
        renderer.render(scene, camera);
    });
    display(0);
    const roots = data.frames.map((frame) => frame.positions[0]);
    const mid = (axis) =>
        (Math.min(...roots.map((point) => point[axis])) +
            Math.max(...roots.map((point) => point[axis]))) /
        2;
    orbit.target.set(mid(0), 1, mid(2));
    camera.position.set(mid(0) + 3, 2, mid(2) + 5.3);
    orbit.update();
    status.textContent = `Mouvement enregistré · ${data.frames.length} poses · cinématique`;
    const measure = document.querySelector("#measure");
    measure.disabled = false;
    measure.onclick = async () => {
        pause();
        measure.disabled = true;
        play.disabled = true;
        slider.disabled = true;
        const saved = index;
        let minimum = Infinity,
            highestMinimum = -Infinity,
            maxRootError = 0;
        const handErrors = { rightHand: 0, leftHand: 0 };
        const meshes = [];
        vrm.scene.traverse((node) => {
            if (node.isSkinnedMesh) meshes.push(node);
        });
        const point = new THREE.Vector3(),
            actual = new THREE.Vector3();
        for (let i = 0; i < data.frames.length; i++) {
            display(i);
            let frameMinimum = Infinity;
            vrm.humanoid.getRawBoneNode("hips").getWorldPosition(actual);
            maxRootError = Math.max(
                maxRootError,
                actual.distanceTo(
                    new THREE.Vector3(...data.frames[i].positions[0]),
                ),
            );
            for (const [name, joint] of [
                ["rightHand", "RightHand"],
                ["leftHand", "LeftHand"],
            ]) {
                vrm.humanoid.getRawBoneNode(name).getWorldPosition(actual);
                const expected =
                    data.frames[i].positions[
                        data.skeleton.joint_names.indexOf(joint)
                    ];
                handErrors[name] = Math.max(
                    handErrors[name],
                    actual.distanceTo(new THREE.Vector3(...expected)),
                );
            }
            for (const mesh of meshes) {
                mesh.skeleton.update();
                for (
                    let vertex = 0;
                    vertex < mesh.geometry.attributes.position.count;
                    vertex++
                ) {
                    mesh.getVertexPosition(vertex, point).applyMatrix4(
                        mesh.matrixWorld,
                    );
                    frameMinimum = Math.min(frameMinimum, point.y);
                }
            }
            minimum = Math.min(minimum, frameMinimum);
            highestMinimum = Math.max(highestMinimum, frameMinimum);
            if (i % 10 === 0) {
                metrics.textContent = `Mesure : ${i + 1}/${data.frames.length}`;
                await new Promise((resolve) => requestAnimationFrame(resolve));
            }
        }
        display(saved);
        metrics.textContent = JSON.stringify(
            {
                frames: data.frames.length,
                uniform_scale: scale,
                maximum_hip_error_m: maxRootError,
                maximum_hand_error_m: handErrors,
                objects_follow_observed_world_transform: true,
                attached_hand_alignment_applied: attachedHands.length > 0,
                grasp_validated: false,
                lowest_rendered_vertex_y_m: minimum,
                maximum_floor_penetration_m: Math.max(0, -minimum),
                highest_lowest_vertex_y_m: highestMinimum,
                floor_correction_applied: false,
                foot_support_validated: false,
            },
            null,
            2,
        );
        measure.disabled = false;
        play.disabled = false;
        slider.disabled = false;
    };
} catch (error) {
    status.textContent = `Affichage indisponible : ${error.message}`;
}
