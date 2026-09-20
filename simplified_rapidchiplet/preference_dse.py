"""Run fine-grained block-level, preference-aware Chiplet DSE."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.model import load_models, select_models
from simple_rapidchiplet.preference_dse import (
    make_preference_profile,
    q_learning_search,
    write_search_outputs,
)


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Fine-grained block graph + preference-aware Q-learning DSE."
    )
    parser.add_argument("--config", default=str(root / "configs" / "defaults.json"))
    parser.add_argument("--models-file", default=str(root / "configs" / "models.json"))
    parser.add_argument("--models", nargs="+", default=["resnet50"],
                        help="Validated models: resnet50, resnet18, mobilenet_v2, squeezenet1_1.")
    parser.add_argument(
        "--preference",
        choices=["balanced", "latency", "area", "power"],
        default="balanced",
    )
    parser.add_argument("--max-latency-ns", type=float, default=None)
    parser.add_argument("--max-area-mm2", type=float, default=None)
    parser.add_argument("--max-power-w", type=float, default=None)
    for metric in ("latency", "area", "power"):
        parser.add_argument("--strict-" + metric, action=argparse.BooleanOptionalAction,
                            default=None, help="Enforce this limit; --no-strict-* enables bonus/penalty")
    parser.add_argument(
        "--block-split",
        type=int,
        default=1,
        help=(
            "Legacy fallback only: split stage-only configs into inferred blocks. "
            "Explicit semantic blocks are never split."
        ),
    )
    parser.add_argument("--budget", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--episodes", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--out", default=str(root / "results" / "preference_dse"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    models = select_models(load_models(args.models_file), args.models)
    profile = make_preference_profile(
        args.preference,
        max_latency_ns=args.max_latency_ns if args.max_latency_ns is not None else cfg.ppa.get("max_latency_ns", float("inf")),
        max_area_mm2=args.max_area_mm2 if args.max_area_mm2 is not None else cfg.ppa.get("max_area_mm2", float("inf")),
        max_power_w=args.max_power_w if args.max_power_w is not None else cfg.ppa.get("max_power_w", float("inf")),
        **{"strict_" + name: getattr(args, "strict_" + name) if getattr(args, "strict_" + name) is not None
           else cfg.strict_constraints.get(name, True) for name in ("latency", "area", "power")},
        cfg=cfg,
    )

    results = []
    for model_index, model in enumerate(models):
        result = q_learning_search(
            model,
            cfg,
            profile,
            block_split=args.block_split,
            evaluation_budget=args.budget if args.budget is not None else int(cfg.search.get("evaluation_budget", 128)),
            seed=(args.seed if args.seed is not None else int(cfg.search.get("seed", 1))) + model_index,
            max_episodes=args.episodes if args.episodes is not None else int(cfg.search.get("max_episodes", 3000)),
            **{k: cfg.search[k] for k in ("learning_rate", "epsilon_start", "epsilon_end", "epsilon_decay") if k in cfg.search},
        )
        results.append(result)
        candidate = result.best_candidate
        if candidate is None:
            print(f"{model.name}: no admissible design in {result.unique_evaluations} evaluations; stop={result.stopping_reason}")
            continue
        print(
            f"{model.name}: preference={profile.name} "
            f"blocks={len(candidate.block_graph.get('nodes', []))} "
            f"evaluations={result.unique_evaluations} "
            f"reward={result.best_reward:.6f} "
            f"feasible={result.best_breakdown.feasible} "
            f"chiplets={candidate.selected_chiplets} "
            f"fps={candidate.achieved_fps:.3f} "
            f"latency={candidate.avg_latency_ns:.3f}ns "
            f"area={candidate.total_area_mm2:.3f}mm2 "
            f"power={candidate.total_power_w:.3f}W"
        )
        print("  mapping: " + " | ".join(
            f"blocks[{start}:{end}]={parts}x{strategy}"
            for (start,end,parts), strategy in zip(result.best_state.groups, result.best_state.mapping_strategies)))
        print(f"  stop={result.stopping_reason}; policy_matches_best={result.policy_rollout['matches_best_reward']}")

    written = write_search_outputs(args.out, results)
    manifest = json.loads(written["manifest"].read_text(encoding="utf-8"))
    manifest["configuration"] = asdict(cfg)
    manifest["input_sha256"] = {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                for p in (args.config, args.models_file)}
    manifest["source_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted((root / "simple_rapidchiplet").glob("*.py"))}
    written["manifest"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for path in written.values():
        print(f"Wrote {path.resolve()}")


if __name__ == "__main__":
    main()
