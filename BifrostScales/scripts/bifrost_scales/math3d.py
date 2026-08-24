"""Small dependency-free vector math helpers."""

from __future__ import annotations

import math
from typing import Iterable

Vec3 = tuple[float, float, float]

_EPSILON = 1.0e-12


def vec3(value: Iterable[float]) -> Vec3:
    x, y, z = value
    return (float(x), float(y), float(z))


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec3, scalar: float) -> Vec3:
    s = float(scalar)
    return (a[0] * s, a[1] * s, a[2] * s)


def negate(a: Vec3) -> Vec3:
    return (-a[0], -a[1], -a[2])


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length_squared(a: Vec3) -> float:
    return dot(a, a)


def length(a: Vec3) -> float:
    return math.sqrt(length_squared(a))


def normalize(a: Vec3, fallback: Vec3 = (0.0, 1.0, 0.0)) -> Vec3:
    magnitude = length(a)
    if magnitude <= _EPSILON:
        return fallback
    return mul(a, 1.0 / magnitude)


def lerp(a: Vec3, b: Vec3, amount: float) -> Vec3:
    t = float(amount)
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def project_on_plane(vector: Vec3, normal: Vec3) -> Vec3:
    return sub(vector, mul(normal, dot(vector, normal)))


def rotate_around_axis(vector: Vec3, axis: Vec3, radians: float) -> Vec3:
    """Rotate a vector with Rodrigues' formula."""

    unit_axis = normalize(axis)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    term_a = mul(vector, cosine)
    term_b = mul(cross(unit_axis, vector), sine)
    term_c = mul(unit_axis, dot(unit_axis, vector) * (1.0 - cosine))
    return add(add(term_a, term_b), term_c)


def orthonormal_tangent(normal: Vec3) -> Vec3:
    """Return a stable tangent projected from world Y, then world X."""

    unit_normal = normalize(normal)
    tangent = project_on_plane((0.0, 1.0, 0.0), unit_normal)
    if length_squared(tangent) <= 1.0e-10:
        tangent = project_on_plane((1.0, 0.0, 0.0), unit_normal)
    return normalize(tangent, (1.0, 0.0, 0.0))


def triangle_normal_and_area(a: Vec3, b: Vec3, c: Vec3) -> tuple[Vec3, float]:
    twice_area = cross(sub(b, a), sub(c, a))
    magnitude = length(twice_area)
    if magnitude <= _EPSILON:
        return ((0.0, 1.0, 0.0), 0.0)
    return (mul(twice_area, 1.0 / magnitude), 0.5 * magnitude)


def closest_point_on_triangle(
    point: Vec3,
    a: Vec3,
    b: Vec3,
    c: Vec3,
) -> tuple[Vec3, tuple[float, float, float]]:
    """Return the closest point and barycentric coordinates on a triangle.

    The implementation follows the Voronoi-region test from *Real-Time
    Collision Detection*. Degenerate triangles fall back to the nearest
    vertex, which keeps the relaxation path finite and deterministic.
    """

    ab = sub(b, a)
    ac = sub(c, a)
    ap = sub(point, a)
    d1 = dot(ab, ap)
    d2 = dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return a, (1.0, 0.0, 0.0)

    bp = sub(point, b)
    d3 = dot(ab, bp)
    d4 = dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return b, (0.0, 1.0, 0.0)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        denominator = d1 - d3
        amount = d1 / denominator if abs(denominator) > _EPSILON else 0.0
        return add(a, mul(ab, amount)), (1.0 - amount, amount, 0.0)

    cp = sub(point, c)
    d5 = dot(ab, cp)
    d6 = dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return c, (0.0, 0.0, 1.0)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        denominator = d2 - d6
        amount = d2 / denominator if abs(denominator) > _EPSILON else 0.0
        return add(a, mul(ac, amount)), (1.0 - amount, 0.0, amount)

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        edge = sub(c, b)
        denominator = (d4 - d3) + (d5 - d6)
        amount = (d4 - d3) / denominator if abs(denominator) > _EPSILON else 0.0
        return add(b, mul(edge, amount)), (0.0, 1.0 - amount, amount)

    denominator = va + vb + vc
    if abs(denominator) <= _EPSILON:
        candidates = (
            (length_squared(sub(point, a)), a, (1.0, 0.0, 0.0)),
            (length_squared(sub(point, b)), b, (0.0, 1.0, 0.0)),
            (length_squared(sub(point, c)), c, (0.0, 0.0, 1.0)),
        )
        _distance, closest, barycentric = min(candidates, key=lambda item: item[0])
        return closest, barycentric

    inverse = 1.0 / denominator
    v = vb * inverse
    w = vc * inverse
    u = 1.0 - v - w
    return add(add(mul(a, u), mul(b, v)), mul(c, w)), (u, v, w)
