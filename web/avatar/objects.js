import { Group, Mesh, SphereGeometry, MeshStandardMaterial } from "three";
import { rotationQuaternion } from "./retarget.js";

export class ObjectVisuals {
    constructor(scene, models) {
        this.scene = scene;
        this.models = models;
        this.nodes = new Map();
    }

    display(objects) {
        for (const [id, entry] of this.nodes) {
            if (!(id in objects) || objects[id].asset !== entry.asset) {
                entry.node.traverse((part) => {
                    part.geometry?.dispose();
                    part.material?.dispose();
                });
                this.scene.remove(entry.node);
                this.nodes.delete(id);
            }
        }
        for (const [id, object] of Object.entries(objects)) {
            if (!this.nodes.has(id)) {
                const parts = this.models[object.asset];
                if (!parts)
                    throw new Error(`Modèle d’objet absent : ${object.asset}`);
                const node = new Group();
                for (const part of parts) {
                    const mesh = new Mesh(
                        new SphereGeometry(0.5, 20, 12),
                        new MeshStandardMaterial({
                            color: part.color,
                            roughness: 0.9,
                        }),
                    );
                    mesh.position.fromArray(part.center);
                    mesh.scale.fromArray(part.size);
                    node.add(mesh);
                }
                this.scene.add(node);
                this.nodes.set(id, { node, asset: object.asset });
            }
            const node = this.nodes.get(id).node;
            node.position.fromArray(object.spatial.position);
            node.quaternion.copy(rotationQuaternion(object.spatial.rotation));
            node.updateMatrixWorld(true);
        }
    }
}
