import { readFile } from "node:fs/promises";
import { GLTFLoader } from "../../../../web/avatar/node_modules/three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "../../../../web/avatar/node_modules/@pixiv/three-vrm/lib/three-vrm.module.js";

// CPU-only fixture: preserve geometry, skeleton, constraints and expression binds.
// Textures/materials are omitted so this does not require a browser or GPU.
export async function loadFixtureVRM() {
    const bytes = await readFile(process.env.PROMETHEE_TEST_AVATAR);
    const jsonLength = bytes.readUInt32LE(12);
    const document = JSON.parse(bytes.subarray(20, 20 + jsonLength).toString());
    const binStart = 20 + jsonLength + 8;
    document.buffers[0].uri = `data:application/octet-stream;base64,${bytes.subarray(binStart).toString("base64")}`;
    delete document.images;
    delete document.textures;
    delete document.materials;
    for (const mesh of document.meshes ?? [])
        for (const primitive of mesh.primitives) delete primitive.material;
    globalThis.ProgressEvent ??= class {
        constructor(type, fields = {}) {
            this.type = type;
            Object.assign(this, fields);
        }
    };
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.parseAsync(JSON.stringify(document), "");
    return gltf.userData.vrm;
}
