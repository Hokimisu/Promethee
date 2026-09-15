import { Vector3 } from "three";

// Select skin vertices attached mostly to the actual foot/toe bone hierarchy.
// The normalized animation bones are not the indices used by the skin.
export class FootGeometry {
    constructor(vrm) {
        this.vrm = vrm;
        this.feet = {};
        for (const side of ["left", "right"]) {
            const foot = vrm.humanoid.getRawBoneNode(`${side}Foot`);
            if (!foot) throw new Error(`Pied VRM absent : ${side}.`);
            const descendants = new Set();
            foot.traverse((node) => descendants.add(node));
            const selected = [];
            vrm.scene.traverse((mesh) => {
                if (!mesh.isSkinnedMesh) return;
                const bones = new Set(
                    mesh.skeleton.bones.flatMap((bone, index) =>
                        descendants.has(bone) ? [index] : [],
                    ),
                );
                const indices = mesh.geometry.attributes.skinIndex;
                const weights = mesh.geometry.attributes.skinWeight;
                const vertices = [];
                for (let vertex = 0; vertex < indices.count; vertex++) {
                    let weight = 0;
                    for (let slot = 0; slot < 4; slot++)
                        if (bones.has(indices.getComponent(vertex, slot)))
                            weight += weights.getComponent(vertex, slot);
                    if (weight > 0.5) vertices.push(vertex);
                }
                if (vertices.length) selected.push({ mesh, vertices });
            });
            if (!selected.length)
                throw new Error(`Maillage de pied VRM absent : ${side}.`);
            this.feet[side] = selected;
        }
    }

    sample() {
        const result = {};
        const point = new Vector3();
        for (const [side, selected] of Object.entries(this.feet)) {
            const vertices = [];
            for (const { mesh, vertices: indices } of selected) {
                mesh.skeleton.update();
                for (const vertex of indices) {
                    mesh.getVertexPosition(vertex, point).applyMatrix4(
                        mesh.matrixWorld,
                    );
                    if (!point.toArray().every(Number.isFinite))
                        throw new Error("Sommet de pied non fini.");
                    vertices.push(point.toArray());
                }
            }
            result[side] = vertices;
        }
        return result;
    }
}

export function footSurfaceSummary(samples) {
    if (!samples.length) throw new Error("Aucune pose de pied à mesurer.");
    return Object.fromEntries(
        ["left", "right"].map((side) => {
            const heights = samples.map((sample) =>
                Math.min(...sample[side].map((point) => point[1])),
            );
            return [
                side,
                {
                    vertices: samples[0][side].length,
                    lowest_vertex_y_m: Math.min(...heights),
                    highest_lowest_vertex_y_m: Math.max(...heights),
                    frames_with_surface_contact: samples.filter((sample) =>
                        sample[side].some(
                            (point) => Math.abs(point[1]) <= 0.0001,
                        ),
                    ).length,
                    frames: samples.length,
                },
            ];
        }),
    );
}
