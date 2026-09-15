import math

import pytest

from promethee.ardy_geometry import floor_lift_envelope, floor_settle_offsets


def test_posture_grounding_removes_float_and_penetration_without_an_envelope():
    heights = [0.008, 0.004, -0.003, -0.001]
    offsets = floor_settle_offsets(heights)
    assert offsets == pytest.approx([-0.008, -0.004, 0.003, 0.001])
    assert [h + o for h, o in zip(heights, offsets, strict=True)] == [0.0] * 4


@pytest.mark.parametrize(
    "heights", [[], [math.nan], [math.inf], [0.051], [-0.051], [0, 0.016], [0, -0.016]]
)
def test_posture_grounding_refuses_large_or_abrupt_adjustments(heights):
    with pytest.raises(ValueError):
        floor_settle_offsets(heights)


def test_lift_anticipates_and_leaves_a_peak_without_cutting_through_floor():
    required = [0.0, 0.0, 0.04, 0.0, 0.0]
    actual = floor_lift_envelope(required)
    assert actual == pytest.approx([0.01, 0.025, 0.04, 0.025, 0.01])
    assert all(a >= r for a, r in zip(actual, required, strict=True))
    assert max(abs(a - b) for a, b in zip(actual, actual[1:], strict=False)) <= 0.015000001
    assert floor_lift_envelope(actual) == actual


def test_flat_floor_envelope_is_unchanged():
    assert floor_lift_envelope([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]
    assert floor_lift_envelope([0.01, 0.012, 0.011]) == [0.01, 0.012, 0.011]


@pytest.mark.parametrize("required", [[], [math.nan], [math.inf], [-0.01]])
def test_invalid_lifts_are_rejected(required):
    with pytest.raises(ValueError):
        floor_lift_envelope(required)
