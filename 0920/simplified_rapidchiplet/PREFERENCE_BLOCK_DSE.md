# Preference-aware mapping DSE (0917 revision)

Implementation and mathematical details: [Chinese review](0917_IMPLEMENTATION_REVIEW_zh-TW.md).

Current GUI/multi-model and hard/soft scoring specification: [GUI guide](GUI_GUIDE_zh-TW.md). Directional weights are 0.6/0.2/0.2. Each metric has its own strict switch; only admissible candidates enter the best archive. No admissible candidate means null, never a violating fallback design. Soft metrics use the documented bonus/penalty; architectural constraints remain hard. MobileNetV2 supports single/OC, while SqueezeNet Fire blocks stay on one chiplet until parallel concat semantics are implemented.

1. Parse calibrated block metadata, validate tensor sizes and the dependency DAG.
2. Mask actions by SRAM, channel partitions, Head support and remaining capacity.
3. Establish a minimum-capacity baseline; explore full legal actions with epsilon, exploit learned Q values.
4. Build tensor ownership events for dependency edges and intra-block redistributions/reductions.
5. Evaluate those same flows with configured Rapid inputs and analytical E2E timing.
6. Train from terminal PPA reward with discount 1. Cache by groups **and mapping strategies**.
7. Export the best evaluated design and a separate Q-policy rollout, with replay convergence, budget stopping reason and history.

The model is task-specific tabular RL. Its Q table records complete design prefixes; it is not a pretrained policy with demonstrated transfer across models or preferences. Replay converges only on observed transitions. Full optimality is certified only when the entire feasible architecture space has been evaluated.

Supported strategies: single, output channel, input channel. Spatial tiling is disabled until a correct tensor/tile model is available. FPS has no role in constraints, reward or power.

Run `python run.py --help`; use the current CSV/JSON outputs. Historical DP sweeps and presentation assets retain their historical definitions and cannot substantiate this revision's results.
