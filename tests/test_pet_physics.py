"""B04 ball mechanics; these tests make no claims about the avatar's physics."""

import copy
import math

import pytest

from promethee.pet_physics import GRAVITY, MAX_SPEED, step_ball


def test_free_flight_falls_and_retains_horizontal_momentum():
    result = step_ball([0, 2, 0], [2, 1, -1], 0.1)
    assert result["position"][0] == pytest.approx(0.2)
    assert result["position"][2] == pytest.approx(-0.1)
    assert result["velocity"] == pytest.approx([2, 1 - GRAVITY * 0.1, -1])
    assert result["position"][1] == pytest.approx(2 + 0.1 - 0.5 * GRAVITY * 0.1**2, abs=0.005)
    assert result["contacts"] == []
    assert not result["sleeping"]


def test_floor_bounce_loses_energy_and_does_not_penetrate():
    result = step_ball([0, 0.2, 0], [0, -5, 0], 0.05)
    assert result["position"][1] >= 0.06
    assert 0 < result["velocity"][1] < 5
    assert result["contacts"] == ["floor"]
    energy = GRAVITY * result["position"][1] + sum(v * v for v in result["velocity"]) / 2
    assert energy < GRAVITY * 0.2 + 5**2 / 2


@pytest.mark.parametrize("axis,sign", [(0, -1), (0, 1), (2, -1), (2, 1)])
def test_fast_wall_contact_is_swept(axis, sign):
    position, velocity = [0, 1, 0], [0, 0, 0]
    position[axis], velocity[axis] = sign * 4.3, sign * 12
    result = step_ball(position, velocity, 0.25)
    assert abs(result["position"][axis]) <= 4.44 + 1e-9
    assert result["velocity"][axis] * sign < 0
    assert "wall" in result["contacts"]


def test_ceiling_keeps_the_ball_inside_the_world_coordinates():
    result = step_ball([0, 4.8, 0], [0, 12, 0], 0.1)
    assert result["position"][1] <= 4.94
    assert result["velocity"][1] < 0
    assert result["contacts"] == ["wall"]


def test_fast_ball_hits_avatar_capsule_but_can_pass_above_it():
    result = step_ball([-0.6, 1, 0], [12, 0, 0], 0.1, avatar_position2=[0, 0])
    assert result["position"][0] < -0.31
    assert result["velocity"][0] < 0
    assert result["contacts"] == ["avatar"]
    overhead = step_ball([-0.6, 2, 0], [12, 0, 0], 0.1, avatar_position2=[0, 0])
    assert overhead["position"][0] > 0
    assert overhead["contacts"] == []


def test_small_sphere_grazing_contact_cannot_be_skipped_between_substeps():
    # Entry and exit lie within one 120 Hz step; endpoint-only tests miss this.
    obstacle = {"position": [0, 1, 0], "radius": 0.01}
    result = step_ball([-0.055, 1, 0.019], [12, 0, 0], 0.008, radius=0.01, obstacles=[obstacle])
    assert result["contacts"] == ["object"]
    assert math.dist(result["position"], obstacle["position"]) >= 0.02 - 1e-8


def test_ball_eventually_sleeps_and_does_not_gain_energy_after_rest():
    position, velocity = [0, 1.5, 0], [2, 2, 0.5]
    for _ in range(400):
        result = step_ball(position, velocity, 0.05)
        position, velocity = result["position"], result["velocity"]
    assert result["sleeping"]
    assert position[1] == 0.06
    assert velocity == [0, 0, 0]
    for _ in range(30):
        next_result = step_ball(position, velocity, 0.05)
        assert next_result["position"] == position
        assert next_result["velocity"] == velocity
        assert next_result["sleeping"]


def test_result_is_deterministic_and_does_not_modify_any_input():
    arguments = {
        "position3": [-0.5, 1, 0],
        "velocity3": [4, 0, 0],
        "dt": 0.2,
        "avatar_position2": [2, 2],
        "obstacles": [{"position": [0, 1, 0], "radius": 0.1}],
    }
    before = copy.deepcopy(arguments)
    assert step_ball(**arguments) == step_ball(**arguments)
    assert arguments == before


def test_external_overlap_is_resolved_without_increasing_speed():
    result = step_ball([0, 1, 0], [0, 0, 0], 0, avatar_position2=[0, 0])
    assert result["position"] == [0.31, 1, 0]
    assert result["velocity"] == [0, 0, 0]
    assert result["contacts"] == ["avatar"]


def test_gravity_is_speed_bounded_and_tags_are_unique():
    result = step_ball([0, 4, 0], [0, -MAX_SPEED, 0], 0.25)
    assert math.sqrt(sum(v * v for v in result["velocity"])) <= MAX_SPEED + 1e-9
    resting = step_ball([0, 0.06, 0], [0, 0, 0], 0.25)
    assert resting["contacts"] == ["floor"]


def test_repeated_contacts_remain_inside_proxies_and_do_not_add_energy():
    position, velocity = [-2, 1.1, -0.5], [8, 2, 2]
    obstacle = {"position": [1.2, 0.4, 0.4], "radius": 0.4}
    for _ in range(200):
        energy = GRAVITY * position[1] + sum(v * v for v in velocity) / 2
        result = step_ball(position, velocity, 0.05, avatar_position2=[0, 0], obstacles=[obstacle])
        position, velocity = result["position"], result["velocity"]
        new_energy = GRAVITY * position[1] + sum(v * v for v in velocity) / 2
        assert new_energy <= energy + 1e-8
        assert 0.06 - 1e-8 <= position[1] <= 4.94 + 1e-8
        assert max(abs(position[0]), abs(position[2])) <= 4.44 + 1e-8
        assert math.dist(position, obstacle["position"]) >= 0.46 - 1e-8
        capsule_point = [0, max(0.25, min(1.45, position[1])), 0]
        assert math.dist(position, capsule_point) >= 0.31 - 1e-8


@pytest.mark.parametrize(
    "changes",
    [
        {"dt": -0.1},
        {"dt": 0.3},
        {"dt": True},
        {"dt": math.nan},
        {"dt": 10**1000},
        {"position3": [0, math.inf, 0]},
        {"position3": [5, 1, 0]},
        {"position3": [0, -0.1, 0]},
        {"velocity3": [10, 10, 0]},
        {"velocity3": [True, 0, 0]},
        {"velocity3": [0, 0]},
        {"avatar_position2": [0, math.nan]},
        {"radius": 0},
        {"room_limit": 0.1},
        {"obstacles": [{"position": [0, 0, 0], "radius": -1}]},
        {"obstacles": [{"position": [0, 0, 0], "radius": 1, "extra": 0}]},
        {"obstacles": [{"position": [0, 0, 0], "radius": 1}] * 65},
    ],
)
def test_invalid_inputs_are_rejected(changes):
    arguments = {"position3": [0, 1, 0], "velocity3": [0, 0, 0], "dt": 0.05}
    with pytest.raises(ValueError):
        step_ball(**(arguments | changes))
