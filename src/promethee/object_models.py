"""Original geometric object models, in metres; visuals do not grant actions."""

# Each part is an ellipsoid: centre, full XYZ dimensions, RGB colour.
# Authored for Promethee under the repository MIT license; no downloaded asset.
OBJECT_MODELS = {
    "plush": [
        {"center": [0, -0.02, 0], "size": [0.12, 0.14, 0.09], "color": "#c99c73"},
        {"center": [0, 0.065, 0], "size": [0.09, 0.085, 0.075], "color": "#c99c73"},
        {"center": [-0.034, 0.103, 0], "size": [0.025, 0.025, 0.025], "color": "#ae7e58"},
        {"center": [0.034, 0.103, 0], "size": [0.025, 0.025, 0.025], "color": "#ae7e58"},
        {"center": [-0.062, -0.015, 0], "size": [0.04, 0.08, 0.05], "color": "#c99c73"},
        {"center": [0.062, -0.015, 0], "size": [0.04, 0.08, 0.05], "color": "#c99c73"},
        {"center": [-0.032, -0.086, 0.025], "size": [0.05, 0.045, 0.06], "color": "#ae7e58"},
        {"center": [0.032, -0.086, 0.025], "size": [0.05, 0.045, 0.06], "color": "#ae7e58"},
        {"center": [-0.019, 0.075, 0.034], "size": [0.008, 0.008, 0.008], "color": "#302c29"},
        {"center": [0.019, 0.075, 0.034], "size": [0.008, 0.008, 0.008], "color": "#302c29"},
        {"center": [0, 0.057, 0.039], "size": [0.012, 0.009, 0.008], "color": "#302c29"},
    ],
}


def part_mesh(part):
    """Triangulate the same ellipsoid for the live Core diagnostic viewer."""
    import numpy as np

    points = []
    for ring in range(13):
        phi = np.pi * ring / 12
        for sector in range(21):
            theta = 2 * np.pi * sector / 20
            point = np.array(
                [np.sin(phi) * np.cos(theta), np.cos(phi), np.sin(phi) * np.sin(theta)]
            )
            points.append(np.array(part["center"]) + point * np.array(part["size"]) / 2)
    faces = []
    for ring in range(12):
        for sector in range(20):
            a = ring * 21 + sector
            faces.extend([[a, a + 1, a + 21], [a + 1, a + 22, a + 21]])
    return np.asarray(points, dtype=np.float32), np.asarray(faces, dtype=np.uint32)
