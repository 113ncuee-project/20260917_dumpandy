"""Batch=1 end-to-end latency estimation.

RapidChiplet reports a traffic-weighted network path latency.  That value is
useful for inspecting the inter-chiplet network, but it is not the latency of
one CNN inference.  This module follows the E2E model used by the
``260815_cnn-e2e-constrained-ppa`` reference project:

    E2E = sum(group compute time) + sum(boundary communication time)

Each boundary communication time is the sum of the bottleneck-link
serialization time and the longest routed path latency for that boundary.
The path latency uses the Rapid-compatible endpoint/relay/PHY formula on the
same shortest-path-lowest-ID routing table used by this repository.

The current block-level design also has intra-group mapping traffic for
output-channel, input-channel, and spatial parallelism.  Those transfers are
included as additional communication events so that a mapping action changes
the E2E metric as well as Rapid's network diagnostic.

This is an analytical Batch=1 proxy, not a cycle-accurate accelerator or RTL
model.  It intentionally does not model cache/DRAM stalls, queues, runtime
scheduling, contention, or compute/communication overlap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import EvalConfig
from .mapping import MappingPlan
from .model import ModelSpec
from .routing import shortest_path_lowest_id_first
from .topology import Topology
from .workload import WorkloadPartition

BYTES_PER_MB = 1024.0 * 1024.0
BITS_PER_MB = BYTES_PER_MB * 8.0


@dataclass(frozen=True)
class E2ELatencyResult:
    """Auditable components of the Batch=1 E2E estimate."""

    feasible: bool
    compute_latency_sum_s: float
    communication_serialization_sum_s: float
    communication_path_latency_sum_s: float
    communication_latency_sum_s: float
    estimated_e2e_latency_s: float
    estimated_e2e_latency_ns: float
    group_compute_times_s: tuple[float, ...]
    communication_event_times_s: tuple[float, ...]
    boundary_timings: tuple[dict[str, object], ...]
    compute_limited_fps: float
    pipeline_initiation_interval_s: float
    pipeline_fps: float
    path_latency_source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "compute_latency_sum_s": self.compute_latency_sum_s,
            "communication_serialization_sum_s": self.communication_serialization_sum_s,
            "communication_path_latency_sum_s": self.communication_path_latency_sum_s,
            "communication_latency_sum_s": self.communication_latency_sum_s,
            "estimated_e2e_latency_s": self.estimated_e2e_latency_s,
            "estimated_e2e_latency_ns": self.estimated_e2e_latency_ns,
            "group_compute_times_s": list(self.group_compute_times_s),
            "communication_event_times_s": list(self.communication_event_times_s),
            "boundary_timings": list(self.boundary_timings),
            "compute_limited_fps": self.compute_limited_fps,
            "pipeline_initiation_interval_s": self.pipeline_initiation_interval_s,
            "pipeline_fps": self.pipeline_fps,
            "path_latency_source": self.path_latency_source,
        }


def estimate_batch1_e2e_latency(
    model: ModelSpec,
    workload: WorkloadPartition,
    mapping_plan: MappingPlan,
    topology: Topology,
    cfg: EvalConfig,
) -> E2ELatencyResult:
    """Estimate one inference using group compute and communication events.

    ``workload.group_specs`` contains contiguous ``(start, end, chiplets)``
    records.  Group boundaries use the reference project's all-to-all
    boundary-flow construction.  Mapping traffic is evaluated separately as
    an intra-group event, which preserves the semantics of the current RL
    mapping action.
    """

    if not workload.group_specs:
        raise ValueError("E2E estimation requires explicit group_specs")
    if len(mapping_plan.groups) != len(workload.group_specs):
        raise ValueError("mapping plan and workload group count do not match")

    group_chiplets = _group_chiplet_ids(workload.group_specs)
    group_compute_times_s = tuple(
        _group_compute_time_s(model, group, mapping_group, cfg)
        for group, mapping_group in zip(workload.group_specs, mapping_plan.groups)
    )

    routes = shortest_path_lowest_id_first(topology)
    frequency_hz = max(cfg.chiplet.frequency_hz, 1e-12)
    link_bandwidth_bits_per_cycle = max(
        cfg.network.link_bandwidth_bits_per_cycle,
        1e-12,
    )

    event_times: list[float] = []
    boundary_timings: list[dict[str, object]] = []

    # This is the reference E2E construction: each adjacent group boundary
    # sends the boundary tensor from every source chiplet to every destination
    # chiplet, with equal traffic per source/destination pair.
    for group_index in range(len(workload.group_specs) - 1):
        _start, next_start, _next_parts = workload.group_specs[group_index + 1]
        boundary_mb = model.blocks[next_start - 1].output_mb
        sources = group_chiplets[group_index]
        destinations = group_chiplets[group_index + 1]
        pair_count = max(1, len(sources) * len(destinations))
        pair_bits = boundary_mb * BITS_PER_MB / pair_count
        flows = tuple(
            (source, destination, pair_bits)
            for source in sources
            for destination in destinations
        )
        timing = _communication_event(
            event_kind="group_boundary",
            source_group_index=group_index,
            destination_group_index=group_index + 1,
            flows=flows,
            routes=routes,
            topology=topology,
            cfg=cfg,
            frequency_hz=frequency_hz,
            link_bandwidth_bits_per_cycle=link_bandwidth_bits_per_cycle,
            nominal_traffic_bits=boundary_mb * BITS_PER_MB,
            pair_count=pair_count,
        )
        event_times.append(float(timing["service_s"]))
        boundary_timings.append(timing)

    # Parallel mapping creates a second class of communication.  Treat all
    # edges belonging to one mapping group as one event so simultaneous
    # broadcasts/reductions use the same bottleneck-link rule as a boundary.
    mapping_flows_by_group: dict[int, list[tuple[int, int, float]]] = {}
    for edge in mapping_plan.traffic_edges:
        group_index = int(edge["group"])
        source = int(edge["source"])
        target = int(edge["target"])
        bits = float(edge["mb"]) * BITS_PER_MB
        if bits > 0.0 and source != target:
            mapping_flows_by_group.setdefault(group_index, []).append(
                (source, target, bits)
            )

    for group_index in sorted(mapping_flows_by_group):
        flows = tuple(mapping_flows_by_group[group_index])
        timing = _communication_event(
            event_kind="intra_group_mapping",
            source_group_index=group_index,
            destination_group_index=group_index,
            flows=flows,
            routes=routes,
            topology=topology,
            cfg=cfg,
            frequency_hz=frequency_hz,
            link_bandwidth_bits_per_cycle=link_bandwidth_bits_per_cycle,
            nominal_traffic_bits=sum(flow[2] for flow in flows),
            pair_count=len(flows),
        )
        event_times.append(float(timing["service_s"]))
        boundary_timings.append(timing)

    compute_latency_sum_s = sum(group_compute_times_s)
    communication_serialization_sum_s = sum(
        float(timing["serialization_s"]) for timing in boundary_timings
    )
    communication_path_latency_sum_s = sum(
        float(timing["path_latency_s"]) for timing in boundary_timings
    )
    communication_latency_sum_s = sum(event_times)
    estimated_e2e_latency_s = compute_latency_sum_s + communication_latency_sum_s

    compute_interval_s = max(group_compute_times_s, default=0.0)
    pipeline_interval_s = max(
        (*group_compute_times_s, *event_times),
        default=0.0,
    )
    compute_limited_fps = (
        1.0 / compute_interval_s if compute_interval_s > 0.0 else math.inf
    )
    pipeline_fps = (
        1.0 / pipeline_interval_s if pipeline_interval_s > 0.0 else math.inf
    )

    return E2ELatencyResult(
        feasible=mapping_plan.feasible,
        compute_latency_sum_s=compute_latency_sum_s,
        communication_serialization_sum_s=communication_serialization_sum_s,
        communication_path_latency_sum_s=communication_path_latency_sum_s,
        communication_latency_sum_s=communication_latency_sum_s,
        estimated_e2e_latency_s=estimated_e2e_latency_s,
        estimated_e2e_latency_ns=estimated_e2e_latency_s * 1e9,
        group_compute_times_s=group_compute_times_s,
        communication_event_times_s=tuple(event_times),
        boundary_timings=tuple(boundary_timings),
        compute_limited_fps=compute_limited_fps,
        pipeline_initiation_interval_s=pipeline_interval_s,
        pipeline_fps=pipeline_fps,
        path_latency_source="rapid_compatible_per_flow_splif_reconstruction",
    )


def _group_chiplet_ids(
    groups: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[int, ...], ...]:
    next_chiplet = 0
    result: list[tuple[int, ...]] = []
    for _start, _end, parts in groups:
        if parts < 1:
            raise ValueError("group chiplet count must be positive")
        result.append(tuple(range(next_chiplet, next_chiplet + parts)))
        next_chiplet += parts
    return tuple(result)


def _group_compute_time_s(
    model: ModelSpec,
    group: tuple[int, int, int],
    mapping_group,
    cfg: EvalConfig,
) -> float:
    start, end, parts = group
    group_ops = sum(
        model.blocks[index].macs_g * 1e9 * cfg.chiplet.op_per_mac
        for index in range(start, end)
    )
    ops_per_chiplet = group_ops / max(parts, 1)
    base_ops_per_second = (
        cfg.chiplet.pe_rows
        * cfg.chiplet.pe_cols
        * cfg.chiplet.ops_per_pe_per_cycle
        * cfg.chiplet.frequency_hz
        * cfg.chiplet.utilization
    )
    effective_ops_per_second = base_ops_per_second * mapping_group.compute_efficiency
    return ops_per_chiplet / max(effective_ops_per_second, 1e-12)


def _communication_event(
    *,
    event_kind: str,
    source_group_index: int,
    destination_group_index: int,
    flows: tuple[tuple[int, int, float], ...],
    routes: dict[tuple[int, int], tuple[int, ...]],
    topology: Topology,
    cfg: EvalConfig,
    frequency_hz: float,
    link_bandwidth_bits_per_cycle: float,
    nominal_traffic_bits: float,
    pair_count: int,
) -> dict[str, object]:
    link_loads: dict[tuple[int, int], float] = {
        direction: 0.0
        for edge in topology.edges
        for direction in ((edge.a, edge.b), (edge.b, edge.a))
    }
    max_path_cycles = 0.0
    max_path: tuple[int, ...] = ()
    total_traffic_bits = 0.0
    for source, destination, bits in flows:
        if source == destination or bits <= 0.0:
            continue
        path = routes[(source, destination)]
        path_cycles = _rapid_compatible_path_cycles(path, topology, cfg)
        if path_cycles >= max_path_cycles:
            max_path_cycles = path_cycles
            max_path = path
        for left, right in zip(path, path[1:]):
            link_loads[(left, right)] += bits
        total_traffic_bits += bits

    bottleneck_link, bottleneck_link_bits = _max_link_load(link_loads)
    serialization_s = bottleneck_link_bits / (
        link_bandwidth_bits_per_cycle * frequency_hz
    )
    path_latency_s = max_path_cycles / frequency_hz
    service_s = serialization_s + path_latency_s
    return {
        "kind": event_kind,
        "source_group_index": source_group_index,
        "destination_group_index": destination_group_index,
        "traffic_bits": nominal_traffic_bits,
        "routed_traffic_bits": total_traffic_bits,
        "pair_count": pair_count,
        "bottleneck_link": list(bottleneck_link) if bottleneck_link else None,
        "bottleneck_link_bits": bottleneck_link_bits,
        "max_path": list(max_path),
        "max_path_cycles": max_path_cycles,
        "serialization_s": serialization_s,
        "path_latency_s": path_latency_s,
        "service_s": service_s,
    }


def _max_link_load(
    link_loads: dict[tuple[int, int], float],
) -> tuple[tuple[int, int] | None, float]:
    if not link_loads:
        return None, 0.0
    link = max(link_loads, key=link_loads.get)
    return link, link_loads[link]


def _rapid_compatible_path_cycles(
    path: tuple[int, ...],
    topology: Topology,
    cfg: EvalConfig,
) -> float:
    """Match the reference Rapid-compatible per-flow path formula."""

    if len(path) < 2:
        return 0.0
    endpoint_cycles = (
        cfg.chiplet.internal_latency_cycles + cfg.chiplet.phy_latency_cycles
    )
    relay_cycles = (
        cfg.chiplet.internal_latency_cycles
        + 2.0 * cfg.chiplet.phy_latency_cycles
    )
    link_cycles = sum(
        math.ceil(
            cfg.network.link_latency_base_cycles
            + cfg.network.link_latency_cycles_per_mm
            * topology.edge_lengths()[tuple(sorted((left, right)))]
        )
        for left, right in zip(path, path[1:])
    )
    relay_count = max(0, len(path) - 2)
    return 3.0 + 2.0 * endpoint_cycles + relay_count * relay_cycles + link_cycles
