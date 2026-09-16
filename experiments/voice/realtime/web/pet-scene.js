import * as THREE from "three";

/** Hit tests real observed instances; the marker is never the authoritative object. */
export class PetScene {
    constructor({
        renderer,
        scene,
        camera,
        orbit,
        interaction,
        objects,
        avatar,
        enabled,
        geometry,
    }) {
        Object.assign(this, {
            renderer,
            scene,
            camera,
            orbit,
            interaction,
            objects,
            avatar,
            enabled,
            geometry,
        });
        this.canvas = renderer.domElement;
        this.ray = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();
        this.plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
        this.point = new THREE.Vector3();
        this.pointer = null;
        this.height = 0;
        this.planarAvatar = false;
        this.offset = new THREE.Vector3();
        this.marker = new THREE.Group();
        const ink = new THREE.MeshBasicMaterial({
            color: "#a75235",
            transparent: true,
            opacity: 0.65,
            depthTest: false,
        });
        this.ring = new THREE.Mesh(
            new THREE.TorusGeometry(0.18, 0.008, 8, 48),
            ink,
        );
        this.ring.rotation.x = Math.PI / 2;
        this.marker.add(this.ring);
        this.ghost = new THREE.Mesh(
            new THREE.CylinderGeometry(0.13, 0.18, 1, 20, 1, true),
            new THREE.MeshBasicMaterial({
                color: "#a75235",
                transparent: true,
                opacity: 0.12,
                depthWrite: false,
                side: THREE.DoubleSide,
            }),
        );
        this.marker.add(this.ghost);
        this.arrow = new THREE.ArrowHelper(
            new THREE.Vector3(1, 0, 0),
            new THREE.Vector3(),
            1,
            0xa75235,
            0.13,
            0.07,
        );
        this.marker.add(this.arrow);
        this.marker.visible = false;
        scene.add(this.marker);
        this.canvas.addEventListener(
            "pointerdown",
            (event) => this.down(event),
            true,
        );
        this.canvas.addEventListener(
            "pointermove",
            (event) => this.move(event),
            true,
        );
        this.canvas.addEventListener(
            "pointerup",
            (event) => this.up(event),
            true,
        );
        this.canvas.addEventListener(
            "pointercancel",
            () => this.cancel(),
            true,
        );
        this.canvas.addEventListener("lostpointercapture", () => {
            if (this.pointer !== null) this.cancel();
        });
    }
    cast(event) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouse.set(
            ((event.clientX - rect.left) / rect.width) * 2 - 1,
            1 - ((event.clientY - rect.top) / rect.height) * 2,
        );
        this.ray.setFromCamera(this.mouse, this.camera);
    }
    onPlane(event, height) {
        this.cast(event);
        this.plane.constant = -height;
        const point = this.ray.ray.intersectPlane(this.plane, this.point);
        return point ? point.clone() : null;
    }
    pick(event) {
        this.cast(event);
        const candidates = [];
        const rect = this.canvas.getBoundingClientRect();
        for (const [id, entry] of this.objects()?.nodes ?? []) {
            const hit = this.ray.intersectObject(entry.node, true)[0];
            // Tiny real objects get a 16px pointer target; no extra object is rendered.
            const world = entry.node.getWorldPosition(new THREE.Vector3());
            const projected = world.clone().project(this.camera);
            const pixels = Math.hypot(
                ((projected.x - this.mouse.x) * rect.width) / 2,
                ((projected.y - this.mouse.y) * rect.height) / 2,
            );
            if (hit || (pixels <= 16 && projected.z >= -1 && projected.z <= 1))
                candidates.push({
                    distance:
                        hit?.distance ?? this.camera.position.distanceTo(world),
                    target: { kind: "object", id, asset: entry.asset },
                    point: world,
                });
        }
        const avatar = this.avatar();
        if (avatar?.visible && this.interaction.mode !== "throw") {
            // Moving hips changes the skinned vertices, not necessarily mesh.matrixWorld.
            // Three caches these bounds after the first pick; refresh only on pointerdown.
            avatar.updateWorldMatrix(true, true);
            avatar.traverse((node) => {
                if (!node.isSkinnedMesh) return;
                node.computeBoundingSphere();
                if (node.boundingBox !== null) node.computeBoundingBox();
            });
            const hit = this.ray.intersectObject(avatar, true)[0];
            if (hit) {
                candidates.push({
                    distance: hit.distance,
                    target: { kind: "avatar" },
                    point: hit.point.clone(),
                });
            }
        }
        return candidates.sort((a, b) => a.distance - b.distance)[0] ?? null;
    }
    floor(model) {
        const parts = this.geometry()?.[model];
        if (!Array.isArray(parts) || !parts.length) return null;
        if (model === "plush" && this.interaction.placement === "high")
            return 1.25;
        return Math.max(
            0,
            -Math.min(
                ...parts.map((part) => part.center[1] - part.size[1] / 2),
            ),
        );
    }
    down(event) {
        if (!this.enabled() || event.button !== 0 || this.interaction.busy)
            return;
        if (this.interaction.model) {
            const height = this.floor(this.interaction.model);
            const point = height === null ? null : this.onPlane(event, height);
            if (!point) return;
            event.stopImmediatePropagation();
            event.preventDefault();
            void this.interaction.spawn(point.toArray());
            return;
        }
        const hit = this.pick(event);
        if (
            !hit ||
            (this.interaction.mode === "throw" && hit.target.asset !== "ball")
        )
            return;
        this.planarAvatar = hit.target.kind === "avatar";
        this.height = hit.point.y;
        const point = this.onPlane(event, this.height);
        if (!point) return;
        // The root can be obtained independently of the mesh point being clicked.
        if (this.planarAvatar) {
            const root = this.avatar().userData.petRoot;
            if (!Array.isArray(root)) return;
            hit.point.set(root[0], 0, root[1]);
        }
        this.offset.copy(hit.point).sub(point);
        this.pointer = event.pointerId;
        this.orbit.enabled = false;
        this.canvas.setPointerCapture(event.pointerId);
        event.stopImmediatePropagation();
        event.preventDefault();
        void this.interaction.begin(hit.target, hit.point.toArray());
    }
    move(event) {
        if (this.pointer !== event.pointerId) return;
        const point = this.onPlane(event, this.height);
        if (point) {
            point.add(this.offset);
            if (this.planarAvatar) point.y = 0;
            this.interaction.move(point.toArray());
        }
        event.stopImmediatePropagation();
        event.preventDefault();
    }
    detachPointer() {
        const pointer = this.pointer;
        this.pointer = null;
        if (pointer !== null && this.canvas.hasPointerCapture(pointer))
            this.canvas.releasePointerCapture(pointer);
        this.orbit.enabled = true;
    }
    up(event) {
        if (this.pointer !== event.pointerId) return;
        this.move(event);
        this.detachPointer();
        void this.interaction.release();
        event.stopImmediatePropagation();
    }
    cancel() {
        this.detachPointer();
        void this.interaction.cancel();
    }
    update() {
        const operation = this.interaction.operation;
        this.marker.visible = Boolean(operation && this.enabled());
        if (!operation) {
            if (this.pointer !== null) this.detachPointer();
            return;
        }
        const point =
            operation.mode === "throw" ? operation.origin : operation.point;
        this.ring.position.set(point[0], 0.015, point[2]);
        this.ghost.visible = operation.mode !== "throw";
        const size = operation.target.kind === "avatar" ? 1.65 : 0.2;
        this.ghost.scale.set(1, size, 1);
        this.ghost.position.set(point[0], point[1] + size / 2, point[2]);
        this.arrow.visible = operation.mode === "throw";
        if (this.arrow.visible) {
            const delta = new THREE.Vector3()
                .fromArray(operation.point)
                .sub(new THREE.Vector3().fromArray(operation.origin));
            delta.y = 0;
            const length = delta.length();
            this.arrow.position
                .fromArray(operation.origin)
                .add(new THREE.Vector3(0, 0.04, 0));
            if (length > 0.01) {
                this.arrow.setDirection(delta.normalize());
                this.arrow.setLength(
                    length,
                    Math.min(0.2, length * 0.2),
                    Math.min(0.1, length * 0.1),
                );
            } else this.arrow.visible = false;
        }
    }
}
