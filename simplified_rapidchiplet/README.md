# Simplified RapidChiplet

Traditional Chinese guide: [README_zh-TW.md](README_zh-TW.md)

This folder contains a compact DNN chiplet exploration prototype. It sweeps
model partitions and active chiplet counts on a mesh interconnect, then reports
latency, area, power, FPS, and a normalized PPA score.

The main evaluator uses only the Python standard library. If the official
RapidChiplet project path in `configs/defaults.json` exists, the evaluator calls
that engine for package/link metrics. If it does not exist, the evaluator falls
back to the local proxy in `simple_rapidchiplet/rapid_proxy.py`, so teammates can
still clone and run the simplified project directly.

Latency semantics: `avg_latency_ns` is the canonical Batch=1 analytical
end-to-end latency, computed as group compute time plus communication service
time. Rapid's traffic-weighted ICI latency is retained separately as
`rapid_avg_latency_ns` and is not used as the complete inference latency.

## Quick Start

```powershell
cd .\simplified_rapidchiplet
.\scripts\run_demo.ps1
```

Or run Python directly:

```powershell
python .\run.py --models shufflenet_v2_x1_0 --ppa-goal balanced --workload-search pareto-dp --dp-top-k 12 --out .\results\demo
```

Outputs are written to the selected output folder:

```text
best.csv
best.json
summary.csv
summary.json
chiplet_results.csv
report.html
```

Open `report.html` in a browser for the visual summary.

## Defaults

- models: `resnet50`, `shufflenet_v2_x1_0`
- target FPS: `15`
- available chiplets: up to `16`
- chiplet capacity: `8 x 8` PEs at `200 MHz`
- topology: `mesh` only
- workload search: `pareto-dp` with `--dp-top-k 12` (use brute-force as an oracle for validation)
- PPA goal: `balanced`

## Useful Commands

```powershell
python .\run.py --ppa-goal latency
python .\run.py --ppa-goal area
python .\run.py --ppa-goal power
python .\run.py --workload-search pareto-dp --dp-top-k 0
python .\run.py --target-fps 30 --ppa-goal balanced
python -m unittest discover -s tests
```

## Edit Inputs

Change chiplet, network, power, target FPS, and RapidChiplet assumptions in:

```text
configs/defaults.json
```

Change model workload assumptions in:

```text
configs/models.json
```
