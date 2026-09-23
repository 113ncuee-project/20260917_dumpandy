# 0917 PPA-only Chiplet DSE

**Windows classmates: download/extract the repository and double-click `Start Chiplet Lab.cmd` at its root, or `Start GUI.cmd` here.** No installed Python or Codex runtime is required. The first launch downloads pinned, SHA-256-verified Python and official RapidChiplet files into `.runtime`; subsequent launches work offline. See [portable setup](PORTABLE_PACKAGE_zh-TW.md).

[GUI 與多模型使用說明](GUI_GUIDE_zh-TW.md) · [先前實作檢查](0917_IMPLEMENTATION_REVIEW_zh-TW.md)

Run **`python gui.py`** (or double-click **Start GUI.cmd**) for the local GUI: independent hard/soft PPA switches, calibrated model selection, and actual chiplet placement / routed tensor flows. Directional preference weights are now **0.6 / 0.2 / 0.2**; balanced is equal.

The current entry point is tabular Q-learning over contiguous block groups, chiplet counts and OC/IC mapping strategies. User inputs are PPA limits and preference. FPS is a reported metric only.

```powershell
python .\run.py --preference balanced --max-latency-ns 500000000 --max-area-mm2 800 --max-power-w 16
```

- Defaults: `configs/defaults.json`; calibrated workloads: ResNet-50 v1.5, ResNet-18, MobileNetV2 and SqueezeNet 1.1, batch 1, FP32. All four have actual CPU forward / shape / parameter / Conv+Linear MAC records in `validation/model_forward_validation.json`.
- PPA power is Batch-1 energy divided by its latency; 0.8175 W per chiplet is retained only in the fixed-utilization diagnostic. Hardware uses the user-confirmed **256 bits/cycle/direction** default link bandwidth.
- The official Rapid engine receives generated inputs and explicit directed link bandwidths. The portable default is `root=../.runtime/rapidchiplet` relative to the config file and `backend=official`; the launcher prepares it automatically. No per-machine path is needed, and failed official imports do not silently fall back.
- Results: `results/preference_dse/preference_search_summary.csv`, full JSON, and a configuration/source-hash manifest.
- Failed strict PPA constraints exclude a design from both best candidate and policy delivery; no acceptable result means `best_candidate=null`. Unchecked constraints permit overshoot with explicit bonus/penalty. CLI: `--no-strict-latency`, `--no-strict-area`, `--no-strict-power`. A 128-evaluation search is not a global optimum certificate.

```powershell
python -m unittest discover -s tests
python tools/validate_0917.py
```

The validation script requires the official engine and compares matched-budget Q-learning and random search. Its current output is `multi_seed_comparison_v4.json`. EfficientNet/ShuffleNet entries and historical DP/presentation helpers remain prototypes. MobileNetV2 IC and within-Fire parallel mapping are deliberately masked until validated; see the GUI guide for supported traffic semantics.

[Batch-1 average power, energy and assumptions](BATCH1_POWER_zh-TW.md). FPS is output only.
