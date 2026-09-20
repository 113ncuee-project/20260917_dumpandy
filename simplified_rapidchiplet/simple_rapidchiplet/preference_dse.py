"""Preference-aware direct-action DSE over a fine-grained CNN block graph.

This module is intentionally independent from the legacy exhaustive/DP sweep.
It turns a model into smaller pipeline blocks, lets the agent assign any
contiguous block group to any positive number of chiplets, and learns a
preference-conditioned policy with terminal PPA/constraint feedback.
"""

from __future__ import annotations

import csv
import json
import math
import random
from functools import lru_cache
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterable, Literal

from .config import EvalConfig
from .evaluator import EvaluationResult, evaluate_one
from .block_extractor import extract_semantic_blocks
from .mapping import mapping_action_is_feasible
from .model import ModelSpec
from .workload import build_pipeline_workload


PreferenceName = Literal["balanced", "latency", "area", "power"]


def _json_safe(value: object) -> object:
    """Convert non-finite floats to JSON null for portable result files."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class PreferenceProfile:
    """User constraints and the direction of the PPA trade-off."""

    name: PreferenceName
    latency_weight: float
    area_weight: float
    power_weight: float
    max_latency_ns: float = math.inf
    max_area_mm2: float = math.inf
    max_power_w: float = math.inf
    strict_latency: bool = True
    strict_area: bool = True
    strict_power: bool = True
    # Used only when a user does not provide a hard limit.  It keeps the
    # reward scale stable while still making lower latency/area/power better.
    latency_scale_ns: float = 1_000_000.0
    area_scale_mm2: float = 1_000.0
    power_scale_w: float = 16.0

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in
               (self.strict_latency, self.strict_area, self.strict_power)):
            raise ValueError("strict constraint switches must be booleans")
        weights = (self.latency_weight, self.area_weight, self.power_weight)
        if any(not math.isfinite(value) or value < 0.0 for value in weights):
            raise ValueError("preference weights must be finite and non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("preference weights must sum to one")
        for name in ("max_latency_ns", "max_area_mm2", "max_power_w"):
            value = getattr(self, name)
            if not math.isfinite(value) and value != math.inf:
                raise ValueError(f"{name} must be finite or +inf")
            if value <= 0.0 and value != math.inf:
                raise ValueError(f"{name} must be positive when provided")
        if any(not math.isfinite(v) or v <= 0 for v in
               (self.latency_scale_ns, self.area_scale_mm2, self.power_scale_w)):
            raise ValueError("reward scales must be finite and positive")

    @property
    def weights(self) -> tuple[float, float, float]:
        return self.latency_weight, self.area_weight, self.power_weight

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def constraint_key(self) -> tuple[tuple[str, float], ...]:
        return (
            ("max_latency_ns", self.max_latency_ns),
            ("max_area_mm2", self.max_area_mm2),
            ("max_power_w", self.max_power_w),
            ("strict_latency", self.strict_latency),
            ("strict_area", self.strict_area),
            ("strict_power", self.strict_power),
        )


def make_preference_profile(
    name: PreferenceName = "balanced",
    *,
    max_latency_ns: float = math.inf,
    max_area_mm2: float = math.inf,
    max_power_w: float = math.inf,
    strict_latency: bool = True,
    strict_area: bool = True,
    strict_power: bool = True,
    cfg: EvalConfig | None = None,
) -> PreferenceProfile:
    """Create one user preference profile.

    Missing limits use fixed fallback scales. Each supplied limit has its own
    strict switch: True rejects a violating design, False applies soft scoring.
    """

    if name == "balanced":
        weights = (1 / 3, 1 / 3, 1 / 3)
    else:
        weights = {
            "latency": (0.6, 0.2, 0.2),
            "area": (0.2, 0.6, 0.2),
            "power": (0.2, 0.2, 0.6),
        }[name]
    total = sum(weights)
    if total <= 0.0:
        raise ValueError("preference weights must have a positive sum")
    normalised = tuple(value / total for value in weights)

    area_scale = 1_000.0
    power_scale = 16.0
    if cfg is not None:
        area_scale = max(
            1.0,
            cfg.max_chiplets * cfg.chiplet.width_mm * cfg.chiplet.width_mm,
        )
        power_scale = max(
            1.0,
            cfg.max_chiplets
            * (
                cfg.power.chiplet_static_w
                + cfg.power.chiplet_peak_dynamic_w * cfg.chiplet.utilization
                + cfg.power.phy_w
            ),
        )

    return PreferenceProfile(
        name=name,
        latency_weight=normalised[0],
        area_weight=normalised[1],
        power_weight=normalised[2],
        max_latency_ns=max_latency_ns,
        max_area_mm2=max_area_mm2,
        max_power_w=max_power_w,
        strict_latency=strict_latency,
        strict_area=strict_area,
        strict_power=strict_power,
        area_scale_mm2=area_scale,
        power_scale_w=power_scale,
    )


@dataclass(frozen=True, order=True)
class DesignState:
    """Immutable RL state for sequential block-group construction."""

    preference: str
    next_block: int = 0
    used_chiplets: int = 0
    groups: tuple[tuple[int, int, int], ...] = ()
    model: str = ""
    constraints: tuple[tuple[str, float], ...] = ()
    mapping_strategies: tuple[str, ...] = ()


@dataclass(frozen=True, order=True)
class DesignAction:
    """Assign a contiguous block group and choose its intra-block mapping."""

    group_length: int
    chiplets: int
    mapping_strategy: str = "output_channel"

    @property
    def label(self) -> str:
        return (
            f"assign(length={self.group_length}, chiplets={self.chiplets}, "
            f"mapping={self.mapping_strategy})"
        )


@lru_cache(maxsize=32768)
def minimum_suffix_chiplets(model, start, max_chiplets, sram_mb):
    """Exact minimum resident chiplets for the remaining contiguous blocks."""
    if start == len(model.blocks):
        return 0
    best = None
    for end in range(start + 1, len(model.blocks) + 1):
        for parts in range(1, max_chiplets + 1):
            strategies = ("single",) if parts == 1 else ("output_channel", "input_channel")
            if any(mapping_action_is_feasible(model, start, end, parts, strategy,
                    sram_mb=sram_mb) for strategy in strategies):
                suffix = minimum_suffix_chiplets(model, end, max_chiplets, sram_mb)
                if suffix is not None:
                    best = min(best, parts + suffix) if best is not None else parts + suffix
    return best


@lru_cache(maxsize=16384)
def legal_actions(
    state: DesignState,
    block_count: int,
    max_chiplets: int,
    model: ModelSpec | None = None,
    sram_mb: float = math.inf,
) -> tuple[DesignAction, ...]:
    """Return all legal split/merge/parallelisation actions.

    Unlike the legacy workload search, there is deliberately no condition on
    ``group_length``.  A group containing one block or many blocks can use any
    positive number of chiplets, as long as the complete design remains
    finishable under the chiplet budget.
    """

    if block_count < 1 or max_chiplets < 1:
        raise ValueError("block_count and max_chiplets must be positive")
    if not 0 <= state.next_block <= block_count:
        raise ValueError("state.next_block is outside the block graph")
    if not 0 <= state.used_chiplets <= max_chiplets:
        raise ValueError("state.used_chiplets is outside the chiplet budget")
    if state.next_block == block_count:
        return ()

    remaining_blocks = block_count - state.next_block
    remaining_chiplets = max_chiplets - state.used_chiplets
    actions: list[DesignAction] = []

    for group_length in range(1, remaining_blocks + 1):
        blocks_after = remaining_blocks - group_length
        reserve = 1 if blocks_after else 0
        max_parts = remaining_chiplets - reserve
        for parts in range(1, max_parts + 1):
            strategies = ("single",) if parts == 1 else (
                "output_channel",
                "input_channel",
            )
            for strategy in strategies:
                if model is not None:
                    if not mapping_action_is_feasible(
                        model,
                        state.next_block,
                        state.next_block + group_length,
                        parts,
                        strategy,
                        sram_mb=sram_mb,
                    ):
                        continue
                    suffix_minimum = minimum_suffix_chiplets(model, state.next_block + group_length, max_chiplets, sram_mb)
                    if suffix_minimum is None or parts + suffix_minimum > remaining_chiplets:
                        continue
                actions.append(DesignAction(group_length, parts, strategy))
    return tuple(actions)


def apply_action(
    state: DesignState,
    action: DesignAction,
    block_count: int,
    max_chiplets: int,
    model: ModelSpec | None = None,
    sram_mb: float = math.inf,
) -> DesignState:
    if action not in legal_actions(state, block_count, max_chiplets, model, sram_mb):
        raise ValueError(f"illegal action: {action.label}")
    start = state.next_block
    end = start + action.group_length
    return DesignState(
        preference=state.preference,
        next_block=end,
        used_chiplets=state.used_chiplets + action.chiplets,
        groups=state.groups + ((start, end, action.chiplets),),
        model=state.model,
        constraints=state.constraints,
        mapping_strategies=state.mapping_strategies + (action.mapping_strategy,),
    )


def is_complete(state: DesignState, block_count: int) -> bool:
    return state.next_block == block_count and bool(state.groups)


def random_complete_state(
    preference: PreferenceProfile,
    block_count: int,
    max_chiplets: int,
    rng: random.Random,
    model_name: str = "",
    model: ModelSpec | None = None,
    sram_mb: float = math.inf,
) -> DesignState:
    state = DesignState(
        preference=preference.name,
        model=model_name,
        constraints=preference.constraint_key,
    )
    while not is_complete(state, block_count):
        actions = legal_actions(state, block_count, max_chiplets, model, sram_mb)
        if not actions:
            raise RuntimeError("action mask produced a dead-end state")
        state = apply_action(
            state,
            rng.choice(actions),
            block_count,
            max_chiplets,
            model,
            sram_mb,
        )
    return state


def design_key(state):
    from .mapping import default_mapping_strategies
    strategies = state.mapping_strategies or default_mapping_strategies(state.groups)
    if len(strategies) != len(state.groups):
        raise ValueError("one strategy is required per group")
    return (state.groups, tuple("single" if group[2] == 1 else strategy
                                for group, strategy in zip(state.groups, strategies)))


@dataclass(frozen=True)
class RewardBreakdown:
    reward: float
    feasible: bool
    weighted_cost: float
    total_violation: float
    latency_ratio: float
    area_ratio: float
    power_ratio: float
    violated_constraints: tuple[str, ...]
    architecture_feasible: bool
    architecture_violations: tuple[str, ...]
    admissible: bool = True
    hard_violations: tuple[str, ...] = ()
    base_reward: float = 0.0
    bonus: float = 0.0
    penalty: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _soft_ratio(value: float, limit: float, fallback_scale: float) -> float:
    if not math.isfinite(value) or value < 0.0:
        return math.inf
    return value / limit if math.isfinite(limit) else value / fallback_scale


def score_result(
    result: EvaluationResult,
    profile: PreferenceProfile,
) -> RewardBreakdown:
    """Hard constraints gate admission; soft limits contribute bonus/penalty.

    r = metric/limit; cost = sum(w*r); base = 1/(1+cost).
    Soft bonus = .25*sum(w*max(0,1-r)); soft penalty =
    sum(w*excess/(1+excess)). Accepted reward = base+bonus-penalty (> -1).
    Rejected reward is below -2, so Q never prefers rejection to admission.
    ``feasible`` means all PPA targets met; ``admissible`` respects only checked
    constraints plus the always-hard architectural and finite-metric checks.
    """

    latency_ratio = _soft_ratio(
        result.avg_latency_ns, profile.max_latency_ns, profile.latency_scale_ns
    )
    area_ratio = _soft_ratio(
        result.total_area_mm2, profile.max_area_mm2, profile.area_scale_mm2
    )
    power_ratio = _soft_ratio(
        result.total_power_w, profile.max_power_w, profile.power_scale_w
    )
    violations: list[tuple[str, float]] = []
    if math.isfinite(profile.max_latency_ns):
        violations.append(("latency", max(0.0, latency_ratio - 1.0)))
    if math.isfinite(profile.max_area_mm2):
        violations.append(("area", max(0.0, area_ratio - 1.0)))
    if math.isfinite(profile.max_power_w):
        violations.append(("power", max(0.0, power_ratio - 1.0)))

    architecture_feasible = bool(getattr(result, "architecture_feasible", True))
    architecture_violations = tuple(getattr(result, "architecture_violations", ()))
    if not architecture_feasible:
        # Architecture invalidity is a hard feasibility failure, independent
        # of the user's soft PPA direction.
        violations.append(("architecture", 1.0 + min(1.0, len(architecture_violations) / 10.0)))

    if any(not math.isfinite(v) for v in (latency_ratio, area_ratio, power_ratio)):
        violations.append(("invalid_metric", math.inf))
    total_violation = sum(value for _name, value in violations)
    feasible = total_violation == 0.0
    weighted_cost = sum(w * r for w, r in zip(profile.weights,
                        (latency_ratio, area_ratio, power_ratio)) if w > 0)
    hard_names = {name for name in ("latency", "area", "power")
                  if getattr(profile, "strict_" + name)} | {"architecture", "invalid_metric"}
    hard = tuple(name for name, value in violations if value > 0 and name in hard_names)
    admissible = not hard
    base = 1.0 / (1.0 + weighted_cost)
    bonus = penalty = 0.0
    for name, weight, ratio in zip(("latency", "area", "power"), profile.weights,
                                   (latency_ratio, area_ratio, power_ratio)):
        limit = getattr(profile, {"latency": "max_latency_ns", "area": "max_area_mm2", "power": "max_power_w"}[name])
        if not getattr(profile, "strict_" + name) and math.isfinite(limit) and math.isfinite(ratio):
            excess = max(0., ratio - 1.)
            bonus += .25 * weight * max(0., 1. - ratio)
            penalty += weight * excess / (1. + excess)
    hard_severity = sum(value for name, value in violations if name in hard_names)
    reward = base + bonus - penalty if admissible else -2.0 - (
        hard_severity / (1.0 + hard_severity) if math.isfinite(hard_severity) else 1.0)
    return RewardBreakdown(
        reward=reward,
        feasible=feasible,
        weighted_cost=weighted_cost,
        total_violation=total_violation,
        latency_ratio=latency_ratio,
        area_ratio=area_ratio,
        power_ratio=power_ratio,
        violated_constraints=tuple(name for name, value in violations if value > 0.0),
        architecture_feasible=architecture_feasible,
        architecture_violations=architecture_violations,
        admissible=admissible, hard_violations=hard,
        base_reward=base, bonus=bonus, penalty=penalty,
    )


@dataclass
class EvaluationOracle:
    model: ModelSpec
    cfg: EvalConfig
    profile: PreferenceProfile
    max_chiplets: int
    _cache: dict[tuple, EvaluationResult] = field(default_factory=dict)
    requests: int = 0

    def evaluate(self, state: DesignState) -> EvaluationResult:
        if not is_complete(state, len(self.model.blocks)):
            raise ValueError("only complete designs can be evaluated")
        if sum(g[2] for g in state.groups) != state.used_chiplets or state.used_chiplets > self.max_chiplets:
            raise ValueError("state chiplet count does not match the complete design")
        key = design_key(state)
        self.requests += 1
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        workload = build_pipeline_workload(
            self.model,
            self.cfg.chiplet.op_per_mac,
            state.groups,
            search_method="preference-q-learning",
            mapping_strategies=state.mapping_strategies or None,
        )
        result = evaluate_one(
            self.model,
            "mesh",
            state.used_chiplets,
            self.cfg,
            workload=workload,
            ppa_goal=self.profile.name,
        )
        result = replace(result, ppa_score=score_result(result, self.profile).weighted_cost)
        self._cache[key] = result
        return result

    @property
    def unique_evaluations(self) -> int:
        return len(self._cache)


@dataclass(frozen=True)
class PreferenceSearchResult:
    model: str
    block_source: str
    extraction_report: dict[str, object]
    preference: dict[str, object]
    seed: int
    block_split: int
    evaluation_budget: int
    unique_evaluations: int
    requests: int
    episodes: int
    final_epsilon: float
    best_reward: float | None
    best_breakdown: RewardBreakdown | None
    best_state: DesignState | None
    best_candidate: EvaluationResult | None
    history: tuple[dict[str, object], ...]
    policy_rollout: dict[str, object]
    q_table: tuple[dict[str, object], ...]
    stopping_reason: str
    design_space_size: int
    replay_sweeps: int

    @property
    def status(self):
        return "completed" if self.best_candidate is not None else "no_admissible_design"

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "status": self.status,
            "block_source": self.block_source,
            "extraction_report": self.extraction_report,
            "preference": self.preference,
            "seed": self.seed,
            "block_split": self.block_split,
            "evaluation_budget": self.evaluation_budget,
            "unique_evaluations": self.unique_evaluations,
            "requests": self.requests,
            "episodes": self.episodes,
            "final_epsilon": self.final_epsilon,
            "best_reward": self.best_reward,
            "best_breakdown": self.best_breakdown.to_dict() if self.best_breakdown else None,
            "best_state": asdict(self.best_state) if self.best_state else None,
            "best_candidate": self.best_candidate.to_dict() if self.best_candidate else None,
            "history": list(self.history),
            "policy_rollout": self.policy_rollout,
            "q_table": list(self.q_table),
            "stopping_reason": self.stopping_reason,
            "design_space_size": self.design_space_size,
            "replay_sweeps": self.replay_sweeps,
            "global_optimum_certified": self.best_candidate is not None and self.unique_evaluations == self.design_space_size,
        }


def q_learning_search(
    model, cfg, profile, *, block_split=1, evaluation_budget=128, seed=1,
    max_episodes=None, learning_rate=.2, discount=1.0,
    epsilon_start=.8, epsilon_end=.05, epsilon_decay=.99,
    progress_callback=None, should_cancel=None,
):
    """Finite-horizon tabular Q-learning; terminal PPA only, no depth discount.

    The archive is the best evaluated design. A separate greedy rollout is
    exported from Q values, after replay on observed transitions. Replay is
    convergence on the sampled subgraph, never a claim of global convergence.
    """
    if type(evaluation_budget) is not int or evaluation_budget < 1 or (
        max_episodes is not None and (type(max_episodes) is not int or max_episodes < 1)
    ):
        raise ValueError("evaluation budget and episode limit must be positive")
    if not 0 < learning_rate <= 1 or not 0 < epsilon_decay <= 1:
        raise ValueError("learning rate and epsilon decay must be in (0,1]")
    if not 0 <= epsilon_end <= epsilon_start <= 1:
        raise ValueError("epsilon values must satisfy 0 <= end <= start <= 1")
    if discount != 1.0:
        raise ValueError("Use discount=1 in this finite-horizon task to avoid rewarding fewer groups")
    extracted, report = extract_semantic_blocks(model, legacy_split_factor=block_split)
    count = len(extracted.blocks)
    oracle = EvaluationOracle(extracted, cfg, profile, cfg.max_chiplets)
    rng = random.Random(seed)
    initial = DesignState(profile.name, model=model.name, constraints=profile.constraint_key)
    def actions(state):
        return legal_actions(state, count, cfg.max_chiplets, extracted, cfg.chiplet.sram_mb)
    def advance(state, action):
        return apply_action(state, action, count, cfg.max_chiplets, extracted, cfg.chiplet.sram_mb)
    if not actions(initial):
        raise ValueError("No complete mapping fits the chiplet/SRAM limits; increase hardware capacity or revise the workload")
    @lru_cache(maxsize=None)
    def suffix_count(start, used):
        if start == count:
            return 1
        proxy = DesignState(profile.name, next_block=start, used_chiplets=used)
        return sum(suffix_count(start+a.group_length, used+a.chiplets) for a in actions(proxy))
    space_size = suffix_count(0, 0)
    budget = min(evaluation_budget, space_size)
    q, visits, transitions, history = {}, {}, {}, []
    observed = {}
    episodes = 0
    epsilon = epsilon_start
    best = None
    cap = max_episodes or max(1000, evaluation_budget * 30)
    stagnant = 0
    while oracle.unique_evaluations < budget and episodes < cap:
        if should_cancel and should_cancel():
            raise InterruptedError("Search cancelled")
        episodes += 1
        state = initial
        trajectory = []
        explore_steps = exploit_steps = 0
        while not is_complete(state, count):
            allowed = actions(state)
            if episodes == 1:
                # Deterministic capacity baseline prevents a sparse first budget
                # from overlooking the smallest admissible package entirely.
                action = min(allowed, key=lambda a: (
                    a.chiplets + minimum_suffix_chiplets(extracted, state.next_block+a.group_length,
                                                        cfg.max_chiplets, cfg.chiplet.sram_mb),
                    -a.group_length, a.chiplets, a.mapping_strategy == "input_channel"))
            elif rng.random() < epsilon or stagnant >= 50:
                action = rng.choice(allowed)
                explore_steps += 1
            else:
                # Unvisited optimistic children must not hide every measured
                # terminal reward. Epsilon explores the full legal mask;
                # exploitation compares the actions actually learned so far.
                learned = sorted(observed.get(state, allowed))
                scores = [q.get((state, a), 0.0) for a in learned]
                maximum = max(scores)
                action = rng.choice([a for a, value in zip(learned, scores) if abs(value-maximum) < 1e-12])
                if state in observed:
                    exploit_steps += 1
                else:
                    explore_steps += 1
            following = advance(state, action)
            trajectory.append((state, action, following))
            state = following
        key = design_key(state)
        is_new = key not in oracle._cache
        candidate = oracle.evaluate(state)
        reward = score_result(candidate, profile)
        rank = (reward.reward,
                -reward.weighted_cost, -candidate.avg_latency_ns, -candidate.total_area_mm2, -candidate.total_power_w)
        if reward.admissible and (best is None or rank > best[0]):
            best = (rank, state, candidate, reward)
        stagnant = 0 if is_new else stagnant + 1
        for previous, action, following in reversed(trajectory):
            pair = (previous, action)
            terminal = is_complete(following, count)
            transitions[pair] = (following, reward.reward if terminal else None)
            observed.setdefault(previous, set()).add(action)
            visits[pair] = visits.get(pair, 0) + 1
            target = reward.reward if terminal else max(q[(following, a)] for a in observed[following])
            # Initialize a newly sampled action from its first measured target.
            # Reverse updates make that target available through the full path.
            current = q.get(pair, target)
            q[pair] = current + learning_rate * (target-current)
        history.append(dict(episode=episodes, evaluations=oracle.unique_evaluations, is_new=is_new,
            reward=reward.reward, feasible=reward.feasible, admissible=reward.admissible,
            hard_violations=reward.hard_violations, groups=state.groups,
            exploration="minimum_capacity_baseline" if episodes == 1 else "epsilon_greedy_q",
            explore_steps=explore_steps, exploit_steps=exploit_steps,
            mapping_strategies=state.mapping_strategies, best_reward=best[3].reward if best else None, epsilon=epsilon))
        if progress_callback and (is_new or episodes % 25 == 0):
            progress_callback(dict(model=model.name, evaluations=oracle.unique_evaluations,
                                   budget=budget, episodes=episodes, best_reward=best[3].reward if best else None))
        epsilon = max(epsilon_end, epsilon * epsilon_decay)

    # Once new evaluations stop, train on the observed finite DAG only. No
    # unevaluated optimistic leaf may silently become the delivered policy.
    order = sorted(transitions, key=lambda pair: pair[0].next_block, reverse=True)
    sweeps = 0
    for sweeps in range(1, 501):
        if should_cancel and should_cancel():
            raise InterruptedError("Search cancelled")
        delta = 0.
        for pair in order:
            following, terminal_reward = transitions[pair]
            target = terminal_reward if terminal_reward is not None else max(q[(following,a)] for a in observed[following])
            old = q[pair]
            q[pair] = old + learning_rate * (target-old)
            delta = max(delta, abs(q[pair]-old))
        if delta < 1e-12:
            break
    policy_state = initial
    while not is_complete(policy_state, count):
        action = max(observed[policy_state], key=lambda a: (q[(policy_state,a)], a))
        policy_state = advance(policy_state, action)
    policy_candidate = oracle._cache[design_key(policy_state)]
    policy_reward = score_result(policy_candidate, profile)
    stop = "design_space_exhausted" if oracle.unique_evaluations == space_size else (
        "evaluation_budget" if oracle.unique_evaluations == budget else "episode_limit")
    return PreferenceSearchResult(
        model=model.name, block_source=extracted.block_source, extraction_report=report.to_dict(),
        preference=profile.to_dict(), seed=seed, block_split=block_split, evaluation_budget=evaluation_budget,
        unique_evaluations=oracle.unique_evaluations, requests=oracle.requests, episodes=episodes,
        final_epsilon=epsilon, best_reward=best[3].reward if best else None,
        best_breakdown=best[3] if best else None, best_state=best[1] if best else None,
        best_candidate=best[2] if best else None, history=tuple(history),
        policy_rollout=dict(state=asdict(policy_state) if policy_reward.admissible else None, reward=policy_reward.to_dict(),
            candidate=policy_candidate.to_dict() if policy_reward.admissible else None,
            admissible=policy_reward.admissible, scope="greedy_policy_on_evaluated_designs",
            replay_converged=delta < 1e-12, final_replay_delta=delta,
            matches_best_reward=bool(best and math.isclose(policy_reward.reward, best[3].reward, abs_tol=1e-8))),
        q_table=tuple(dict(state=asdict(st), action=asdict(a), value=q[(st,a)], visits=visits[(st,a)])
                      for st, a in sorted(q)),
        stopping_reason=stop, design_space_size=space_size, replay_sweeps=sweeps,
    )


def write_search_outputs(
    output_dir: str | Path,
    results: Iterable[PreferenceSearchResult],
) -> dict[str, Path]:
    """Write machine-readable results for the new preference-aware run."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    values = list(results)
    json_path = directory / "preference_search_results.json"
    json_path.write_text(
        json.dumps(
            _json_safe([result.to_dict() for result in values]),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summaries = []
    for result in values:
        candidate = result.best_candidate
        summaries.append(
            {
                "model": result.model,
                "preference": result.preference["name"],
                "reward": result.best_reward,
                "status": result.status,
                "feasible": result.best_breakdown.feasible if candidate else False,
                "violated_constraints": ",".join(result.best_breakdown.violated_constraints) if candidate else "",
                "evaluations": result.unique_evaluations,
                "episodes": result.episodes,
                "blocks": len(candidate.block_graph.get("nodes", [])) if candidate else None,
                "chiplets": candidate.selected_chiplets if candidate else None,
                "fps": candidate.achieved_fps if candidate else None,
                "latency_ns": candidate.avg_latency_ns if candidate else None,
                "area_mm2": candidate.total_area_mm2 if candidate else None,
                "power_w": candidate.total_power_w if candidate else None,
                "workload_plan": candidate.workload_plan if candidate else None,
            }
        )
    csv_path = directory / "preference_search_summary.csv"
    if summaries:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            _json_safe(
                {
                    "version": "ppa-per-metric-hard-soft-dse-v4",
                    "results": len(values),
                    "method": "tabular_q_learning_terminal_preference_reward",
                    "semantic_block_extraction": True,
                    "arbitrary_group_parallelization": True,
                    "intra_block_mapping": [
                        "single",
                        "output_channel",
                        "input_channel",
                    ],
                    "feasibility_checker": True,
                    "fps_role": "reported_only",
                    "traffic_model": "shared_tensor_ownership_events",
                    "spatial_mapping": "disabled_until_tile_metadata_is_available",
                    "dependency_aware_scheduler": True,
                    "outputs": [json_path.name, csv_path.name],
                }
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"json": json_path, "csv": csv_path, "manifest": manifest_path}
