"""Logical affordances only: this catalog contains no meshes or animations."""

CATALOG = {
    "chair": {"movable": True, "sit": True},
    "sign": {"movable": True, "write": True},
    "plush": {"movable": True},
    "ball": {"movable": True},
    "bed": {"movable": False},
    "tv": {"movable": False},
}

INITIAL_WORLD = {
    "schema_version": 10,
    "initiative": None,
    "session_kind": None,
    "conversation": None,
    "data_origin": "fixture",
    "revision": 0,
    "body": {"status": "unconfirmed", "observed_at": None, "source": None},
    "pose": None,
    "appearance": None,
    "avatar": {"position": [0.0, 0.0], "seated_on": None, "holding": None},
    "objects": {},
}
