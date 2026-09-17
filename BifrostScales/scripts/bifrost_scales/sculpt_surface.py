"""Versioned, shared vector displacement; independent of output tessellation."""

import math
from collections.abc import Mapping, Sequence

from .shape_curves import normalize_shape_curve, sample_shape_curve

ZERO_CURVE = ((0.0, 0.0), (1.0, 0.0))
MAX_EDIT_RESOLUTION = 128


def normalize_surface(value):
    if not value:
        return {}
    if not isinstance(value, Mapping) or value.get("schema") not in ("vector-surface/1", "vector-surface/2", "vector-surface/3"):
        raise ValueError("Unsupported sculpt surface schema")
    n = value.get("resolution", 32)
    if isinstance(n, bool) or not isinstance(n, int) or not 4 <= n <= MAX_EDIT_RESOLUTION:
        raise ValueError("Sculpt resolution must be 4..128")
    source = value.get("deltas", ())
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes)) or len(source) not in (0, (n + 1) ** 2):
        raise ValueError("Sculpt sample count does not match resolution")
    deltas = []
    for point in source:
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) != 3:
            raise ValueError("Sculpt samples require three components")
        point = tuple(float(component) for component in point)
        if not all(math.isfinite(component) and abs(component) <= 8.0 for component in point):
            raise ValueError("Sculpt displacement must be finite and within +/-8 scale sizes")
        deltas.append(point)
    for key in ("u_curve", "v_curve"):
        curve = value.get(key, ZERO_CURVE)
        if not isinstance(curve, Sequence) or isinstance(curve, (str, bytes)) or not 2 <= len(curve) <= 16:
            raise ValueError("Sculpt curves require 2..16 points")
        for point in curve:
            if not isinstance(point, Sequence) or len(point) != 2 or not all(math.isfinite(float(x)) for x in point):
                raise ValueError("Invalid sculpt curve point")
    return dict(
        schema=value["schema"], resolution=n, deltas=tuple(deltas),
        u_curve=normalize_shape_curve(value.get("u_curve", ZERO_CURVE), -4.0, 4.0),
        v_curve=normalize_shape_curve(value.get("v_curve", ZERO_CURVE), -4.0, 4.0),
    )


def sample_surface(surface, u, v):
    """Return lateral, longitudinal, height displacement in scale-size units."""
    if surface["schema"] == "vector-surface/3" and min(u, v, 1-u, 1-v) <= 0:
        return (0.0, 0.0, 0.0)
    n = surface["resolution"]
    x, y = max(0.0, min(1.0, u)) * n, max(0.0, min(1.0, v)) * n
    i, j = min(n - 1, int(x)), min(n - 1, int(y))
    a, b = x - i, y - j
    data = surface["deltas"]
    result = [0.0, 0.0, 0.0]
    if data:
        for di, dj, weight in ((0, 0, (1-a)*(1-b)), (1, 0, a*(1-b)), (0, 1, (1-a)*b), (1, 1, a*b)):
            point = data[(j + dj) * (n + 1) + i + di]
            for axis in range(3):
                result[axis] += point[axis] * weight
    result[2] += sample_shape_curve(surface["u_curve"], u) + sample_shape_curve(surface["v_curve"], v)
    if surface["schema"] in ("vector-surface/2", "vector-surface/3"):
        return tuple(result)
    # Zero at the protected boundary; full displacement in the central area.
    t = min(1.0, 8.0 * min(u, v, 1-u, 1-v))
    weight = t*t*(3-2*t)
    return tuple(component * weight for component in result)


def editor_rest_point(u, v, disk=False):
    x, z = 2*u-1, 2*v-1
    if disk:
        return (.5*x*math.sqrt(1-.5*z*z), 0., .5*z*math.sqrt(1-.5*x*x))
    return (.5*x, 0., .5*z)


def editor_points(surface, disk=False):
    n = surface["resolution"]
    result = []
    for j in range(n + 1):
        for i in range(n + 1):
            u, v = i / n, j / n
            dx, dz, dy = sample_surface(surface, u, v)
            x, _, z = editor_rest_point(u, v, disk)
            result.append((x + dx, dy, z + dz))
    return result


def capture_surface(surface, points, disk=False):
    """Capture edited positions without resampling or changing the stored grid."""
    n = surface["resolution"]
    if len(points) != (n + 1) ** 2:
        raise ValueError("Editing mesh topology changed; restore topology before applying")
    data = []
    for j in range(n + 1):
        for i in range(n + 1):
            u, v = i/n, j/n
            x, y, z = points[j*(n+1)+i]
            rest_x, _, rest_z = editor_rest_point(u, v, disk)
            x += u-.5-rest_x
            z += v-.5-rest_z
            t = min(1.0, 8.0 * min(u, v, 1-u, 1-v))
            weight = t*t*(3-2*t)
            if surface["schema"] == "vector-surface/3" and min(i,j,n-i,n-j) == 0:
                data.append((0.0, 0.0, 0.0))
                continue
            if surface["schema"] in ("vector-surface/2", "vector-surface/3"):
                weight = 1.0
            if weight == 0.0:
                if max(abs(x-(u-.5)), abs(z-(v-.5)), abs(y)) > 1e-5:
                    raise ValueError("Protected boundary moved; undo the boundary edit before applying")
                data.append((0.0, 0.0, 0.0))
            else:
                height = y/weight - sample_shape_curve(surface["u_curve"], u) - sample_shape_curve(surface["v_curve"], v)
                data.append(((x-u+.5)/weight, (z-v+.5)/weight, height))
    return normalize_surface(dict(surface, deltas=data))
