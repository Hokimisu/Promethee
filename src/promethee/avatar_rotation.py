"""Match the pinned Three.js matrix-to-normalized-quaternion conversion."""

import math


def quaternion_matrix(q):
    import numpy as np

    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def normalized_core_rotation(rows):
    # Quaternion.setFromRotationMatrix(...).normalize(), Three.js 0.186.0.
    # SVD orthogonalization is different for slightly imperfect Core matrices.
    trace = sum(rows[i][i] for i in range(3))
    if trace > 0:
        scale = 0.5 / math.sqrt(trace + 1)
        q = [
            (rows[2][1] - rows[1][2]) * scale,
            (rows[0][2] - rows[2][0]) * scale,
            (rows[1][0] - rows[0][1]) * scale,
            0.25 / scale,
        ]
    else:
        i = (
            0
            if rows[0][0] > rows[1][1] and rows[0][0] > rows[2][2]
            else (1 if rows[1][1] > rows[2][2] else 2)
        )
        j, k = (i + 1) % 3, (i + 2) % 3
        scale = 2 * math.sqrt(1 + rows[i][i] - rows[j][j] - rows[k][k])
        q = [0.0] * 4
        q[i] = 0.25 * scale
        q[j] = (rows[i][j] + rows[j][i]) / scale
        q[k] = (rows[i][k] + rows[k][i]) / scale
        q[3] = (rows[k][j] - rows[j][k]) / scale
    norm = math.hypot(*q)
    return quaternion_matrix([v / norm for v in q])
