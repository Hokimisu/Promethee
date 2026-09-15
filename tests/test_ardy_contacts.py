"""Optional NumPy geometry tests. No GPU, model or claim of physical contact."""

import pytest

from promethee.ardy_contacts import between, sole_contact_metrics, solve_leg, validate_sole_contacts

np = pytest.importorskip("numpy")


@pytest.mark.parametrize("target", [[0, 0, 1], [-1, 0, 0], [1, 0, 0]])
def test_alignment_is_a_proper_rotation(target):
    source, target = np.array([1.0, 0, 0]), np.array(target, dtype=float)
    rotation = between(source, target)
    np.testing.assert_allclose(rotation @ source, target, atol=1e-10)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-10)
    assert np.linalg.det(rotation) == pytest.approx(1)


@pytest.mark.parametrize("target", [[0.1, 0.2, 0.1], [0, -3, 0], [0, 1, 0]])
def test_leg_preserves_lengths_and_reports_unreachable_target(target):
    points = np.array([[0, 1, 0], [0.1, 0.55, 0.05], [0, 0.1, 0], [0, 0.1, 0.2]])
    original = points.copy()
    rotations = np.repeat(np.eye(3)[None], 4, axis=0)
    target = np.array(target, dtype=float)
    corrected, residual = solve_leg(points, rotations, [0, 1, 2, 3], target, np.eye(3))
    knee = points[0] + corrected[0] @ (points[1] - points[0])
    ankle = knee + corrected[1] @ (points[2] - points[1])
    assert np.linalg.norm(knee - points[0]) == pytest.approx(np.linalg.norm(points[1] - points[0]))
    assert np.linalg.norm(ankle - knee) == pytest.approx(np.linalg.norm(points[2] - points[1]))
    assert np.linalg.norm(ankle - target) == pytest.approx(residual, abs=1e-9)
    assert (residual > 0.1) == (target[1] < 0)
    np.testing.assert_array_equal(points, original)
    np.testing.assert_allclose(np.linalg.det(corrected), 1, atol=1e-10)


def test_zero_length_bones_fail_explicitly():
    with pytest.raises(ValueError, match="zero-length"):
        between(np.zeros(3), np.ones(3))
    with pytest.raises(ValueError, match="zero-length"):
        solve_leg(
            np.zeros((4, 3)),
            np.repeat(np.eye(3)[None], 4, axis=0),
            [0, 1, 2, 3],
            np.ones(3),
            np.eye(3),
        )


def test_surface_slide_is_rejected_without_model_contact_labels():
    sole = np.zeros((10, 2, 3))
    sole[:, :, 0] = np.arange(10)[:, None] * 0.02
    metrics = sole_contact_metrics(sole)
    assert metrics["speed_max_m_s"] == pytest.approx(0.4)
    with pytest.raises(ValueError, match="Foot mesh slides"):
        validate_sole_contacts(metrics)
    sole[:, :, 0] = 0
    validate_sole_contacts(sole_contact_metrics(sole))


def test_airborne_vertices_do_not_prove_floor_contact():
    sole = np.ones((3, 2, 3))
    with pytest.raises(ValueError, match="No geometric foot contact"):
        validate_sole_contacts(sole_contact_metrics(sole))
    sole[0, 0, 1] = 0
    assert sole_contact_metrics(sole)["vertex_contact_pairs"] == 0
