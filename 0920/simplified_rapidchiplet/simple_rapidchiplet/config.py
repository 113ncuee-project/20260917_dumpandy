from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
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
    backend: str = "auto"
    chiplet_name: str = "dp_candidate"


@dataclass(frozen=True)
class EvalConfig:
    max_chiplets: int
    chiplet: ChipletConfig
    network: NetworkConfig
    power: PowerConfig
    rapidchiplet: RapidChipletConfig
    ppa: dict[str, float] = field(default_factory=dict)
    search: dict[str, object] = field(default_factory=dict)
    experiment: dict[str, object] = field(default_factory=dict)
    strict_constraints: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self):
        if type(self.max_chiplets) is not int or self.max_chiplets < 1:
            raise ValueError("max_chiplets must be positive")
        for obj in (self.chiplet, self.network, self.power):
            for name, value in vars(obj).items():
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"{name} must be finite and nonnegative")
        for value in (self.chiplet.pe_rows, self.chiplet.pe_cols,
                      self.chiplet.frequency_hz, self.chiplet.utilization,
                      self.chiplet.sram_mb, self.chiplet.width_mm,
                      self.chiplet.op_per_mac, self.chiplet.ops_per_pe_per_cycle,
                      self.network.link_bandwidth_bits_per_cycle):
            if value <= 0:
                raise ValueError("compute capacity, SRAM, dimensions and bandwidth must be positive")
        if self.chiplet.utilization > 1:
            raise ValueError("utilization must be <= 1")
        if self.rapidchiplet.backend not in ("auto", "official", "local"):
            raise ValueError("backend must be auto, official or local")
        for name in ("pe_rows", "pe_cols"):
            if type(getattr(self.chiplet, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        allowed_ppa = {"max_latency_ns", "max_area_mm2", "max_power_w"}
        if self.strict_constraints.keys() - {"latency", "area", "power"} or any(
            type(value) is not bool for value in self.strict_constraints.values()
        ):
            raise ValueError("strict_constraints accepts latency/area/power booleans")
        if self.ppa.keys() - allowed_ppa:
            raise ValueError("ppa accepts only latency, area and power limits; FPS is output only")
        for name, value in self.ppa.items():
            if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
                raise ValueError(f"{name} must be positive or +inf")


def load_config(path: str | Path) -> EvalConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if "target_fps" in raw["evaluation"]:
        raise ValueError("Remove evaluation.target_fps: FPS is a reported metric, not a design input")

    chiplet = ChipletConfig(**raw["chiplet"])
    network = NetworkConfig(**raw["network"])
    power = PowerConfig(**raw["power"])
    rapid_values = dict(raw["rapidchiplet"])
    rapid_root = Path(rapid_values["root"]).expanduser()
    if not rapid_root.is_absolute():
        rapid_root = Path(path).resolve().parent / rapid_root
    rapid_values["root"] = str(rapid_root.resolve())
    rapidchiplet = RapidChipletConfig(**rapid_values)
    return EvalConfig(
        max_chiplets=raw["evaluation"]["max_chiplets"],
        chiplet=chiplet,
        network=network,
        power=power,
        rapidchiplet=rapidchiplet,
        ppa=raw.get("ppa", {}),
        search=raw.get("search", {}),
        experiment=raw.get("experiment", {}),
        strict_constraints=raw.get("strict_constraints", {}),
    )
