"""Far-field pattern from segment currents.

Each segment is treated as a short current element. Ground is included with an
image whose contribution is scaled by the Fresnel reflection coefficients (the
same reflection-coefficient approximation NEC2 uses for far fields). This lets
us compute a real-ground pattern even when NEC2 had to solve the currents over
perfect ground (ground-mounted verticals).
"""

from __future__ import annotations

import math

import numpy as np

from ..geometry.wire_model import GroundModel, WireModel
from ..solver.results import Pattern

ETA0 = 376.730313668
EPS0 = 8.8541878128e-12
FLOOR_DBI = -99.0


def segment_geometry(model: WireModel) -> tuple[np.ndarray, np.ndarray]:
    """Return (centers[N,3], vector length*direction [N,3]) in NEC segment order."""
    centers, vecs = [], []
    for w in model.wires:
        n = max(w.segments, 1)
        p1, p2 = np.array(w.p1), np.array(w.p2)
        d = (p2 - p1) / n
        for k in range(n):
            centers.append(p1 + d * (k + 0.5))
            vecs.append(d)
    return np.array(centers), np.array(vecs)


def reflection_coefficients(ground: GroundModel, freq_mhz: float, sin_psi: np.ndarray):
    """(R_v, R_h) for elevation angles with sin(psi) given."""
    if ground.kind == "perfect":
        return np.ones_like(sin_psi, dtype=complex), -np.ones_like(sin_psi, dtype=complex)
    omega = 2 * math.pi * freq_mhz * 1e6
    eps_c = ground.permittivity - 1j * ground.conductivity / (omega * EPS0)
    cos2 = 1 - sin_psi ** 2
    root = np.sqrt(eps_c - cos2)
    r_v = (eps_c * sin_psi - root) / (eps_c * sin_psi + root)
    r_h = (sin_psi - root) / (sin_psi + root)
    return r_v, r_h


def compute_pattern(model: WireModel, currents: np.ndarray, freq_mhz: float,
                    input_power_w: float, ground: GroundModel,
                    theta_step: float = 2.0, phi_step: float = 5.0) -> Pattern:
    has_ground = ground.kind != "free_space"
    theta_deg = np.arange(0.0, (90.0 if has_ground else 180.0) + 1e-9, theta_step)
    phi_deg = np.arange(0.0, 360.0 + 1e-9, phi_step)
    th = np.radians(theta_deg)[:, None]
    ph = np.radians(phi_deg)[None, :]

    k = 2 * math.pi * freq_mhz * 1e6 / 299_792_458.0
    centers, vecs = segment_geometry(model)
    if len(currents) != len(centers):
        raise ValueError(f"{len(currents)} currents for {len(centers)} segments")
    moments = currents[:, None] * vecs  # I * dl vector, [N,3]

    st, ct, sp, cp = np.sin(th), np.cos(th), np.sin(ph), np.cos(ph)
    khat = np.stack(np.broadcast_arrays(st * cp, st * sp, ct), axis=-1)  # [T,P,3]
    that = np.stack(np.broadcast_arrays(ct * cp, ct * sp, -st), axis=-1)
    phat = np.stack(np.broadcast_arrays(-sp, cp, np.zeros_like(th * ph)), axis=-1)

    def field(pos, mom):
        phase = np.exp(1j * k * np.einsum("tpi,ni->tpn", khat, pos))
        a = np.einsum("tpn,ni->tpi", phase, mom)
        return np.einsum("tpi,tpi->tp", a, that), np.einsum("tpi,tpi->tp", a, phat)

    e_th, e_ph = field(centers, moments)
    if has_ground:
        img_pos = centers * np.array([1.0, 1.0, -1.0])
        img_mom = moments * np.array([-1.0, -1.0, 1.0])
        i_th, i_ph = field(img_pos, img_mom)
        sin_psi = np.broadcast_to(np.cos(th), e_th.shape)  # elevation psi = 90 - theta
        r_v, r_h = reflection_coefficients(ground, freq_mhz, sin_psi)
        e_th = e_th + r_v * i_th
        e_ph = e_ph - r_h * i_ph

    # Radiation intensity U = eta k^2 |I dl_perp|^2 / (32 pi^2); gain = 4 pi U / P_in.
    scale = ETA0 * k * k / (32 * math.pi ** 2) * 4 * math.pi / max(input_power_w, 1e-30)

    def db(x):
        with np.errstate(divide="ignore"):
            return np.maximum(10 * np.log10(np.maximum(x * scale, 1e-30)), FLOOR_DBI)

    g_v = np.abs(e_th) ** 2
    g_h = np.abs(e_ph) ** 2
    return Pattern(theta_deg, phi_deg, db(g_v), db(g_h), db(g_v + g_h))
