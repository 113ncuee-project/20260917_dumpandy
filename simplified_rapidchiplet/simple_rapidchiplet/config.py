from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChipletConfig:
    pe_rows: int
    pe_cols: int
    frequency_hz: float
    op_per_mac: float
    ops_per_pe_per_cycle: float
    utilization: float
    width_mm: float
    spacing_mm: float
    internal_latency_cycles: float
    phy_latency_cycles: float
    # Local SRAM budget used by the architecture-level feasibility checker.
    # Existing configs that do not provide it use this conservative default.
    sram_mb: float = 16.0

    @property
    def peak_ops_per_second(self) -> float:
        return self.pe_rows * self.pe_cols * self.frequency_hz * self.ops_per_pe_per_cycle

    @property
    def peak_tops(self) -> float:
        return self.peak_ops_per_second / 1e12


@dataclass(frozen=True)
class NetworkConfig:
    link_bandwidth_bits_per_cycle: float
    link_latency_base_cycles: float
    link_latency_cycles_per_mm: float


@dataclass(frozen=True)
class PowerConfig:
    chiplet_static_w: float
    chiplet_peak_dynamic_w: float
    phy_w: float
    link_static_w_per_mm: float
    link_dynamic_pj_per_bit: float


@dataclass(frozen=True)
class RapidChipletConfig:
    root: str
    technology_file: str
    chiplet_file: str
    chiplet_name: str
    packaging_file: str
    technology: str
    chiplet_power_w: float
    fraction_power_bumps: float
    phy_fraction_bump_area: float


@dataclass(frozen=True)
class EvalConfig:
    target_fps: float
    max_chiplets: int
    chiplet: ChipletConfig
    network: NetworkConfig
    power: PowerConfig
    rapidchiplet: RapidChipletConfig


def load_config(path: str | Path) -> EvalConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = json.load(f)

    chiplet = ChipletConfig(**raw["chiplet"])
    network = NetworkConfig(**raw["network"])
    power = PowerConfig(**raw["power"])
    rapidchiplet = RapidChipletConfig(**raw["rapidchiplet"])
    return EvalConfig(
        target_fps=float(raw["evaluation"]["target_fps"]),
        max_chiplets=int(raw["evaluation"]["max_chiplets"]),
        chiplet=chiplet,
        network=network,
        power=power,
        rapidchiplet=rapidchiplet,
    )
