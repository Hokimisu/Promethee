"""Logical affordances only: this catalog contains no meshes or animations."""

CATALOG = {
    "chair": {"movable": True, "sit": True},
    "sign": {"movable": True, "write": True},
    "plush": {"movable": True},
    "bed": {"movable": False},
    "tv": {"movable": False},
}

INITIAL_WORLD = {
    "schema_version": 1,
    "avatar": {"position": [0.0, 0.0], "seated_on": None, "holding": None},
    "objects": {},
}
