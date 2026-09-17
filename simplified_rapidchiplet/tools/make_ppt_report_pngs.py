from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "latest"
OUT = RESULTS / "ppt_assets"
OUT.mkdir(parents=True, exist_ok=True)

WIDTH = 1600
HEIGHT = 900

INK = "#17202a"
MUTED = "#5d6875"
LINE = "#d8dee6"
SOFT = "#f5f7fa"
HEADER = "#eef2f6"
BLUE = "#2f6fad"
GREEN = "#117a65"
RED = "#a93226"
ORANGE = "#b86b1b"
PURPLE = "#7157a8"
TEAL = "#4d7f87"
WHITE = "#ffffff"


def main() -> None:
    summary = read_json(RESULTS / "pareto_dp" / "balanced" / "summary.json")
    comparison = read_csv(RESULTS / "search_comparison_with_bonus.csv")
    report_time = (RESULTS / "report.html").stat().st_mtime
    generated = timestamp(report_time)

    resnet_mesh = next(row for row in summary if row["model"] == "resnet50" and row["topology"] == "mesh")
    resnet_tree = next(row for row in summary if row["model"] == "resnet50" and row["topology"] == "tree")
    shufflenet = next(row for row in summary if row["model"] == "shufflenet_v2_x1_0" and row["topology"] == "mesh")
    resnet_goals = [
        row
        for goal in ("balanced", "latency", "power", "area")
        for row in comparison
        if row["ppa_goal"] == goal and row["search"] == "pareto-dp" and row["model"] == "resnet50"
    ]
    shufflenet_goals = [
        row
        for goal in ("balanced", "latency", "power", "area")
        for row in comparison
        if row["ppa_goal"] == goal and row["search"] == "pareto-dp" and row["model"] == "shufflenet_v2_x1_0"
    ]
    resnet_goal_topology_rows = load_resnet_goal_topology_rows()

    draw_overview(summary, resnet_mesh, shufflenet, generated)
    draw_goal_tradeoff(resnet_goals, generated)
    draw_shufflenet_goal_tradeoff(shufflenet_goals, generated)
    draw_resnet_all_goal_topology_summary(resnet_goal_topology_rows, generated)
    draw_resnet_best_partitions_by_goal(generated)
    draw_partition(resnet_mesh, generated)
    draw_topology(resnet_mesh, resnet_tree, generated)
    draw_resnet_topology_metric_comparison(resnet_mesh, resnet_tree, generated)
    draw_resnet_topology_connection_graphs(resnet_mesh, resnet_tree, generated)
    draw_search_check(comparison, generated)

    print(f"Wrote PNG assets to {OUT}")


def load_resnet_goal_topology_rows() -> list[dict]:
    rows = []
    for goal in ("balanced", "latency", "power", "area"):
        goal_rows = [
            row
            for row in read_json(RESULTS / "pareto_dp" / goal / "summary.json")
            if row["model"] == "resnet50"
        ]
        best_score = min(num(row["ppa_score"]) for row in goal_rows)
        for row in goal_rows:
            rows.append({**row, "selected": num(row["ppa_score"]) == best_score})
    return rows


def draw_overview(summary: list[dict], resnet: dict, shuffle: dict, generated: str) -> None:
    img, draw = canvas()
    header(draw, "Simulation results are clearest as a decision story", "Show the best feasible design first, then explain why the PPA objective selects it.", generated)

    x0, y0 = 70, 175
    gap = 18
    card_w = (WIDTH - 140 - gap * 3) // 4
    cards = [
        ("ResNet50 best", f"{num(resnet['achieved_fps']):.2f} FPS", f"{resnet['selected_chiplets']}/{resnet['available_chiplets']} chiplets, PPA {num(resnet['ppa_score']):.3f}", GREEN),
        ("ResNet50 package", f"{num(resnet['total_area_mm2']):.1f} mm2", f"{num(resnet['total_power_w']):.1f} W, {num(resnet['avg_latency_ns']):.1f} ns", BLUE),
        ("ShuffleNetV2 best", f"{num(shuffle['achieved_fps']):.2f} FPS", f"single chiplet, PPA {num(shuffle['ppa_score']):.3f}", PURPLE),
        ("Target", f"{num(resnet['target_fps']):.0f} FPS", "balanced goal, Pareto-DP", ORANGE),
    ]
    for i, item in enumerate(cards):
        metric_card(draw, x0 + i * (card_w + gap), y0, card_w, 118, *item)

    table_x, table_y, table_w, table_h = 70, 335, 930, 350
    panel(draw, table_x, table_y, table_w, table_h)
    text(draw, "Balanced Pareto-DP winners", table_x + 24, table_y + 20, 30, bold=True)
    columns = [("Model", 210), ("Topology", 125), ("Status", 115), ("FPS", 120), ("Chiplets", 140), ("PPA", 100)]
    rows = [
        [model_name(r["model"]), r["topology"], "MET" if r["target_met"] else "MISS", f"{num(r['achieved_fps']):.2f}", f"{r['selected_chiplets']}/{r['available_chiplets']}", f"{num(r['ppa_score']):.3f}"]
        for r in summary
    ]
    data_table(draw, table_x + 24, table_y + 76, columns, rows, row_h=48)

    right_x, right_y = 1030, 335
    panel(draw, right_x, right_y, 500, 350)
    text(draw, "Presentation takeaway", right_x + 24, right_y + 20, 30, bold=True)
    wrapped(draw, "Balanced objective selects mesh for ResNet50: it meets 15 FPS and has lower latency than tree.", right_x + 24, right_y + 82, 450, 30, bold=True, fill=INK)
    callout(draw, right_x + 24, right_y + 230, 452, 82, "ShuffleNetV2 is already satisfied by one chiplet, so it is best used as a contrast case.")

    footer(draw)
    img.save(OUT / "01_latest_result_overview.png")


def draw_goal_tradeoff(rows: list[dict], generated: str) -> None:
    img, draw = canvas()
    header(draw, "PPA goals change the ResNet50 design choice", "Balanced and latency goals meet 15 FPS; power and area goals save resources but miss the target.", generated)

    x, y = 70, 175
    panel(draw, x, y, 1460, 390)
    columns = [
        ("Goal", 155),
        ("Topology", 120),
        ("Status", 110),
        ("FPS", 235),
        ("Chiplets", 125),
        ("Area", 215),
        ("Power", 205),
        ("Latency", 140),
        ("PPA", 100),
    ]
    max_fps = max([num(r["achieved_fps"]) for r in rows] + [15])
    max_area = max(num(r["area_mm2"]) for r in rows)
    max_power = max(num(r["power_w"]) for r in rows)

    tx, ty = x + 24, y + 24
    draw.rectangle([tx, ty, tx + sum(w for _, w in columns), ty + 48], fill=HEADER)
    cx = tx
    for title, width in columns:
        text(draw, title, cx + 10, ty + 13, 20, bold=True)
        cx += width
    row_y = ty + 48
    for row in rows:
        draw.line([tx, row_y, tx + sum(w for _, w in columns), row_y], fill=LINE, width=1)
        cx = tx
        values = [
            goal_name(row["ppa_goal"]),
            row["topology"],
            row["status"],
            f"{num(row['achieved_fps']):.2f}",
            f"{row['used_chiplets']}/16",
            f"{num(row['area_mm2']):.1f}",
            f"{num(row['power_w']):.1f}",
            f"{num(row['latency_ns']):.1f} ns",
            f"{num(row['ppa_score']):.3f}",
        ]
        for idx, ((_, width), value) in enumerate(zip(columns, values)):
            fill = GREEN if idx == 1 and value == "MET" else RED if idx == 1 else INK
            text(draw, value, cx + 10, row_y + 14, 20, bold=(idx in (0, 1)), fill=fill)
            if idx == 3:
                bar(draw, cx + 82, row_y + 20, 130, 14, num(row["achieved_fps"]), max_fps, GREEN if row["status"] == "MET" else RED)
            if idx == 5:
                bar(draw, cx + 78, row_y + 20, 115, 14, num(row["area_mm2"]), max_area, BLUE)
            if idx == 6:
                bar(draw, cx + 72, row_y + 20, 105, 14, num(row["power_w"]), max_power, ORANGE)
            cx += width
        row_y += 70
    draw.line([tx, row_y, tx + sum(w for _, w in columns), row_y], fill=LINE, width=1)

    bottom_y = 600
    panels = [
        ("Feasible choice", f"Balanced / latency use mesh with 9 chiplets and achieve {num(rows[0]['achieved_fps']):.2f} FPS.", GREEN),
        ("Power choice", f"Power goal selects mesh with 8 chiplets and {num(rows[2]['power_w']):.1f} W, but misses by {15 - num(rows[2]['achieved_fps']):.2f} FPS.", ORANGE),
        ("Area choice", f"Area goal selects mesh with 6 chiplets and {num(rows[3]['area_mm2']):.1f} mm2, but reaches only {num(rows[3]['achieved_fps']):.2f} FPS.", BLUE),
    ]
    panel_w = (1460 - 22 * 2) // 3
    for i, (title, body, color) in enumerate(panels):
        px = 70 + i * (panel_w + 22)
        panel(draw, px, bottom_y, panel_w, 180)
        text(draw, title, px + 22, bottom_y + 22, 28, bold=True, fill=color)
        wrapped(draw, body, px + 22, bottom_y + 70, panel_w - 44, 29, bold=True)

    footer(draw)
    img.save(OUT / "02_resnet_goal_tradeoff.png")


def draw_shufflenet_goal_tradeoff(rows: list[dict], generated: str) -> None:
    img, draw = canvas()
    header(draw, "PPA goals keep ShuffleNetV2 on a single-chiplet design", "All goals select the same mesh result because one chiplet already exceeds the 15 FPS target.", generated)

    x, y = 70, 175
    panel(draw, x, y, 1460, 390)
    columns = [
        ("Goal", 155),
        ("Topology", 120),
        ("Status", 110),
        ("FPS", 235),
        ("Chiplets", 125),
        ("Area", 215),
        ("Power", 205),
        ("Latency", 140),
        ("PPA", 100),
    ]
    max_fps = max([num(r["achieved_fps"]) for r in rows] + [15])
    max_area = max(num(r["area_mm2"]) for r in rows)
    max_power = max(num(r["power_w"]) for r in rows)

    tx, ty = x + 24, y + 24
    draw.rectangle([tx, ty, tx + sum(w for _, w in columns), ty + 48], fill=HEADER)
    cx = tx
    for title, width in columns:
        text(draw, title, cx + 10, ty + 13, 20, bold=True)
        cx += width
    row_y = ty + 48
    for row in rows:
        draw.line([tx, row_y, tx + sum(w for _, w in columns), row_y], fill=LINE, width=1)
        cx = tx
        values = [
            goal_name(row["ppa_goal"]),
            row["topology"],
            row["status"],
            f"{num(row['achieved_fps']):.2f}",
            f"{row['used_chiplets']}/16",
            f"{num(row['area_mm2']):.1f}",
            f"{num(row['power_w']):.1f}",
            f"{num(row['latency_ns']):.1f} ns",
            f"{num(row['ppa_score']):.3f}",
        ]
        for idx, ((_, width), value) in enumerate(zip(columns, values)):
            fill = GREEN if idx == 2 and value == "MET" else RED if idx == 2 else RED if idx == 1 else INK
            text(draw, value, cx + 10, row_y + 14, 20, bold=(idx in (0, 1, 2)), fill=fill)
            if idx == 3:
                bar(draw, cx + 82, row_y + 20, 130, 14, num(row["achieved_fps"]), max_fps, GREEN if row["status"] == "MET" else RED)
            if idx == 5:
                bar(draw, cx + 78, row_y + 20, 115, 14, num(row["area_mm2"]), max_area, BLUE)
            if idx == 6:
                bar(draw, cx + 72, row_y + 20, 105, 14, num(row["power_w"]), max_power, ORANGE)
            cx += width
        row_y += 70
    draw.line([tx, row_y, tx + sum(w for _, w in columns), row_y], fill=LINE, width=1)

    bottom_y = 600
    panels = [
        ("Same topology", f"All goals select mesh with 1 chiplet and achieve {num(rows[0]['achieved_fps']):.2f} FPS.", GREEN),
        ("Resource use", f"Area stays {num(rows[0]['area_mm2']):.1f} mm2 and power stays {num(rows[0]['power_w']):.1f} W across goals.", BLUE),
        ("Design meaning", "ShuffleNetV2 is lightweight enough that extra chiplets are unnecessary for this target.", ORANGE),
    ]
    panel_w = (1460 - 22 * 2) // 3
    for i, (title, body, color) in enumerate(panels):
        px = 70 + i * (panel_w + 22)
        panel(draw, px, bottom_y, panel_w, 180)
        text(draw, title, px + 22, bottom_y + 22, 28, bold=True, fill=color)
        wrapped(draw, body, px + 22, bottom_y + 70, panel_w - 44, 29, bold=True)

    footer(draw)
    img.save(OUT / "06_shufflenet_goal_tradeoff.png")


def draw_resnet_all_goal_topology_summary(rows: list[dict], generated: str) -> None:
    img, draw = canvas()
    header(draw, "ResNet50 summary across PPA goals and topology", "Presentation-relevant columns only; mesh has the best PPA score in each goal setting.", generated)

    selected_count = sum(1 for row in rows if row["selected"] and row["topology"] == "mesh")
    met_rows = sum(1 for row in rows if row["target_met"])
    best_balanced = next(row for row in rows if row["ppa_goal"] == "balanced" and row["selected"])

    y = 175
    metric_card(draw, 70, y, 340, 112, "Selected topology", f"mesh {selected_count}/4", "lowest PPA score per goal", GREEN)
    metric_card(draw, 430, y, 340, 112, "Rows meeting target", f"{met_rows}/8", "target FPS = 15", BLUE)
    metric_card(draw, 790, y, 340, 112, "Balanced best", f"{num(best_balanced['achieved_fps']):.2f} FPS", f"{best_balanced['selected_chiplets']}/16 chiplets", ORANGE)
    metric_card(draw, 1150, y, 380, 112, "Removed columns", "4", "compute min, TOPS, penalty, bonus", PURPLE)

    table_x, table_y = 70, 325
    panel(draw, table_x, table_y, 1460, 485)
    columns = [
        ("Goal", 150),
        ("Topology", 115),
        ("Status", 100),
        ("Chiplets", 130),
        ("FPS", 105),
        ("Area", 125),
        ("Power", 120),
        ("PPA score", 135),
        ("Latency", 135),
        ("Bottleneck", 125),
        ("Selected", 100),
    ]
    table_rows = []
    for row in rows:
        table_rows.append([
            goal_name(row["ppa_goal"]),
            row["topology"],
            "MET" if row["target_met"] else "MISS",
            f"{row['selected_chiplets']}/16",
            f"{num(row['achieved_fps']):.2f}",
            f"{num(row['total_area_mm2']):.1f}",
            f"{num(row['total_power_w']):.1f}",
            f"{num(row['ppa_score']):.3f}",
            f"{num(row['avg_latency_ns']):.1f} ns",
            row["bottleneck_link"],
            "yes" if row["selected"] else "no",
        ])
    data_table(draw, table_x + 24, table_y + 30, columns, table_rows, row_h=45, font_size=17)

    callout(draw, 70, 835, 1460, 50, "Compact view for PPT: the crossed-out columns were removed, while topology and final PPA decision are kept.")
    img.save(OUT / "09_resnet50_all_goal_topology_summary.png")


def draw_resnet_best_partitions_by_goal(generated: str) -> None:
    img, draw = canvas()
    header(draw, "ResNet50 best workload partitions by PPA goal", "Balanced and low-latency select the same 9-chiplet partition; power and area goals reduce active chiplets.", generated)

    balanced = best_resnet_row("balanced")
    power = best_resnet_row("power")
    area = best_resnet_row("area")
    max_ops = max(
        node["ops"]
        for row in (balanced, power, area)
        for node in row["connection_graph"]["nodes"]
    )

    partition_band(
        draw,
        "Balanced / Low Latency",
        balanced,
        70,
        170,
        1460,
        210,
        max_ops,
        "Same partition for both goals",
    )
    partition_band(
        draw,
        "Low Power",
        power,
        70,
        410,
        1460,
        190,
        max_ops,
        "Uses fewer chiplets and lower power, but misses 15 FPS",
    )
    partition_band(
        draw,
        "Low Area",
        area,
        70,
        630,
        1460,
        180,
        max_ops,
        "Most compact mapping; lowest area but largest FPS miss",
    )

    footer(draw)
    img.save(OUT / "10_resnet50_best_partition_by_goal.png")


def best_resnet_row(goal: str) -> dict:
    rows = [
        row
        for row in read_json(RESULTS / "pareto_dp" / goal / "best.json")
        if row["model"] == "resnet50"
    ]
    if not rows:
        raise ValueError(f"No ResNet50 best row for goal {goal}")
    return rows[0]


def partition_band(
    draw: ImageDraw.ImageDraw,
    title: str,
    row: dict,
    x: int,
    y: int,
    w: int,
    h: int,
    max_ops: float,
    note: str,
) -> None:
    status = "MET" if row["target_met"] else "MISS"
    status_color = GREEN if row["target_met"] else RED
    text(draw, title, x, y, 29, bold=True, fill=stage_color(title.lower()))
    text(
        draw,
        f"{row['topology']} | {row['selected_chiplets']}/16 chiplets | {num(row['achieved_fps']):.2f} FPS | {status} | PPA {num(row['ppa_score']):.3f}",
        x + 380,
        y + 6,
        19,
        bold=True,
        fill=status_color if not row["target_met"] else MUTED,
    )
    text(draw, note, x + 985, y + 6, 17, fill=MUTED)

    graph = row["connection_graph"]
    traffic_by_source = {
        int(edge["source"]): float(edge["mb"])
        for edge in graph.get("traffic_edges", [])
    }
    nodes = sorted(graph["nodes"], key=lambda item: int(item["id"]))
    card_gap = 10
    card_y = y + 46
    card_h = h - 58
    card_w = min(150, int((w - card_gap * (len(nodes) - 1)) / len(nodes)))
    total_w = card_w * len(nodes) + card_gap * (len(nodes) - 1)
    start_x = x + max(0, int((w - total_w) / 2))
    for i, node in enumerate(nodes):
        compact_partition_card(
            draw,
            start_x + i * (card_w + card_gap),
            card_y,
            card_w,
            card_h,
            node,
            max_ops,
            traffic_by_source.get(int(node["id"])),
        )


def compact_partition_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    node: dict,
    max_ops: float,
    out_mb: float | None,
) -> None:
    color = stage_color(str(node["stage"]))
    draw.rounded_rectangle([x, y, x + w, y + h], radius=7, fill="#fbfcfd", outline=LINE, width=1)
    draw.rounded_rectangle([x, y, x + w, y + 6], radius=3, fill=color)
    text(draw, f"C{int(node['id']) + 1}", x + 9, y + 15, 18, bold=True)
    wrapped(draw, str(node["stage"]), x + 9, y + 42, w - 18, 15)
    out_label = "-" if out_mb is None else f"{out_mb:.2f} MB"
    text(draw, f"{num(node['ops']) / 1e9:.2f} GOP", x + 9, y + h - 43, 13, fill=MUTED)
    text(draw, f"out {out_label}", x + 9, y + h - 25, 12, fill=MUTED)
    bar(draw, x + 9, y + h - 10, w - 18, 5, num(node["ops"]), max_ops, color)


def draw_partition(row: dict, generated: str) -> None:
    img, draw = canvas()
    header(draw, "ResNet50 mapping reveals the compute bottleneck", "The balanced design spreads heavier ResNet stages across 9 active chiplets while leaving 7 chiplets unused.", generated)
    nodes = row["connection_graph"]["nodes"]
    max_ops = max(node["ops"] for node in nodes)

    start_x, start_y = 70, 190
    chip_w, chip_h, gap = 152, 210, 12
    for i, node in enumerate(nodes):
        x = start_x + i * (chip_w + gap)
        chiplet(draw, x, start_y, chip_w, chip_h, node, max_ops)
        if i < len(nodes) - 1:
            arrow(draw, x + chip_w + 1, start_y + chip_h / 2, x + chip_w + gap - 3, start_y + chip_h / 2, MUTED)

    y = 455
    metric_card(draw, 70, y, 455, 120, "Workload traffic", f"{num(row['total_traffic_mb_per_inference']):.2f} MB", "per inference", RED)
    metric_card(draw, 545, y, 455, 120, "Bottleneck link", row["bottleneck_link"], f"{num(row['aggregate_throughput_bits_per_cycle']):.1f} bits/cycle", ORANGE)
    metric_card(draw, 1020, y, 510, 120, "Compute vs network", f"{num(row['compute_limited_fps']):.2f} / {num(row['network_limited_fps']):.0f}", "compute FPS / network FPS", BLUE)

    panel(draw, 70, 620, 1460, 170)
    text(draw, "Workload partition", 94, 642, 28, bold=True)
    wrapped(draw, row["workload_plan"], 94, 692, 1410, 28, fill=INK)

    footer(draw)
    img.save(OUT / "03_resnet_partition_mapping.png")


def draw_topology(mesh: dict, tree: dict, generated: str) -> None:
    img, draw = canvas()
    header(draw, "Mesh keeps ResNet50 latency lower than tree", "Both balanced topologies meet the target at 9 chiplets, but mesh has lower reported communication latency.", generated)

    left = (70, 175, 705, 540)
    right = (825, 175, 705, 540)
    topology_panel(draw, left, mesh)
    topology_panel(draw, right, tree)
    callout(draw, 70, 750, 1460, 78, "Use mesh as the main result; introduce tree only as topology comparison: same chiplet count and FPS, but higher latency.")

    footer(draw)
    img.save(OUT / "04_resnet_topology_traffic.png")


def draw_resnet_topology_metric_comparison(mesh: dict, tree: dict, generated: str) -> None:
    img, draw = canvas()
    header(draw, "ResNet50 mesh vs tree: same FPS, lower mesh latency", "Both topologies meet the 15 FPS target, but mesh is selected because latency and PPA score are better.", generated)

    latency_delta = num(tree["avg_latency_ns"]) - num(mesh["avg_latency_ns"])
    power_delta = num(mesh["total_power_w"]) - num(tree["total_power_w"])
    ppa_delta = num(tree["ppa_score"]) - num(mesh["ppa_score"])
    throughput_drop = (
        (num(mesh["aggregate_throughput_bits_per_cycle"]) - num(tree["aggregate_throughput_bits_per_cycle"]))
        / num(mesh["aggregate_throughput_bits_per_cycle"])
        * 100
    )

    y = 175
    metric_card(draw, 70, y, 340, 116, "Selected topology", "mesh", "lower balanced PPA score", GREEN)
    metric_card(draw, 430, y, 340, 116, "Tree latency gap", f"+{latency_delta:.1f} ns", "compared with mesh", RED)
    metric_card(draw, 790, y, 340, 116, "Tree power saving", f"{power_delta:.1f} W", "fewer topology links", ORANGE)
    metric_card(draw, 1150, y, 380, 116, "Tree throughput drop", f"{throughput_drop:.1f}%", "aggregate bits/cycle", BLUE)

    panel(draw, 70, 330, 1460, 320)
    columns = [
        ("Topology", 170),
        ("Status", 120),
        ("Chiplets", 135),
        ("Links", 110),
        ("FPS", 145),
        ("Latency", 170),
        ("Power", 150),
        ("Throughput", 180),
        ("PPA", 120),
        ("Selected", 130),
    ]
    rows = [
        [
            "mesh",
            "MET",
            f"{mesh['selected_chiplets']}/16",
            str(mesh["link_count"]),
            f"{num(mesh['achieved_fps']):.2f}",
            f"{num(mesh['avg_latency_ns']):.1f} ns",
            f"{num(mesh['total_power_w']):.1f} W",
            f"{num(mesh['aggregate_throughput_bits_per_cycle']):.0f}",
            f"{num(mesh['ppa_score']):.3f}",
            "yes",
        ],
        [
            "tree",
            "MET",
            f"{tree['selected_chiplets']}/16",
            str(tree["link_count"]),
            f"{num(tree['achieved_fps']):.2f}",
            f"{num(tree['avg_latency_ns']):.1f} ns",
            f"{num(tree['total_power_w']):.1f} W",
            f"{num(tree['aggregate_throughput_bits_per_cycle']):.0f}",
            f"{num(tree['ppa_score']):.3f}",
            "no",
        ],
    ]
    data_table(draw, 95, 365, columns, rows, row_h=62, font_size=19)

    panel(draw, 70, 690, 460, 120)
    text(draw, "Main comparison", 92, 712, 26, bold=True, fill=GREEN)
    wrapped(draw, f"Mesh keeps the same {num(mesh['achieved_fps']):.2f} FPS with {latency_delta:.1f} ns lower latency than tree.", 92, 754, 410, 22, bold=True)

    panel(draw, 570, 690, 460, 120)
    text(draw, "Why tree is close", 592, 712, 26, bold=True, fill=ORANGE)
    wrapped(draw, f"Tree uses {mesh['link_count'] - tree['link_count']} fewer links and saves {power_delta:.1f} W, but routing is less direct.", 592, 754, 410, 22, bold=True)

    panel(draw, 1070, 690, 460, 120)
    text(draw, "PPA decision", 1092, 712, 26, bold=True, fill=BLUE)
    wrapped(draw, f"Tree PPA is higher by {ppa_delta:.3f}, so mesh is the selected balanced result.", 1092, 754, 410, 22, bold=True)

    footer(draw)
    img.save(OUT / "07_resnet50_topology_metric_comparison.png")


def draw_resnet_topology_connection_graphs(mesh: dict, tree: dict, generated: str) -> None:
    img, draw = canvas()
    header(draw, "ResNet50 connection graphs: mesh vs tree", "Gray lines are physical topology links; red dashed lines are workload traffic routes between chiplet partitions.", generated)

    left = (70, 175, 705, 600)
    right = (825, 175, 705, 600)
    topology_panel(draw, left, mesh)
    topology_panel(draw, right, tree)
    callout(draw, 70, 795, 1460, 50, "Mesh routes traffic more directly; tree saves links but increases path latency.")

    footer(draw)
    img.save(OUT / "08_resnet50_topology_connection_graphs.png")


def draw_search_check(comparison: list[dict], generated: str) -> None:
    img, draw = canvas()
    header(draw, "Pareto-DP preserves the reported best designs", "DP matches brute-force on selected metrics across the latest goal comparison.", generated)

    rows = []
    for goal in ("balanced", "latency", "power", "area"):
        for model in ("resnet50", "shufflenet_v2_x1_0"):
            brute = next(r for r in comparison if r["ppa_goal"] == goal and r["search"] == "brute-force" and r["model"] == model)
            dp = next(r for r in comparison if r["ppa_goal"] == goal and r["search"] == "pareto-dp" and r["model"] == model)
            match = same_metrics(brute, dp)
            rows.append([goal_name(goal), model_name(model), compact_result(brute), compact_result(dp), "same" if match else "different"])

    matches = sum(1 for row in rows if row[-1] == "same")
    y = 175
    metric_card(draw, 70, y, 340, 112, "Checks passed", f"{matches}/{len(rows)}", "same selected metrics", GREEN)
    metric_card(draw, 430, y, 340, 112, "Models", "2", "ResNet50, ShuffleNetV2", BLUE)
    metric_card(draw, 790, y, 340, 112, "Goals", "4", "balanced, latency, power, area", PURPLE)
    metric_card(draw, 1150, y, 380, 112, "Use in talk", "Validation", "DP does not change the result", ORANGE)

    panel(draw, 70, 325, 1460, 480)
    columns = [("Goal", 160), ("Model", 210), ("Brute-force", 390), ("Pareto-DP", 390), ("Match", 130)]
    data_table(draw, 95, 350, columns, rows, row_h=47, font_size=18)

    footer(draw)
    img.save(OUT / "05_search_method_check.png")


def topology_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], row: dict) -> None:
    x, y, w, h = box
    panel(draw, x, y, w, h)
    title = f"{row['topology'].title()}: {num(row['avg_latency_ns']):.1f} ns, {num(row['total_power_w']):.1f} W"
    text(draw, title, x + 22, y + 20, 28, bold=True)
    text(draw, f"{row['selected_chiplets']} chiplets, {row['link_count']} links, traffic {num(row['total_traffic_mb_per_inference']):.2f} MB/inference", x + 22, y + 58, 18, fill=MUTED)
    gx, gy, gw, gh = x + 35, y + 105, w - 70, h - 165
    graph = row["connection_graph"]
    positions = tree_positions(graph["nodes"], graph["physical_links"], gx, gy, gw, gh) if row["topology"] == "tree" else scaled_positions(graph["nodes"], gx, gy, gw, gh)
    for link in graph["physical_links"]:
        a = positions[int(link["source"])]
        b = positions[int(link["target"])]
        draw.line([a, b], fill="#98a6b5", width=4)
    max_mb = max([edge["mb"] for edge in graph["traffic_edges"]] + [1])
    for edge in graph["traffic_edges"]:
        a = positions[int(edge["source"])]
        b = positions[int(edge["target"])]
        width = int(3 + 5 * edge["mb"] / max_mb)
        dashed_arrow(draw, a, b, RED, width)
    for node in graph["nodes"]:
        px, py = positions[int(node["id"])]
        draw.rounded_rectangle([px - 27, py - 27, px + 27, py + 27], radius=7, fill="#e8f2ff", outline=BLUE, width=3)
        centered(draw, f"C{int(node['id']) + 1}", px, py - 1, 18, bold=True)
        centered(draw, short(str(node["stage"]), 15), px, py + 47, 14, fill=MUTED)
    text(draw, "gray: topology links   red: workload traffic", x + 22, y + h - 38, 17, fill=MUTED)


def chiplet(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, node: dict, max_ops: float) -> None:
    color = stage_color(str(node["stage"]))
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill="#fbfcfd", outline=LINE, width=1)
    draw.rounded_rectangle([x, y, x + w, y + 9], radius=4, fill=color)
    text(draw, f"C{int(node['id']) + 1}", x + 12, y + 22, 22, bold=True)
    wrapped(draw, str(node["stage"]), x + 12, y + 62, w - 24, 19)
    text(draw, f"{num(node['ops']) / 1e9:.2f} GOP", x + 12, y + 150, 16, fill=MUTED)
    bar(draw, x + 12, y + 180, w - 24, 12, num(node["ops"]), max_ops, color)


def data_table(draw: ImageDraw.ImageDraw, x: int, y: int, columns: list[tuple[str, int]], rows: list[list[str]], row_h: int, font_size: int = 19) -> None:
    total_w = sum(width for _, width in columns)
    draw.rectangle([x, y, x + total_w, y + row_h], fill=HEADER)
    cx = x
    for title, width in columns:
        text(draw, title, cx + 10, y + 13, font_size, bold=True)
        cx += width
    cy = y + row_h
    for row in rows:
        draw.line([x, cy, x + total_w, cy], fill=LINE, width=1)
        cx = x
        for (col_title, width), value in zip(columns, row):
            fill = GREEN if value in {"MET", "same", "yes"} else RED if value in {"MISS", "different", "no"} else INK
            display = short(str(value), max(8, int(width / (font_size * 0.55))))
            text(draw, display, cx + 10, cy + 13, font_size, bold=value in {"MET", "MISS", "same", "different", "yes", "no"}, fill=fill)
            cx += width
        cy += row_h
    draw.line([x, cy, x + total_w, cy], fill=LINE, width=1)


def metric_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, label: str, value: str, note: str, color: str) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=SOFT, outline=LINE, width=1)
    draw.rectangle([x, y, x + 7, y + h], fill=color)
    text(draw, label, x + 20, y + 16, 18, fill=MUTED)
    text(draw, value, x + 20, y + 45, 32, bold=True)
    wrapped(draw, note, x + 20, y + 86, w - 32, 16, fill=MUTED)


def panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=WHITE, outline=LINE, width=1)


def callout(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, body: str) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill="#eff8f4", outline="#d7ebe2", width=1)
    draw.rectangle([x, y, x + 7, y + h], fill=GREEN)
    wrapped(draw, body, x + 22, y + 17, w - 44, 24, bold=True)


def header(draw: ImageDraw.ImageDraw, title: str, subtitle: str, generated: str) -> None:
    text(draw, title, 70, 48, 46, bold=True)
    wrapped(draw, subtitle, 70, 106, 1160, 24, fill=MUTED)
    text(draw, "latest report", 1335, 57, 17, fill=MUTED)
    text(draw, generated, 1335, 82, 17, fill=MUTED)
    draw.line([70, 145, 1530, 145], fill=LINE, width=2)


def footer(draw: ImageDraw.ImageDraw) -> None:
    text(draw, "Source: simplified_rapidchiplet/results/latest/report.html and search_comparison_with_bonus.csv", 70, 858, 15, fill=MUTED)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    return img, ImageDraw.Draw(img)


def bar(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, value: float, maximum: float, color: str) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill="#e8edf3")
    pct = max(0.02, min(1.0, value / maximum if maximum else 0.0))
    draw.rounded_rectangle([x, y, x + w * pct, y + h], radius=h / 2, fill=color)


def arrow(draw: ImageDraw.ImageDraw, x1: float, y1: float, x2: float, y2: float, fill: str) -> None:
    draw.line([x1, y1, x2, y2], fill=fill, width=2)
    draw.polygon([(x2, y2), (x2 - 7, y2 - 5), (x2 - 7, y2 + 5)], fill=fill)


def dashed_arrow(draw: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float], fill: str, width: int) -> None:
    x1, y1 = a
    x2, y2 = b
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return
    ux, uy = dx / dist, dy / dist
    dash, gap = 18, 11
    t = 0
    while t < dist - 30:
        s = t
        e = min(t + dash, dist - 30)
        draw.line([x1 + ux * s, y1 + uy * s, x1 + ux * e, y1 + uy * e], fill=fill, width=width)
        t += dash + gap
    arrow(draw, x2 - ux * 24, y2 - uy * 24, x2 - ux * 8, y2 - uy * 8, fill)


def scaled_positions(nodes: list[dict], x: int, y: int, w: int, h: int) -> dict[int, tuple[float, float]]:
    xs = [num(node["x"]) for node in nodes]
    ys = [num(node["y"]) for node in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    margin = 55
    positions = {}
    for node in nodes:
        px = x + w / 2 if max_x == min_x else x + margin + (num(node["x"]) - min_x) / (max_x - min_x) * (w - margin * 2)
        py = y + h / 2 if max_y == min_y else y + margin + (num(node["y"]) - min_y) / (max_y - min_y) * (h - margin * 2)
        positions[int(node["id"])] = (px, py)
    return positions


def tree_positions(nodes: list[dict], links: list[dict], x: int, y: int, w: int, h: int) -> dict[int, tuple[float, float]]:
    ids = sorted(int(node["id"]) for node in nodes)
    root = ids[0]
    adj = {node_id: [] for node_id in ids}
    for link in links:
        s, t = int(link["source"]), int(link["target"])
        if s in adj and t in adj:
            adj[s].append(t)
            adj[t].append(s)
    for node_id in ids:
        adj[node_id].sort()
    children = {node_id: [] for node_id in ids}
    depth = {root: 0}
    parent = {root: None}
    queue = [root]
    for node_id in queue:
        for nxt in adj[node_id]:
            if nxt in parent:
                continue
            parent[nxt] = node_id
            depth[nxt] = depth[node_id] + 1
            children[node_id].append(nxt)
            queue.append(nxt)
    slots = {}
    next_slot = 0

    def assign(node_id: int) -> float:
        nonlocal next_slot
        if not children[node_id]:
            slots[node_id] = float(next_slot)
            next_slot += 1
            return slots[node_id]
        vals = [assign(child) for child in children[node_id]]
        slots[node_id] = sum(vals) / len(vals)
        return slots[node_id]

    assign(root)
    max_slot = max(slots.values()) if slots else 1
    max_depth = max(depth.values()) if depth else 1
    margin = 55
    positions = {}
    for node_id in ids:
        px = x + w / 2 if max_slot == 0 else x + margin + slots[node_id] / max_slot * (w - margin * 2)
        py = y + h / 2 if max_depth == 0 else y + margin + depth[node_id] / max_depth * (h - margin * 2)
        positions[node_id] = (px, py)
    return positions


def same_metrics(left: dict, right: dict) -> bool:
    keys = ["topology", "status", "used_chiplets", "achieved_fps", "area_mm2", "power_w", "latency_ns", "ppa_score"]
    return all(left[key] == right[key] for key in keys)


def compact_result(row: dict) -> str:
    return f"{row['status']}, {row['used_chiplets']} chiplets, {num(row['achieved_fps']):.2f} FPS"


def wrapped(draw: ImageDraw.ImageDraw, value: str, x: int, y: int, max_w: int, size: int, *, bold: bool = False, fill: str = INK) -> None:
    font = font_for(size, bold=bold)
    words = value.split()
    lines = []
    line = ""
    for word in words:
        test = word if not line else f"{line} {word}"
        if text_width(draw, test, font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    for i, line in enumerate(lines[:4]):
        draw.text((x, y + i * int(size * 1.25)), line, font=font, fill=fill)


def centered(draw: ImageDraw.ImageDraw, value: str, x: float, y: float, size: int, *, bold: bool = False, fill: str = INK) -> None:
    font = font_for(size, bold=bold)
    bbox = draw.textbbox((0, 0), value, font=font)
    draw.text((x - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2), value, font=font, fill=fill)


def text(draw: ImageDraw.ImageDraw, value: str, x: int, y: int, size: int, *, bold: bool = False, fill: str = INK) -> None:
    draw.text((x, y), value, font=font_for(size, bold=bold), fill=fill)


def text_width(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), value, font=font)
    return bbox[2] - bbox[0]


def font_for(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def read_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def timestamp(seconds: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")


def num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.inf


def short(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."


def goal_name(goal: str) -> str:
    return {
        "balanced": "Balanced",
        "latency": "Low latency",
        "power": "Low power",
        "area": "Low area",
    }.get(goal, goal)


def model_name(model: str) -> str:
    return {
        "resnet50": "ResNet50",
        "shufflenet_v2_x1_0": "ShuffleNetV2",
    }.get(model, model)


def stage_color(stage: str) -> str:
    if stage.startswith("conv"):
        return BLUE
    if stage.startswith("layer1"):
        return GREEN
    if stage.startswith("layer2"):
        return ORANGE
    if stage.startswith("layer3"):
        return PURPLE
    if stage.startswith("layer4"):
        return RED
    return TEAL


if __name__ == "__main__":
    main()
