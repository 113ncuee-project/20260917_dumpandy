"""Reproducible bounded Q-policy and matched-budget random-search comparison.

Run from the project root. The 256-bit case is an explicit sensitivity case;
it never overwrites the user's 0.3-bit default hardware configuration.
"""
import json
import random
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.model import load_models
from simple_rapidchiplet.preference_dse import (
    DesignState, EvaluationOracle, make_preference_profile, q_learning_search,
    random_complete_state, score_result, _json_safe,
)


def validate():
    cfg = load_config(ROOT / 'configs/defaults.json')
    cfg = replace(cfg, rapidchiplet=replace(cfg.rapidchiplet, backend='official'))
    model = load_models(ROOT / 'configs/models.json')['resnet50']
    records = []
    cases = [(0.3, 'balanced', seed) for seed in (20260919, 20260920, 20260921)]
    cases += [(256., pref, 20260919) for pref in ('balanced', 'latency', 'area', 'power')]
    for bandwidth, preference, seed in cases:
        effective = replace(cfg, network=replace(cfg.network, link_bandwidth_bits_per_cycle=bandwidth))
        profile = make_preference_profile(preference, cfg=effective, **effective.ppa)
        result = q_learning_search(model, effective, profile, evaluation_budget=128,
                                   max_episodes=3000, seed=seed)
        oracle = EvaluationOracle(model, effective, profile, effective.max_chiplets)
        rng = random.Random(seed)
        # Same deterministic first candidate for both methods, then random actions.
        first = result.history[0]
        state = DesignState(preference, len(model.blocks), sum(g[2] for g in first['groups']),
                            first['groups'], mapping_strategies=first['mapping_strategies'])
        first_random = score_result(oracle.evaluate(state), profile)
        random_rewards = [first_random.reward] if first_random.admissible else []
        for _ in range(3000):
            if oracle.unique_evaluations >= result.unique_evaluations:
                break
            state = random_complete_state(profile, len(model.blocks), effective.max_chiplets,
                                          rng, model.name, model, effective.chiplet.sram_mb)
            random_score = score_result(oracle.evaluate(state), profile)
            if random_score.admissible:
                random_rewards.append(random_score.reward)
        candidate = result.best_candidate
        record = dict(bandwidth_bits_per_cycle=bandwidth, preference=preference, seed=seed,
            backend=candidate.backend if candidate else 'official', status=result.status,
            evaluations=result.unique_evaluations, episodes=result.episodes,
            stopping_reason=result.stopping_reason, design_space_size=result.design_space_size,
            global_optimum_certified=result.to_dict()['global_optimum_certified'],
            first_reward=first['reward'], best_reward=result.best_reward,
            policy_reward=result.policy_rollout['reward']['reward'],
            policy_matches_best=result.policy_rollout['matches_best_reward'],
            replay_converged=result.policy_rollout['replay_converged'],
            random_evaluations=oracle.unique_evaluations, random_best_reward=max(random_rewards) if random_rewards else None,
            ppa_feasible=result.best_breakdown.feasible if candidate else False,
            violated_constraints=result.best_breakdown.violated_constraints if candidate else (),
            architecture_feasible=candidate.architecture_feasible if candidate else None,
            latency_s=candidate.avg_latency_ns/1e9 if candidate else None, area_mm2=candidate.total_area_mm2 if candidate else None,
            power_w=candidate.total_power_w if candidate else None, fps_reported=candidate.achieved_fps if candidate else None,
            groups=result.best_state.groups if candidate else None,
            mapping_strategies=result.best_state.mapping_strategies if candidate else None,
            learned_actions=len(result.q_table),
            explore_steps=sum(h['explore_steps'] for h in result.history),
            exploit_steps=sum(h['exploit_steps'] for h in result.history),
            explored_strategies=sorted({s for h in result.history for s in h['mapping_strategies']}))
        records.append(record)
        print(json.dumps(record), flush=True)
        assert candidate is None or candidate.architecture_feasible
        assert record['replay_converged']
        assert record['policy_matches_best'] if candidate else not result.policy_rollout['admissible']
        assert oracle.unique_evaluations == result.unique_evaluations
    directory = ROOT / 'results/validation_0917'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'multi_seed_comparison_v4.json').write_text(
        json.dumps(_json_safe(records), indent=2), encoding='utf-8')
    return records


if __name__ == '__main__':
    validate()
