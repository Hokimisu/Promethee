"""Deterministic CPU ball physics for B04, in metres with Y up.

Only balls move. The avatar is a static standing capsule, other objects are
static spheres, and the room is a box with a 5 m ceiling. These proxies do not
simulate the VRM skin, fingers, body balance, or momentum exchange between balls.
"""

import math

GRAVITY = 9.81
MAX_SPEED = 12.0
MAX_DT = 0.25
RESTITUTION = 0.55
FLOOR_FRICTION = 0.65
CEILING = 5.0
AVATAR_RADIUS = 0.25
AVATAR_SEGMENT = (0.25, 1.45)
_EPS = 1e-9


def _number(value, low, high, name):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{name} must be finite and within [{low}, {high}].")
    return float(value)


def _vector(value, size, limit, name):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"{name} must contain {size} finite numbers.")
    return [_number(x, -limit, limit, name) for x in value]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _reflect(velocity, normal):
    incoming = _dot(velocity, normal)
    if incoming < 0:
        # Tiny impacts settle instead of bouncing indefinitely under gravity.
        restitution = RESTITUTION if incoming < -0.2 else 0.0
        for axis in range(3):
            velocity[axis] -= (1 + restitution) * incoming * normal[axis]


def _sphere_hit(position, travel, center, radius):
    offset = [position[i] - center[i] for i in range(3)]
    a, b = _dot(travel, travel), _dot(offset, travel)
    if a <= _EPS**2 or b >= 0:
        return None
    c = _dot(offset, offset) - radius * radius
    discriminant = b * b - a * c
    if discriminant < 0:
        return None
    fraction = (-b - math.sqrt(discriminant)) / a
    if not -_EPS <= fraction <= 1:
        return None
    fraction = max(0.0, fraction)
    normal = [(offset[i] + fraction * travel[i]) / radius for i in range(3)]
    return fraction, normal


def _capsule_hits(position, travel, avatar, radius):
    x, z = avatar
    low, high = AVATAR_SEGMENT
    hits = []
    for y in (low, high):
        hit = _sphere_hit(position, travel, [x, y, z], radius)
        if hit is not None:
            hits.append(hit)
    # Infinite vertical cylinder, restricted to the capsule's central segment.
    hit = _sphere_hit([position[0], 0, position[2]], [travel[0], 0, travel[2]], [x, 0, z], radius)
    if hit is not None and low <= position[1] + hit[0] * travel[1] <= high:
        hits.append(hit)
    return hits


def _depenetrate(position, velocity, radius, extent, avatar, obstacles, contacts):
    """Resolve overlaps introduced by external placement without adding an impulse.

    An impossible arrangement is rejected instead of oscillating indefinitely.
    Positional repair can change potential energy: it is an external placement
    correction, not a physically simulated impact.
    """
    for _ in range(16):
        changed = False
        for axis, low, high in (
            (0, -extent, extent),
            (1, radius, CEILING - radius),
            (2, -extent, extent),
        ):
            old = position[axis]
            position[axis] = max(low, min(high, old))
            if position[axis] != old:
                normal = [0.0, 0.0, 0.0]
                normal[axis] = 1.0 if old < low else -1.0
                _reflect(velocity, normal)
                contacts.add("floor" if axis == 1 and old < low else "wall")
                changed = True
        colliders = [(center, size + radius, "object") for center, size in obstacles]
        if avatar is not None:
            y = max(AVATAR_SEGMENT[0], min(AVATAR_SEGMENT[1], position[1]))
            colliders.append(([avatar[0], y, avatar[1]], AVATAR_RADIUS + radius, "avatar"))
        for center, size, tag in colliders:
            delta = [position[i] - center[i] for i in range(3)]
            distance = math.sqrt(_dot(delta, delta))
            if distance < size - _EPS:
                normal = [d / distance for d in delta] if distance > _EPS else [1.0, 0.0, 0.0]
                position[:] = [center[i] + normal[i] * size for i in range(3)]
                _reflect(velocity, normal)
                contacts.add(tag)
                changed = True
        if not changed:
            return
    raise ValueError("Ball cannot be separated from overlapping collision proxies.")


def step_ball(
    position3,
    velocity3,
    dt,
    radius=0.06,
    room_limit=4.5,
    avatar_position2=None,
    obstacles=(),
):
    """Return a new ``{position, velocity, sleeping, contacts}`` ball state.

    ``dt`` is 0..0.25 seconds; velocity magnitude is at most 12 m/s. Obstacles
    are at most 64 static ``{position: [x,y,z], radius: metres}`` spheres. Omit
    the moving ball itself. Avatar coordinates are [x,z], with a fixed standing
    capsule spanning y=0..1.7 m. Contacts are unique sorted category tags.

    No inputs are mutated. Callers own pause, persistence, event grouping and
    author attribution. A sleeping result only means rest on the room floor.
    """
    dt = _number(dt, 0, MAX_DT, "dt")
    radius = _number(radius, 0.01, 0.5, "radius")
    room_limit = _number(room_limit, 0.6, 5, "room_limit")
    position = _vector(position3, 3, 5, "position")
    velocity = _vector(velocity3, 3, MAX_SPEED, "velocity")
    if math.sqrt(_dot(velocity, velocity)) > MAX_SPEED + _EPS:
        raise ValueError("Ball speed exceeds 12 m/s.")
    if position[1] < 0 or abs(position[0]) > room_limit or abs(position[2]) > room_limit:
        raise ValueError("Ball center must start inside the room.")
    avatar = None if avatar_position2 is None else _vector(avatar_position2, 2, 5, "avatar")
    if not isinstance(obstacles, (list, tuple)) or len(obstacles) > 64:
        raise ValueError("Expected at most 64 static spherical obstacles.")
    spheres = []
    for obstacle in obstacles:
        if not isinstance(obstacle, dict) or set(obstacle) != {"position", "radius"}:
            raise ValueError("Obstacle requires position and radius.")
        spheres.append(
            (
                _vector(obstacle["position"], 3, 5, "obstacle position"),
                _number(obstacle["radius"], 0.01, 1, "obstacle radius"),
            )
        )
    contacts = set()
    extent = room_limit - radius
    _depenetrate(position, velocity, radius, extent, avatar, spheres, contacts)
    substeps = max(1, math.ceil(dt * 120))
    h = dt / substeps
    for _ in range(substeps):
        velocity[1] -= GRAVITY * h
        speed = math.sqrt(_dot(velocity, velocity))
        if speed > MAX_SPEED:
            velocity[:] = [v * MAX_SPEED / speed for v in velocity]
        remaining = h
        # Swept collisions avoid tunnelling even through small spheres.
        for _ in range(8):
            if remaining <= _EPS:
                break
            travel = [v * remaining for v in velocity]
            hits = []
            for axis, low, high in (
                (0, -extent, extent),
                (1, radius, CEILING - radius),
                (2, -extent, extent),
            ):
                for plane, sign in ((low, 1), (high, -1)):
                    if travel[axis] * sign < 0:
                        fraction = (plane - position[axis]) / travel[axis]
                        if -_EPS <= fraction <= 1:
                            normal = [0.0, 0.0, 0.0]
                            normal[axis] = sign
                            tag = "floor" if axis == 1 and sign == 1 else "wall"
                            hits.append((max(0.0, fraction), normal, tag))
            for center, size in spheres:
                hit = _sphere_hit(position, travel, center, radius + size)
                if hit is not None:
                    hits.append((*hit, "object"))
            if avatar is not None:
                for hit in _capsule_hits(position, travel, avatar, radius + AVATAR_RADIUS):
                    hits.append((*hit, "avatar"))
            if not hits:
                position[:] = [position[i] + travel[i] for i in range(3)]
                break
            fraction, normal, tag = min(hits, key=lambda item: item[0])
            position[:] = [position[i] + fraction * travel[i] for i in range(3)]
            _reflect(velocity, normal)
            contacts.add(tag)
            remaining *= 1 - fraction
        else:
            # A trapped ball must stop rather than skip unresolved collision time.
            velocity[:] = [0.0, 0.0, 0.0]
        if position[1] <= radius + _EPS and abs(velocity[1]) < 0.2:
            position[1], velocity[1] = radius, 0.0
            horizontal = math.hypot(velocity[0], velocity[2])
            factor = max(0.0, 1 - FLOOR_FRICTION * GRAVITY * h / horizontal) if horizontal else 0
            velocity[0] *= factor
            velocity[2] *= factor
    sleeping = position[1] <= radius + _EPS and math.sqrt(_dot(velocity, velocity)) < 0.03
    if sleeping:
        position[1] = radius
        velocity[:] = [0.0, 0.0, 0.0]
    return {
        "position": position,
        "velocity": velocity,
        "sleeping": sleeping,
        "contacts": sorted(contacts),
    }
