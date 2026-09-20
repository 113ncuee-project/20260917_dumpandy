from __future__ import annotations

import importlib
import math
import sys
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import EvalConfig
from .rapid_proxy import compute_latency, compute_throughput
from .routing import shortest_paths_for_pairs
from .topology import Topology
from .workload import WorkloadPartition


_LOCAL_PROXY_WARNED = False


@dataclass(frozen=True)
class RapidChipletMetrics:
    avg_latency_cycles: float
    avg_latency_ns: float
    min_latency_cycles: float
    max_latency_cycles: float
    network_limited_fps: float
    aggregate_throughput_bits_per_cycle: float
    total_area_mm2: float
    total_chiplet_area_mm2: float
    chip_width_mm: float
    chip_height_mm: float
    total_power_w: float
    total_chiplet_power_w: float
    total_interposer_power_w: float
    total_link_power_w: float
    link_count: int
    min_link_length_mm: float
    avg_link_length_mm: float
    max_link_length_mm: float
    bottleneck_link: tuple[int, int] | None
    graph: dict[str, Any]
    backend: str = "local"
    effective_hardware: dict[str, Any] = field(default_factory=dict)


def evaluate_with_rapidchiplet(
    topology: Topology,
    workload: WorkloadPartition,
    cfg: EvalConfig,
    design_name: str,
) -> RapidChipletMetrics:
    global _LOCAL_PROXY_WARNED
    if cfg.rapidchiplet.backend == "local":
        return _evaluate_with_local_proxy(topology, workload, cfg)
    try:
        rc = _load_rapidchiplet_module(cfg.rapidchiplet.root)
    except (FileNotFoundError, ModuleNotFoundError, ImportError) as exc:
        if cfg.rapidchiplet.backend == "official":
            raise
        if not _LOCAL_PROXY_WARNED:
            warnings.warn(
                f"Using local RapidChiplet proxy because the official engine is unavailable: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            _LOCAL_PROXY_WARNED = True
        return _evaluate_with_local_proxy(topology, workload, cfg)

    inputs = build_effective_inputs(topology, workload, cfg, design_name)
    packaging = inputs["packaging"]
    rc_topology = inputs["topology"]
    routing_table = inputs["routing_table"]
    traffic_by_chiplet = inputs["traffic_by_chiplet"]
    # Seed the supported intermediary instead of relying on an upstream JSON
    # override extension. Both directions use the configured bits/cycle.
    intermediates: dict[str, Any] = {"link_bandwidths": {
        (("chiplet", a), ("chiplet", b)): cfg.network.link_bandwidth_bits_per_cycle
        for e in topology.edges for a, b in ((e.a, e.b), (e.b, e.a))
    }}
    do_compute = {metric: False for metric in rc.metrics}
    for metric in ("area_summary", "power_summary"):
        do_compute[metric] = True
    if rc_topology:
        do_compute["link_summary"] = True
    if traffic_by_chiplet:
        do_compute["latency"] = True
        do_compute["throughput"] = True

    outputs = rc.rapidchiplet(inputs, intermediates, do_compute, design_name, verbose=False, validate=False)
    area = outputs["area_summary"]
    power = outputs["power_summary"]
    link_lengths = intermediates.get("link_lengths", {})
    link_bandwidths = intermediates.get("link_bandwidths", {})
    link_power_w = _compute_link_power(packaging, link_lengths)
    latency = outputs.get("latency", {})
    throughput = outputs.get("throughput", {})

    avg_latency_cycles = float(latency.get("avg", 0.0))
    aggregate_throughput = float(throughput.get("aggregate_throughput", math.inf))
    total_traffic = workload.total_traffic_bits_per_inference
    network_limited_fps = (
        aggregate_throughput * cfg.chiplet.frequency_hz / total_traffic
        if total_traffic > 0 and math.isfinite(aggregate_throughput)
        else math.inf
    )
    link_lengths_once = [length for link, length in link_lengths.items() if link[0] < link[1]]
    bottleneck_link = _find_bottleneck_link(traffic_by_chiplet, routing_table, link_bandwidths)

    return RapidChipletMetrics(
        avg_latency_cycles=avg_latency_cycles,
        avg_latency_ns=avg_latency_cycles / cfg.chiplet.frequency_hz * 1e9,
        min_latency_cycles=float(latency.get("min", 0.0)),
        max_latency_cycles=float(latency.get("max", 0.0)),
        network_limited_fps=network_limited_fps,
        aggregate_throughput_bits_per_cycle=aggregate_throughput,
        total_area_mm2=float(area["total_interposer_area"]),
        total_chiplet_area_mm2=float(area["total_chiplet_area"]),
        chip_width_mm=float(area["chip_width"]),
        chip_height_mm=float(area["chip_height"]),
        total_power_w=float(power["total_power"]) + link_power_w,
        total_chiplet_power_w=float(power["total_chiplet_power"]),
        total_interposer_power_w=float(power["total_interposer_power"]),
        total_link_power_w=link_power_w,
        link_count=len(rc_topology),
        min_link_length_mm=min(link_lengths_once, default=0.0),
        avg_link_length_mm=sum(link_lengths_once) / len(link_lengths_once) if link_lengths_once else 0.0,
        max_link_length_mm=max(link_lengths_once, default=0.0),
        bottleneck_link=bottleneck_link,
        graph=_build_graph(topology, workload, rc_topology, link_lengths),
        backend="official", effective_hardware=effective_hardware(cfg),
    )


def _evaluate_with_local_proxy(
    topology: Topology,
    workload: WorkloadPartition,
    cfg: EvalConfig,
) -> RapidChipletMetrics:
    routes = shortest_paths_for_pairs(topology, workload.traffic_bits_per_inference)
    latency = compute_latency(
        topology=topology,
        routes=routes,
        traffic_bits_per_inference=workload.traffic_bits_per_inference,
        chiplet=cfg.chiplet,
        network=cfg.network,
    )
    throughput = compute_throughput(
        topology=topology,
        routes=routes,
        traffic_bits_per_inference=workload.traffic_bits_per_inference,
        chiplet=cfg.chiplet,
        network=cfg.network,
    )

    link_lengths_once = [edge.length_mm for edge in topology.edges]
    total_chiplet_area = topology.node_count * cfg.chiplet.width_mm * cfg.chiplet.width_mm
    total_area = _local_package_area(topology, cfg)
    total_chiplet_power = _local_chiplet_power(workload, cfg)
    total_link_power = _local_link_power(topology, cfg)
    aggregate_throughput_cycles = (
        throughput.aggregate_throughput_bits_per_second / cfg.chiplet.frequency_hz
        if math.isfinite(throughput.aggregate_throughput_bits_per_second)
        else math.inf
    )

    return RapidChipletMetrics(
        avg_latency_cycles=latency.avg_cycles,
        avg_latency_ns=latency.avg_ns,
        min_latency_cycles=latency.min_cycles,
        max_latency_cycles=latency.max_cycles,
        network_limited_fps=throughput.saturation_fps,
        aggregate_throughput_bits_per_cycle=aggregate_throughput_cycles,
        total_area_mm2=total_area,
        total_chiplet_area_mm2=total_chiplet_area,
        chip_width_mm=_local_package_width(topology, cfg),
        chip_height_mm=_local_package_height(topology, cfg),
        total_power_w=total_chiplet_power + total_link_power,
        total_chiplet_power_w=total_chiplet_power,
        total_interposer_power_w=0.0,
        total_link_power_w=total_link_power,
        link_count=len(topology.edges),
        min_link_length_mm=min(link_lengths_once, default=0.0),
        avg_link_length_mm=sum(link_lengths_once) / len(link_lengths_once) if link_lengths_once else 0.0,
        max_link_length_mm=max(link_lengths_once, default=0.0),
        bottleneck_link=throughput.bottleneck_link,
        graph=_build_local_graph(topology, workload),
        backend="local", effective_hardware=effective_hardware(cfg),
    )


def _load_rapidchiplet_module(root: str):
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(
            f"RapidChiplet root not found: {root_path}. Update configs/defaults.json rapidchiplet.root."
        )
    root_str = str(root_path)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    module = importlib.import_module("rapidchiplet")
    if Path(module.__file__).resolve().parent != root_path.resolve():
        raise ImportError("A different RapidChiplet root is already loaded; use a separate process")
    return module


def chiplet_power_w(cfg):
    # Same convention as the supplied 0815 adapter: one aggregate PHY term.
    return cfg.power.chiplet_static_w + cfg.power.chiplet_peak_dynamic_w * cfg.chiplet.utilization + cfg.power.phy_w


def effective_hardware(cfg):
    return dict(chiplet=asdict(cfg.chiplet), network=asdict(cfg.network), power=asdict(cfg.power),
                chiplet_power_w=chiplet_power_w(cfg), packaging_is_active=False,
                power_model="0815_fixed_utilization_plus_length_static_links",
                dynamic_link_power_included=False,
                link_geometry="chiplet_center_to_center", bandwidth_unit="bits/cycle/direction")


def _build_chiplets(cfg):
    width = cfg.chiplet.width_mm
    return {cfg.rapidchiplet.chiplet_name: dict(
        dimensions={"x": width, "y": width}, type="compute", relay=True,
        phys=[dict(x=width / 2, y=width / 2, fraction_bump_area=.25) for _ in range(4)],
        fraction_power_bumps=.5, technology="configured", power=chiplet_power_w(cfg),
        internal_latency=cfg.chiplet.internal_latency_cycles, unit_count=1)}


def build_effective_inputs(topology, workload, cfg, design_name="configured"):
    packaging = dict(link_routing="euclidean", link_latency_type="function",
        link_latency=f"lambda x: {cfg.network.link_latency_base_cycles!r} + {cfg.network.link_latency_cycles_per_mm!r} * x",
        link_power_type="function", link_power=f"lambda x: {cfg.power.link_static_w_per_mm!r} * x",
        packaging_yield=.9, bump_pitch=.05, non_data_wires=12, is_active=False,
        latency_irouter=0, power_irouter=0, has_interposer=True, interposer_technology="configured")
    links = _build_topology(topology)
    values = dict(chiplets=_build_chiplets(cfg), placement=_build_placement(topology, cfg),
        topology=links, packaging=packaging, technologies={"configured": {"phy_latency": cfg.chiplet.phy_latency_cycles}},
        routing_table=_build_splif_routing_table(topology.node_count, links),
        traffic_by_chiplet=dict(workload.traffic_bits_per_inference))
    values["design"] = dict(design_name=design_name, **{k: "in-memory" for k in values})
    return values


def _build_placement(topology: Topology, cfg: EvalConfig) -> dict[str, Any]:
    return {
        "chiplets": [
            {
                "position": {"x": topology.positions[node][0], "y": topology.positions[node][1]},
                "rotation": 0,
                "name": cfg.rapidchiplet.chiplet_name,
            }
            for node in range(topology.node_count)
        ],
        "interposer_routers": [],
    }


def _build_topology(topology: Topology) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for edge in topology.edges:
        phy_a, phy_b = _endpoint_phys(topology, edge.a, edge.b)
        links.append(
            {
                "ep1": {"type": "chiplet", "outer_id": edge.a, "inner_id": phy_a},
                "ep2": {"type": "chiplet", "outer_id": edge.b, "inner_id": phy_b},
                "color": "#000099",
            }
        )
    return links


def _endpoint_phys(topology: Topology, a: int, b: int) -> tuple[int, int]:
    ax, ay = topology.positions[a]
    bx, by = topology.positions[b]
    dx = bx - ax
    dy = by - ay
    if abs(dx) >= abs(dy):
        return (2, 0) if dx >= 0 else (0, 2)
    return (1, 3) if dy >= 0 else (3, 1)


def _build_splif_routing_table(node_count: int, links: list[dict[str, Any]]) -> dict[str, Any]:
    adj: dict[tuple[str, int], list[tuple[str, int]]] = {
        ("chiplet", node): [] for node in range(node_count)
    }
    for link in links:
        a = (link["ep1"]["type"], link["ep1"]["outer_id"])
        b = (link["ep2"]["type"], link["ep2"]["outer_id"])
        adj[a].append(b)
        adj[b].append(a)
    for node in adj:
        adj[node].sort(key=_node_sort_key)

    table: dict[tuple[str, int], dict[tuple[str, int], tuple[str, int] | None]] = {}
    for src_id in range(node_count):
        src = ("chiplet", src_id)
        table[src] = {}
        for dst_id in range(node_count):
            dst = ("chiplet", dst_id)
            if src == dst:
                table[src][dst] = None
            else:
                path = _shortest_path_lowest_id_first(src, dst, adj)
                table[src][dst] = path[1]
    return {"type": "default", "table": table}


def _shortest_path_lowest_id_first(
    src: tuple[str, int],
    dst: tuple[str, int],
    adj: dict[tuple[str, int], list[tuple[str, int]]],
) -> tuple[tuple[str, int], ...]:
    queue: list[tuple[tuple[str, int], ...]] = [(src,)]
    seen = {src}
    while queue:
        path = queue.pop(0)
        node = path[-1]
        if node == dst:
            return path
        for nxt in adj[node]:
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append(path + (nxt,))
    raise ValueError(f"No RapidChiplet route from {src} to {dst}")


def _node_sort_key(node: tuple[str, int]) -> tuple[int, int]:
    return (0 if node[0] == "chiplet" else 1, node[1])


def _compute_link_power(packaging: dict[str, Any], link_lengths: dict[Any, float]) -> float:
    # Mirrors RapidChiplet's compute_power_summary link-power block. The upstream
    # function computes this value internally but does not expose it in outputs.
    if packaging["link_power_type"] == "constant":
        return len(link_lengths) * float(packaging["link_power"]) / 2
    link_power_fn = eval(packaging["link_power"])
    return sum(link_power_fn(length) for length in link_lengths.values()) / 2


def _local_package_width(topology: Topology, cfg: EvalConfig) -> float:
    xs = [position[0] for position in topology.positions.values()]
    if not xs:
        return 0.0
    return max(xs) - min(xs) + cfg.chiplet.width_mm


def _local_package_height(topology: Topology, cfg: EvalConfig) -> float:
    ys = [position[1] for position in topology.positions.values()]
    if not ys:
        return 0.0
    return max(ys) - min(ys) + cfg.chiplet.width_mm


def _local_package_area(topology: Topology, cfg: EvalConfig) -> float:
    return _local_package_width(topology, cfg) * _local_package_height(topology, cfg)


def _local_chiplet_power(workload, cfg):
    return len(workload.ops_per_chiplet) * chiplet_power_w(cfg)


def _local_link_power(topology, cfg):
    return sum(e.length_mm * cfg.power.link_static_w_per_mm for e in topology.edges)


def _build_local_graph(topology: Topology, workload: WorkloadPartition) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": node,
                "x": topology.positions[node][0],
                "y": topology.positions[node][1],
                "stage": workload.stage_labels[node] if node < len(workload.stage_labels) else "",
                "ops": workload.ops_per_chiplet[node] if node < len(workload.ops_per_chiplet) else 0.0,
            }
            for node in range(topology.node_count)
        ],
        "physical_links": [
            {"source": edge.a, "target": edge.b, "length_mm": edge.length_mm}
            for edge in topology.edges
        ],
        "traffic_edges": [
            {"source": src, "target": dst, "mb": bits / 8 / 1024 / 1024}
            for (src, dst), bits in sorted(workload.traffic_bits_per_inference.items())
        ],
    }


def _find_bottleneck_link(
    traffic_by_chiplet: dict[tuple[int, int], float],
    routing_table: dict[str, Any],
    link_bandwidths: dict[Any, float],
) -> tuple[int, int] | None:
    if not traffic_by_chiplet or not link_bandwidths:
        return None

    table = routing_table["table"]
    routing_type = routing_table["type"]
    link_loads = {link: 0.0 for link in link_bandwidths}

    for (src_id, dst_id), traffic_bits in traffic_by_chiplet.items():
        previous_node: tuple[str, int] | str = "-1"
        current_node = ("chiplet", src_id)
        dst_node = ("chiplet", dst_id)
        while current_node != dst_node:
            if routing_type == "default":
                next_node = tuple(table[current_node][dst_node])
            elif routing_type == "extended":
                next_node = tuple(table[current_node][dst_node][previous_node])
            else:
                raise ValueError(f"Unsupported RapidChiplet routing table type: {routing_type}")
            link_loads[(current_node, next_node)] += traffic_bits
            previous_node = current_node
            current_node = next_node

    loaded_links = [
        (link_bandwidths[link] / load, link)
        for link, load in link_loads.items()
        if load > 0
    ]
    if not loaded_links:
        return None

    _throughput, ((src_type, src_id), (dst_type, dst_id)) = min(
        loaded_links,
        key=lambda item: (item[0], item[1]),
    )
    if src_type != "chiplet" or dst_type != "chiplet":
        return None
    return (src_id, dst_id)


def _build_graph(
    topology: Topology,
    workload: WorkloadPartition,
    links: list[dict[str, Any]],
    link_lengths: dict[Any, float],
) -> dict[str, Any]:
    physical_links = []
    for link in links:
        source = link["ep1"]["outer_id"]
        target = link["ep2"]["outer_id"]
        length = link_lengths.get((("chiplet", source), ("chiplet", target)), 0.0)
        physical_links.append({"source": source, "target": target, "length_mm": length})
    return {
        "nodes": [
            {
                "id": node,
                "x": topology.positions[node][0],
                "y": topology.positions[node][1],
                "stage": workload.stage_labels[node] if node < len(workload.stage_labels) else "",
                "ops": workload.ops_per_chiplet[node] if node < len(workload.ops_per_chiplet) else 0.0,
            }
            for node in range(topology.node_count)
        ],
        "physical_links": physical_links,
        "traffic_edges": [
            {"source": src, "target": dst, "mb": bits / 8 / 1024 / 1024}
            for (src, dst), bits in sorted(workload.traffic_bits_per_inference.items())
        ],
    }
