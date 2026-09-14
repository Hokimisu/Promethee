"""A deterministic fixture, not an LLM decision or a learned motor policy."""

ACTIVITY_ID = "welcome"
STEPS = [
    {"kind": "spawn", "args": {"object_id": "chair-1", "asset": "chair", "position": [1, 0]}},
    {"kind": "spawn", "args": {"object_id": "sign-1", "asset": "sign", "position": [0, 0.5]}},
    {"kind": "spawn", "args": {"object_id": "plush-1", "asset": "plush", "position": [0.5, 0]}},
    {"kind": "write", "args": {"object_id": "sign-1", "text": "Bienvenue dans Promethee."}},
    {"kind": "take", "args": {"object_id": "plush-1"}},
    {"kind": "move", "args": {"position": [1, 0]}},
    {"kind": "sit", "args": {"object_id": "chair-1"}},
]
