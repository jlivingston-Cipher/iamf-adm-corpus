#!/usr/bin/env python3
# bs2127_position.py -- what an ADM Cartesian position means, by the standard.
#
# Original work (IAMF project, IA-0105). The corpus generator writes an
# object's Cartesian position with plain spherical trigonometry (see
# adm_corpus_gen.py, the comment above sph_to_cart). ITU-R BS.2127-0 section
# 10.1.2 reads a Cartesian position differently: the room-centric cube is
# mapped to azimuth sector by sector, so (-1, 0, 0) is azimuth 70, not 90, and
# elevation is compressed (45 deg of cube elevation is 30 deg). A renderer
# that follows the standard (EAR does) therefore places a Cartesian object of
# this corpus at standard_direction(az, el, dist), not at (az, el), whenever
# the direction is off the five mid-layer speaker azimuths (0, +-30, +-110)
# or off the horizontal plane.
#
# The measures score Cartesian objects against this reading; objects authored
# with spherical coordinates keep their polar ground truth unchanged.
import math

THETA_TOP, THETA_TOP_C, EPS = 30.0, 45.0, 1e-10

# (phi_l, phi_r, (x_l, y_l), (x_r, y_r)) and the Cartesian azimuth range each
# sector serves, section 10.1.
_SECTORS = [
    (30.0, 0.0, (-1.0, 1.0), (0.0, 1.0)),
    (0.0, -30.0, (0.0, 1.0), (1.0, 1.0)),
    (-30.0, -110.0, (1.0, 1.0), (1.0, -1.0)),
    (-110.0, 110.0, (1.0, -1.0), (-1.0, -1.0)),
    (110.0, 30.0, (-1.0, -1.0), (-1.0, 1.0)),
]
_CART_RANGES = [(0.0, 45.0), (-45.0, 0.0), (-135.0, -45.0),
                (135.0, -135.0), (45.0, 135.0)]


def relative_angle(x, y):
    """Section 6.7: y + 360n for the smallest n with the result >= x."""
    while y < x:
        y += 360.0
    while y - 360.0 >= x:
        y -= 360.0
    return y


def inside_angle_range(x, start, end, tol=0.0):
    """Section 6.2: x on the arc from start anticlockwise to end."""
    if end - start >= 360.0 - 2 * tol:
        return True
    end = relative_angle(start, end)
    x = relative_angle(start - tol, x)
    return x <= end + tol


def _map_linear_to_az(phi_l, phi_r, x):
    mid = (phi_l + phi_r) / 2.0
    rng = phi_r - mid
    gl, gr = math.cos(x * math.pi / 2), math.sin(x * math.pi / 2)
    g_r = gr / (gl + gr)
    return mid + math.degrees(
        math.atan(2 * (g_r - 0.5) * math.tan(math.radians(rng))))


def point_cart_to_polar(x, y, z):
    """Section 10.1.2: (azimuth, elevation, distance) of a Cartesian point."""
    if abs(x) < EPS and abs(y) < EPS:
        if abs(z) < EPS:
            return 0.0, 0.0, 0.0
        return 0.0, math.copysign(90.0, z), abs(z)
    phi_c = -math.degrees(math.atan2(x, y))
    for (phi_l, phi_r, (xl, yl), (xr, yr)), (a, b) in zip(_SECTORS,
                                                          _CART_RANGES):
        if inside_angle_range(phi_c, a, b):
            break
    else:
        raise ValueError(phi_c)
    det = xl * yr - yl * xr
    g_l = (x * yr - y * xr) / det
    g_r = (-x * yl + y * xl) / det
    r_xy = g_l + g_r
    phi = relative_angle(-180.0, _map_linear_to_az(
        relative_angle(phi_r, phi_l), phi_r, g_r / r_xy))
    if phi > 180.0:
        phi -= 360.0
    th_c = math.degrees(math.atan(z / r_xy))
    if abs(th_c) > THETA_TOP_C:
        th = THETA_TOP + (90.0 - THETA_TOP) * (abs(th_c) - THETA_TOP_C) \
            / (90.0 - THETA_TOP_C)
        return phi, math.copysign(th, th_c), abs(z)
    return phi, th_c * THETA_TOP / THETA_TOP_C, r_xy


def written_cartesian(az, el, dist):
    """The Cartesian position adm_corpus_gen writes for (az, el, dist)."""
    a, e = math.radians(az), math.radians(el)
    return (-math.sin(a) * math.cos(e) * dist,
            math.cos(a) * math.cos(e) * dist, math.sin(e) * dist)


def standard_direction(az, el, dist=1.0):
    """The (az, el) BS.2127-0 reads from the corpus's Cartesian form."""
    a, e, _ = point_cart_to_polar(*written_cartesian(az, el, dist))
    return a, e


def as_read(blocks, cartesian):
    """Blocks with az/el replaced by what the standard reads, when the object
    was written in Cartesian form; spherical objects pass through unchanged."""
    if not cartesian:
        return blocks
    out = []
    for b in blocks:
        a, e = standard_direction(b["az"], b["el"], b.get("dist", 1.0))
        out.append({**b, "az": a, "el": e})
    return out
