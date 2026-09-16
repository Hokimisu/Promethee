import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";

export function createRoom(host) {
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.append(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#171921");
    const camera = new THREE.PerspectiveCamera(
        36,
        host.clientWidth / host.clientHeight,
        0.05,
        100,
    );
    camera.position.set(1.6, 1.8, 5.8);
    const orbit = new OrbitControls(camera, renderer.domElement);
    orbit.target.set(-0.15, 1.05, -0.6);
    orbit.enableDamping = true;
    orbit.minDistance = 2;
    orbit.maxDistance = 11;
    orbit.maxPolarAngle = Math.PI * 0.48;
    orbit.update();
    scene.add(new THREE.HemisphereLight(0xdbe7ff, 0x6c5555, 2.0));
    const key = new THREE.DirectionalLight(0xffd7ad, 2.9);
    key.position.set(-3, 5, 4);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -5;
    key.shadow.camera.right = 5;
    key.shadow.camera.top = 5;
    key.shadow.camera.bottom = -5;
    key.shadow.normalBias = 0.015;
    key.shadow.bias = -0.0002;
    scene.add(key);
    const fill = new THREE.PointLight(0x819dff, 13, 8);
    fill.position.set(-2, 2.3, -1.8);
    scene.add(fill);
    const warm = new THREE.PointLight(0xffad63, 9, 5);
    warm.position.set(2.5, 1.8, -1.8);
    scene.add(warm);
    const materials = {};
    function material(color) {
        return (materials[color] ??= new THREE.MeshStandardMaterial({
            color,
            roughness: 0.82,
        }));
    }
    function box(x, y, z, w, h, d, color) {
        const mesh = new THREE.Mesh(
            new THREE.BoxGeometry(w, h, d),
            material(color),
        );
        mesh.position.set(x, y, z);
        mesh.receiveShadow = true;
        mesh.castShadow = true;
        scene.add(mesh);
        return mesh;
    }
    box(0, -0.12, 0, 7, 0.18, 7, "#4b3731");
    for (let i = 0; i < 22; i++)
        box(
            -3.34 + i * 0.318,
            -0.009,
            0,
            0.31,
            0.018,
            7,
            i % 3 ? "#aa8365" : "#997256",
        );
    box(0, 1.65, -2.7, 7, 3.3, 0.15, "#a58c83");
    box(-3.45, 1.65, 0.0, 0.15, 3.3, 5.5, "#807c91");
    box(0, 0.08, -2.57, 7, 0.16, 0.07, "#d8c5b2");
    box(-3.35, 0.08, 0, 0.07, 0.16, 5.5, "#d8c5b2");
    // Stage entrance; the door stays ajar throughout this rehearsal.
    box(0.45, 1.13, -2.59, 1.14, 2.26, 0.045, "#35303a");
    box(-0.16, 1.17, -2.53, 0.09, 2.36, 0.1, "#d4bb9c");
    box(1.06, 1.17, -2.53, 0.09, 2.36, 0.1, "#d4bb9c");
    box(0.45, 2.31, -2.53, 1.31, 0.09, 0.1, "#d4bb9c");
    const door = box(1.35, 1.1, -2.03, 1.08, 2.2, 0.06, "#68504b");
    door.rotation.y = -1.08;
    // Window and evening sky.
    box(-1.85, 1.86, -2.58, 1.73, 1.53, 0.07, "#d0c0b9");
    const windowPane = box(-1.85, 1.86, -2.526, 1.55, 1.35, 0.03, "#657ba7");
    windowPane.material = new THREE.MeshStandardMaterial({
        color: 0x566a92,
        emissive: 0x485e85,
        emissiveIntensity: 0.7,
    });
    box(-1.85, 1.86, -2.48, 0.045, 1.35, 0.04, "#cdb9ab");
    box(-1.85, 1.86, -2.48, 1.55, 0.045, 0.04, "#cdb9ab");
    box(-1.85, 1.13, -2.4, 1.85, 0.08, 0.29, "#e1c6aa");
    // Sofa and a table stay outside Ariane's path.
    box(2.23, 0.23, -1.28, 1.8, 0.32, 0.91, "#514956");
    box(2.23, 0.67, -1.7, 1.8, 0.7, 0.2, "#726477");
    box(1.32, 0.54, -1.27, 0.18, 0.7, 0.93, "#726477");
    box(3.14, 0.54, -1.27, 0.18, 0.7, 0.93, "#726477");
    box(1.78, 0.46, -1.26, 0.78, 0.18, 0.75, "#92819a");
    box(2.66, 0.46, -1.26, 0.78, 0.18, 0.75, "#92819a");
    const cushion = box(2.85, 0.8, -1.54, 0.4, 0.4, 0.14, "#cfaa8c");
    cushion.rotation.z = -0.18;
    box(2.35, 0.22, 0.1, 1.15, 0.07, 0.66, "#715344");
    for (const x of [1.9, 2.8])
        for (const z of [-0.13, 0.33])
            box(x, 0.1, z, 0.06, 0.22, 0.06, "#3c3030");
    box(-2.55, 0.34, -1.6, 0.65, 0.06, 0.6, "#ac8968");
    box(-2.55, 0.16, -1.6, 0.05, 0.32, 0.05, "#51423d");
    const pot = new THREE.Mesh(
        new THREE.CylinderGeometry(0.18, 0.14, 0.3, 24),
        material("#b37c63"),
    );
    pot.position.set(-2.65, 0.15, -2.1);
    scene.add(pot);
    for (let i = 0; i < 7; i++) {
        const leaf = new THREE.Mesh(
            new THREE.SphereGeometry(1, 12, 8),
            material(i % 2 ? "#596854" : "#6d775b"),
        );
        leaf.scale.set(0.09, 0.42, 0.035);
        leaf.position.set(
            -2.65 + Math.sin(i * 2.4) * 0.18,
            0.55 + Math.cos(i) * 0.08,
            -2.1 + Math.cos(i * 2.4) * 0.16,
        );
        leaf.rotation.z = Math.sin(i * 2.4) * 0.45;
        leaf.rotation.y = i;
        scene.add(leaf);
    }
    box(2.82, 1.1, -2.36, 0.035, 1.85, 0.035, "#dbc4a0");
    const shade = new THREE.Mesh(
        new THREE.ConeGeometry(0.29, 0.35, 40, 1, true),
        new THREE.MeshStandardMaterial({
            color: 0xeacba7,
            side: THREE.DoubleSide,
        }),
    );
    shade.position.set(2.82, 1.9, -2.36);
    scene.add(shade);

    return { renderer, scene, camera, orbit };
}
