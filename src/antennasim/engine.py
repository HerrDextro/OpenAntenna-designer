"""Simulation pipeline: Project -> WireModel -> solver -> analysis."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np

from .analysis import pattern as pattern_analysis
from .analysis.farfield import compute_pattern
from .analysis.feedline import FeedResult, apply_feed_system
from .analysis.ground_loss import estimate_ground_loss
from .analysis.swr import bandwidth, resonances, swr
from .analysis.tuner import TuneResult, find_root
from .geometry.segmentation import segment, target_segment_length
from .geometry.validation import ERROR, INFO, Issue, validate_model
from .geometry.wire_model import GroundModel, Load, WireModel
from .model.document import NODE_ENVIRONMENT, NODE_SIMULATION, Project
from .model.materials import CONDUCTORS, GROUNDS
from .solver.base import SolveRequest, SolverBackend
from .solver.results import Pattern, SolveResult
from .templates.base import BuildContext, Tunable


class SimulationBlocked(RuntimeError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(i.message for i in issues if i.level == ERROR))


@dataclass
class BuiltModel:
    model: WireModel  # model.ground is the physical ground
    solve_ground: GroundModel  # ground NEC2 solves currents over
    ground_loss_ohm: float | None
    issues: list[Issue]

    @property
    def has_errors(self) -> bool:
        return any(i.level == ERROR for i in self.issues)

    def solver_model(self) -> WireModel:
        return dataclasses.replace(self.model, ground=self.solve_ground)


def sweep_frequencies(project: Project) -> np.ndarray:
    s = project.simulation
    return np.linspace(s["sweep_start"], s["sweep_stop"], s["sweep_points"])


def build(project: Project) -> BuiltModel:
    sim = project.simulation
    env = project.environment
    template = project.template
    issues: list[Issue] = []

    if sim["sweep_stop"] <= sim["sweep_start"]:
        issues.append(Issue(ERROR, "Sweep stop must be above sweep start.", NODE_SIMULATION))
    f_min = min(sim["sweep_start"], sim["design_mhz"])
    f_max = max(sim["sweep_stop"], sim["design_mhz"])
    spw = sim["segments_per_wavelength"]

    issues += template.validate(project)
    model = template.build(project, BuildContext(target_segment_length(f_max, spw)))

    if env["ground"] == "real":
        soil = GROUNDS[env["soil"]]
        ground = GroundModel("real", soil.conductivity, soil.permittivity)
    else:
        ground = GroundModel(env["ground"])
    model.ground = ground
    model.conductivity = CONDUCTORS[env["conductor"]][1]
    segment(model, f_max, spw)

    solve_ground = ground
    ground_loss = None
    if template.feed_is_grounded(project) and ground.kind == "real" and model.source is not None:
        # NEC2 cannot connect wires to lossy ground: solve over perfect ground
        # and add the ground loss as a series resistance at the feed.
        solve_ground = GroundModel("perfect")
        if env["ground_loss"] == "manual":
            ground_loss = env["ground_loss_ohms"]
        else:
            radials = project.first_part("radials")
            count, length = 0, 0.0
            if radials is not None and radials.params["mode"] == "buried":
                count, length = radials.params["count"], radials.params["length"]
            ground_loss = estimate_ground_loss(count, length, sim["design_mhz"], env["soil"])
        model.loads.append(Load(model.source.wire, model.source.fraction, r_ohm=ground_loss,
                                name="Ground loss", part_id=NODE_ENVIRONMENT))
        issues.append(Issue(INFO, f"Ground-mounted over real ground: impedance is solved over "
                                  f"perfect ground plus {ground_loss:.1f} Ω ground loss; the "
                                  f"pattern uses the real soil.", NODE_ENVIRONMENT))

    issues += validate_model(model, f_min, f_max)
    return BuiltModel(model, solve_ground, ground_loss, issues)


@dataclass
class Summary:
    design_mhz: float
    z_antenna: complex
    z_feedpoint: complex  # after balun/unun
    z_rig: complex
    swr_feedpoint: float
    swr_rig: float
    resonances_mhz: list[float]
    min_swr: float
    min_swr_mhz: float
    bandwidth_mhz: tuple[float, float] | None
    efficiency: float | None
    max_gain_dbi: float
    takeoff_deg: float
    max_azimuth_deg: float
    elevation_beamwidth_deg: float | None
    feedline_loss_db: float
    ground_loss_ohm: float | None
    segments: int
    wires: int


@dataclass
class Simulation:
    built: BuiltModel
    result: SolveResult
    pattern: Pattern
    freqs: np.ndarray
    z_antenna: np.ndarray
    feed: FeedResult
    swr_feedpoint: np.ndarray
    swr_rig: np.ndarray
    summary: Summary
    issues: list[Issue] = field(default_factory=list)


def simulate(project: Project, backend: SolverBackend) -> Simulation:
    built = build(project)
    if built.has_errors:
        raise SimulationBlocked(built.issues)
    sim, feed_cfg = project.simulation, project.feedline
    freqs = sweep_frequencies(project)
    design = sim["design_mhz"]

    result = backend.solve(SolveRequest(built.solver_model(), tuple(freqs), design))
    z_ant = result.impedances()
    z0 = feed_cfg["z0"]

    feed = apply_feed_system(freqs, z_ant, feed_cfg)
    z_feedpoint = z_ant / feed_cfg["transformer_ratio"]
    swr_fp = swr(z_feedpoint, z0)
    swr_rig = swr(feed.z_rig, z0)

    d = result.design
    power_in = d.power.input_w if d.power else 0.5 * (1.0 / d.z_in).real
    pat = compute_pattern(built.model, d.currents, design, power_in, built.model.ground)
    ps = pattern_analysis.summarize(pat)

    design_feed = apply_feed_system(np.array([design]), np.array([d.z_in]), feed_cfg)
    i_min = int(np.argmin(swr_rig))
    summary = Summary(
        design_mhz=design,
        z_antenna=d.z_in,
        z_feedpoint=d.z_in / feed_cfg["transformer_ratio"],
        z_rig=complex(design_feed.z_rig[0]),
        swr_feedpoint=float(swr(d.z_in / feed_cfg["transformer_ratio"], z0)),
        swr_rig=float(swr(design_feed.z_rig[0], z0)),
        resonances_mhz=resonances(freqs, z_ant),
        min_swr=float(swr_rig[i_min]),
        min_swr_mhz=float(freqs[i_min]),
        bandwidth_mhz=bandwidth(freqs, swr_rig, sim["swr_threshold"]),
        efficiency=d.power.efficiency if d.power else None,
        max_gain_dbi=ps.max_gain_dbi,
        takeoff_deg=ps.max_elevation_deg,
        max_azimuth_deg=ps.max_azimuth_deg,
        elevation_beamwidth_deg=ps.elevation_beamwidth_deg,
        feedline_loss_db=float(design_feed.total_loss_db[0]),
        ground_loss_ohm=built.ground_loss_ohm,
        segments=sum(max(w.segments, 1) for w in built.model.wires),
        wires=len(built.model.wires),
    )
    return Simulation(built, result, pat, freqs, z_ant, feed, swr_fp, swr_rig, summary,
                      built.issues)


def solve_impedance(project: Project, backend: SolverBackend, freq_mhz: float) -> complex:
    built = build(project)
    if built.has_errors:
        raise SimulationBlocked(built.issues)
    result = backend.solve(SolveRequest(built.solver_model(), (), freq_mhz))
    return result.design.z_in


def tune(project: Project, tunable: Tunable, backend: SolverBackend,
         target_mhz: float | None = None) -> TuneResult:
    """Find the value of `tunable` that makes the antenna resonant at target_mhz."""
    target = target_mhz or project.simulation["design_mhz"]

    def reactance(value: float) -> float:
        trial = project.clone()
        trial.set_value(tunable.node_id, tunable.key, value)
        return solve_impedance(trial, backend, target).imag

    span = tunable.maximum - tunable.minimum
    return find_root(reactance, tunable.minimum, tunable.maximum, tol_x=span * 1e-4)
