"""Energy over the existing Batch-1 observation window; no FPS dependency."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import EvalConfig


@dataclass(frozen=True)
class Batch1Power:
    power_avg_batch1_w: float
    energy_per_inference_j: float
    static_energy_j: float
    compute_dynamic_energy_j: float
    link_dynamic_energy_j: float
    static_power_w: float
    chiplet_static_power_w: float
    link_static_power_w: float
    router_static_power_w: float
    chiplet_average_power_w: float
    link_average_power_w: float
    chiplet_active_times_s: tuple[float, ...]
    chiplet_compute_dynamic_energies_j: tuple[float, ...]
    observation_window_s: float


def estimate_batch1_power(
    cfg: EvalConfig, *, assigned_ops: tuple[float, ...],
    compute_efficiencies: tuple[float, ...], observation_window_s: float,
    link_static_power_w: float, router_static_power_w: float,
    link_dynamic_energy_j: float,
) -> Batch1Power:
    """Use the existing utilization while computing, zero dynamic compute at idle.

    Efficiency losses remain powered time, matching the existing latency model.
    PHY is the existing aggregate per-chiplet constant, treated as static.
    Communication/wait time is not charged as active compute. This helper has
    no rate/FPS input and cannot silently change the observation window.
    """
    if not math.isfinite(observation_window_s) or observation_window_s <= 0:
        raise ValueError('Batch-1 power requires a positive finite observation window')
    if not assigned_ops or len(assigned_ops) != len(compute_efficiencies):
        raise ValueError('Every installed chiplet needs assigned OPS and efficiency')
    values = (*assigned_ops, link_static_power_w, router_static_power_w, link_dynamic_energy_j)
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('OPS, static power and link energy must be finite and nonnegative')
    if any(not math.isfinite(v) or not 0 < v <= 1 for v in compute_efficiencies):
        raise ValueError('Compute efficiency must be in (0, 1]')
    usable_ops_s = cfg.chiplet.peak_ops_per_second * cfg.chiplet.utilization
    active_times = tuple(ops / (usable_ops_s * efficiency)
                         for ops, efficiency in zip(assigned_ops, compute_efficiencies))
    if any(t > observation_window_s and not math.isclose(t, observation_window_s, rel_tol=1e-10)
           for t in active_times):
        raise ValueError('Chiplet active time exceeds the Batch-1 observation window')
    active_dynamic_w = cfg.power.chiplet_peak_dynamic_w * cfg.chiplet.utilization
    compute_energies = tuple(active_dynamic_w * t for t in active_times)
    compute_energy = math.fsum(compute_energies)
    chiplet_static_w = len(assigned_ops) * (cfg.power.chiplet_static_w + cfg.power.phy_w)
    static_w = chiplet_static_w + link_static_power_w + router_static_power_w
    static_energy = static_w * observation_window_s
    total_energy = math.fsum((static_energy, compute_energy, link_dynamic_energy_j))
    return Batch1Power(
        power_avg_batch1_w=total_energy / observation_window_s,
        energy_per_inference_j=total_energy, static_energy_j=static_energy,
        compute_dynamic_energy_j=compute_energy, link_dynamic_energy_j=link_dynamic_energy_j,
        static_power_w=static_w, chiplet_static_power_w=chiplet_static_w,
        link_static_power_w=link_static_power_w, router_static_power_w=router_static_power_w,
        chiplet_average_power_w=chiplet_static_w + compute_energy / observation_window_s,
        link_average_power_w=link_static_power_w + link_dynamic_energy_j / observation_window_s,
        chiplet_active_times_s=active_times, chiplet_compute_dynamic_energies_j=compute_energies,
        observation_window_s=observation_window_s,
    )
