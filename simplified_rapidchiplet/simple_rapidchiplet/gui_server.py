"""Loopback-only GUI API. Uses the same search/evaluator as the CLI."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import mimetypes
import secrets
import threading
import time
import uuid
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .config import load_config
from .model import load_models
from .preference_dse import make_preference_profile, q_learning_search, _json_safe
from .routing import shortest_paths_for_pairs
from .topology import Topology, Edge
from .placement_svg import render_placement_svg

CATALOG = {
    "resnet50": ("ResNet-50", "Bottleneck 殘差 · single / OC / IC"),
    "resnet18": ("ResNet-18", "BasicBlock 殘差 · single / OC / IC"),
    "mobilenet_v2": ("MobileNetV2", "Depthwise + pointwise · single / OC；IC 尚未開放"),
    "squeezenet1_1": ("SqueezeNet 1.1", "Fire 分支與 concat 保留於單顆 chiplet，可做 block 間 pipeline"),
}


def validate_request(data, models):
    if not isinstance(data, dict) or set(data) != {"models", "preference", "limits", "strict", "budget", "seed"}:
        raise ValueError("請提供模型、偏好、三項 PPA 限制、嚴格選項、budget 與 seed")
    selected = data["models"]
    if not isinstance(selected, list) or not 1 <= len(selected) <= len(CATALOG) or any(
        not isinstance(name, str) or name not in CATALOG or name not in models for name in selected
    ) or len(set(selected)) != len(selected):
        raise ValueError("請選擇至少一個已校驗模型，且不可重複")
    if data["preference"] not in ("balanced", "latency", "area", "power"):
        raise ValueError("無效的 preference")
    if not isinstance(data["limits"], dict) or set(data["limits"]) != {"power_w", "area_mm2", "latency_ms"}:
        raise ValueError("PPA 單位必須為 W、mm²、ms")
    for value in data["limits"].values():
        if type(value) not in (int, float) or not math.isfinite(value) or not 1e-9 <= value <= 1e12:
            raise ValueError("PPA 限制必須為有限正數（1e-9 至 1e12）")
    if not isinstance(data["strict"], dict) or set(data["strict"]) != {"power", "area", "latency"} or any(
        type(value) is not bool for value in data["strict"].values()
    ):
        raise ValueError("每項嚴格選項必須是 true 或 false")
    if type(data["budget"]) is not int or not 1 <= data["budget"] <= 1024:
        raise ValueError("評估預算必須為 1 至 1024 的整數")
    if type(data["seed"]) is not int or not 0 <= data["seed"] <= 2**32 - 1:
        raise ValueError("seed 必須為 0 至 4294967295 的整數")
    return copy.deepcopy(data)


def attach_routes(result):
    """Route the actual result's flows on its actual physical links (same SPLIF)."""
    candidate = result.get("best_candidate")
    if not candidate:
        return result
    graph = candidate["connection_graph"]
    topology = Topology(candidate["topology"], len(graph["nodes"]),
        {n["id"]: (n["x"], n["y"]) for n in graph["nodes"]},
        tuple(Edge(e["source"], e["target"], e["length_mm"]) for e in graph["physical_links"]))
    pairs = {(e["source"], e["target"]) for e in graph["traffic_edges"]}
    routes = shortest_paths_for_pairs(topology, pairs)
    graph["routed_traffic"] = [dict(e, path=routes[(e["source"], e["target"])]) for e in graph["traffic_edges"]]
    for event in candidate["communication_events"]:
        for flow in event["flows"]:
            flow["path"] = routes[(flow["source"], flow["target"])]
    graph["coordinate_unit"] = "mm"
    graph["routing"] = "shortest path, lowest-ID tie break (same as evaluator)"
    return result


def result_view(full):
    view = {key: value for key, value in full.items() if key not in ("q_table", "history", "policy_rollout")}
    view["policy_rollout"] = {k: v for k, v in full["policy_rollout"].items() if k not in ("state", "candidate")}
    # Keep distinct evaluations only, including the final point.
    view["learning_curve"] = [{k: h[k] for k in ("evaluations", "reward", "best_reward", "admissible")}
                              for h in full["history"] if h["is_new"]]
    return view


class Application:
    def __init__(self, root, config_path=None):
        self.root = Path(root).resolve()
        self.config_path = Path(config_path or self.root / "configs/defaults.json").resolve()
        self.cfg = load_config(self.config_path)
        self.models = load_models(self.root / "configs/models.json")
        raw = json.loads((self.root / "configs/models.json").read_text(encoding="utf-8"))
        self.metadata = {m["name"]: m for m in raw["models"]}
        self.lock = threading.RLock()
        self.jobs = {}
        self.active_job = None
        self.token = secrets.token_urlsafe(32)

    def configuration(self):
        available = []
        for name, (label, description) in CATALOG.items():
            meta = self.metadata[name]
            calibration = meta.get("calibration", {})
            if not calibration.get("forward_checked"):
                continue
            m = self.models[name]
            available.append(dict(name=name, label=label, description=description,
                parameters=round(m.params_m * 1e6), macs_g=m.macs_g,
                fp32_weights_mib=sum(b.weight_mb for b in m.blocks), blocks=len(m.blocks), calibration=calibration))
        return dict(token=self.token, models=available, hardware=asdict(self.cfg),
                    limits=dict(power_w=self.cfg.ppa.get("max_power_w", 16),
                                area_mm2=self.cfg.ppa.get("max_area_mm2", 800),
                                latency_ms=self.cfg.ppa.get("max_latency_ns", 5e8) / 1e6),
                    strict={name: self.cfg.strict_constraints.get(name, True) for name in ("power", "area", "latency")},
                    preferences={name: make_preference_profile(name).weights for name in ("balanced", "power", "area", "latency")},
                    budget=int(self.cfg.search.get("evaluation_budget", 128)), seed=int(self.cfg.search.get("seed", 1)))

    def start(self, data):
        data = validate_request(data, self.models)
        if any(not self.metadata[m].get("calibration", {}).get("forward_checked") for m in data["models"]):
            raise ValueError("模型尚未完成 forward 校驗")
        with self.lock:
            if self.active_job is not None:
                raise RuntimeError("已有搜尋正在執行，請等待完成或取消")
            if len(self.jobs) >= 100:
                oldest = next(iter(self.jobs))
                self.jobs.pop(oldest)
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = dict(id=job_id, status="running", request=data, progress={},
                results=[], errors=[], created_at=time.time(), cancel=False, download_ready=False)
            self.active_job = job_id
            threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
            return self.snapshot(job_id)

    def snapshot(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            return _json_safe(copy.deepcopy(self.jobs[job_id]))

    def cancel(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            if self.jobs[job_id]["status"] == "running":
                self.jobs[job_id]["cancel"] = True
            return self.snapshot(job_id)

    def _run(self, job_id):
        job = self.jobs[job_id]
        data, full_results = job["request"], []
        directory = self.root / "results/gui" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        limits = data["limits"]
        profile = make_preference_profile(data["preference"], cfg=self.cfg,
            max_power_w=limits["power_w"], max_area_mm2=limits["area_mm2"], max_latency_ns=limits["latency_ms"] * 1e6,
            **{"strict_" + metric: value for metric, value in data["strict"].items()})

        def cancelled():
            return job["cancel"]

        def progress(update):
            with self.lock:
                job["progress"] = update

        try:
            for name in data["models"]:
                if cancelled():
                    raise InterruptedError("Search cancelled")
                progress(dict(model=name, evaluations=0, budget=data["budget"], episodes=0, phase="preparing"))
                try:
                    outcome = q_learning_search(self.models[name], self.cfg, profile,
                        evaluation_budget=data["budget"], seed=data["seed"],
                        max_episodes=int(self.cfg.search.get("max_episodes", 3000)),
                        progress_callback=progress, should_cancel=cancelled,
                        **{k: self.cfg.search[k] for k in ("learning_rate", "epsilon_start", "epsilon_end", "epsilon_decay") if k in self.cfg.search})
                    full = attach_routes(outcome.to_dict())
                    full["model_metadata"] = next(m for m in self.configuration()["models"] if m["name"] == name)
                    (directory / (name + ".json")).write_text(json.dumps(_json_safe(full), ensure_ascii=False, indent=2), encoding="utf-8")
                    full_results.append(full)
                    with self.lock:
                        job["results"].append(result_view(full))
                except InterruptedError:
                    raise
                except Exception as exc:
                    with self.lock:
                        job["errors"].append(dict(model=name, message=str(exc)))
            final_status = "completed_with_errors" if job["errors"] else "completed"
        except InterruptedError:
            final_status = "cancelled"
        except Exception as exc:
            job["errors"].append(dict(model="", message=str(exc)))
            final_status = "failed"
        finally:
            try:
                paths = [self.config_path, self.root / "configs/models.json", *sorted((self.root / "simple_rapidchiplet").glob("*.py"))]
                export = dict(request=data, status=locals().get("final_status", "failed"), results=full_results,
                    errors=job["errors"], effective_configuration=asdict(self.cfg),
                    sha256={str(p.relative_to(self.root)) if p.is_relative_to(self.root) else str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
                (directory / "results.json").write_text(json.dumps(_json_safe(export), ensure_ascii=False, indent=2), encoding="utf-8")
                with (directory / "summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["model", "status", "all_limits_met", "reward", "chiplets", "power_w", "area_mm2", "latency_ms", "fps", "bonus", "penalty", "power_fixed_utilization_w", "energy_per_inference_j"])
                    for r in full_results:
                        c, b = r["best_candidate"], r["best_breakdown"]
                        writer.writerow([r["model"], r["status"], b["feasible"] if b else False, r["best_reward"],
                            c["selected_chiplets"] if c else "", c["total_power_w"] if c else "", c["total_area_mm2"] if c else "",
                            c["avg_latency_ns"] / 1e6 if c else "", c["achieved_fps"] if c else "", b["bonus"] if b else "", b["penalty"] if b else "",
                            c["power_fixed_utilization_w"] if c else "", c["energy_per_inference_j"] if c else ""])
                job["download_ready"] = True
            except Exception as exc:
                job["errors"].append(dict(model="export", message=str(exc)))
                final_status = "failed"
            with self.lock:
                job["status"] = locals().get("final_status", "failed")
                self.active_job = None


def make_server(app, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, code, data, content_type="application/json; charset=utf-8", download=None):
            if not isinstance(data, bytes):
                data = json.dumps(_json_safe(data), ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def trusted_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

        def do_GET(self):
            if not self.trusted_host():
                return self.send(403, {"error": "Localhost only"})
            path = urlsplit(self.path).path
            if path == "/api/config":
                return self.send(200, app.configuration())
            if path.startswith("/api/jobs/"):
                parts = path.strip("/").split("/")
                try:
                    snap = app.snapshot(parts[2])
                    if len(parts) == 3:
                        return self.send(200, snap)
                    if len(parts) == 4 and parts[3] == "placement.svg":
                        query = parse_qs(urlsplit(self.path).query)
                        selected = next((r for r in snap["results"] if r["model"] == query.get("model", [""])[0]), None)
                        if selected is None or selected["best_candidate"] is None:
                            return self.send(404, {"error": "No admissible placement to export"})
                        try:
                            svg = render_placement_svg(selected, query.get("event", ["physical"])[0])
                        except ValueError as exc:
                            return self.send(400, {"error": str(exc)})
                        return self.send(200, svg, "image/svg+xml", selected["model"] + "-placement.svg")
                    if len(parts) == 4 and parts[3] in ("results.json", "summary.csv") and snap["download_ready"]:
                        file = app.root / "results/gui" / snap["id"] / parts[3]
                        return self.send(200, file.read_bytes(), "text/csv; charset=utf-8" if file.suffix == ".csv" else "application/json; charset=utf-8", file.name)
                except KeyError:
                    pass
                return self.send(404, {"error": "找不到此工作或匯出檔尚未完成"})
            static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path in static:
                file = app.root / "gui" / static[path]
                return self.send(200, file.read_bytes(), (mimetypes.guess_type(file)[0] or "text/plain") + "; charset=utf-8")
            self.send(404, {"error": "Not found"})

        def do_POST(self):
            # Drain a bounded request body before a rejection. Otherwise Windows
            # may reset the connection on close and discard the 403 response.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("Invalid request length")
                body = self.rfile.read(length)
            except ValueError as exc:
                return self.send(400, {"error": str(exc)})
            if not self.trusted_host() or not secrets.compare_digest(self.headers.get("X-DSE-Token", ""), app.token):
                return self.send(403, {"error": "請從本機 GUI 操作"})
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers["Host"]:
                return self.send(403, {"error": "Invalid origin"})
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("JSON required")
                data = json.loads(body)
                path = urlsplit(self.path).path
                if path == "/api/jobs":
                    return self.send(202, app.start(data))
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
                    return self.send(200, app.cancel(parts[2]))
                return self.send(404, {"error": "Not found"})
            except (ValueError, TypeError) as exc:
                self.send(400, {"error": str(exc)})
            except KeyError:
                self.send(404, {"error": "找不到此工作"})
            except RuntimeError as exc:
                self.send(409, {"error": str(exc)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
