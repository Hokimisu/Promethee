"""Explicit read projections of one already-read snapshot; no persistence access."""

import copy


def _copy(value, detail):
    if not isinstance(detail, str) or detail not in ("summary", "full"):
        raise ValueError("detail must be 'summary' or 'full'.")
    return copy.deepcopy(value)


def project_world(snapshot, *, detail="summary"):
    """Keep world authority intact while explicitly omitting articulated arrays."""
    result = _copy(snapshot, detail)
    if detail == "full":
        return result
    omitted = []
    for field in ("pose", "appearance"):
        if field in result:
            del result[field]
            omitted.append(field)
    result["projection"] = {"detail": "summary", "omitted": omitted}
    return result


def project_execution(receipt, *, detail="summary"):
    """Preserve the observed receipt, including missing or null observations."""
    result = _copy(receipt, detail)
    if detail == "full":
        return result
    omitted = []
    observation = result.get("observation")
    if isinstance(observation, dict):
        for field in ("pose", "appearance"):
            if field in observation:
                del observation[field]
                omitted.append("observation." + field)
    result["projection"] = {"detail": "summary", "omitted": omitted}
    return result
