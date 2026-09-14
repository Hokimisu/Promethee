"""Logical affordances only: this catalog contains no meshes or animations."""

CATALOG = {
    "chair": {"movable": True, "sit": True},
    "sign": {"movable": True, "write": True},
    "plush": {"movable": True},
    "bed": {"movable": False},
    "tv": {"movable": False},
}

INITIAL_WORLD = {
    "schema_version": 2,
    "data_origin": "fixture",
    "revision": 0,
    "avatar": {"position": [0.0, 0.0], "seated_on": None, "holding": None},
    "objects": {},
}
