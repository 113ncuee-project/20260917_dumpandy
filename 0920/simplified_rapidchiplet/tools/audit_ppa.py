"""Reproduce PPA semantics against a selected, unmodified RapidChiplet root."""
import argparse
import hashlib
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.evaluator import evaluate_one
from simple_rapidchiplet.model import ModelSpec, Stage, load_models
from simple_rapidchiplet.rapidchiplet_engine import _load_rapidchiplet_module, build_effective_inputs
from simple_rapidchiplet.topology import make_topology
from simple_rapidchiplet.workload import build_pipeline_workload


def run_audit(rapid_root):
    cfg = load_config(ROOT/'configs/defaults.json')
    cfg = replace(cfg, rapidchiplet=replace(cfg.rapidchiplet, root=str(Path(rapid_root).resolve()), backend='official'))
    rc = _load_rapidchiplet_module(cfg.rapidchiplet.root)
    base = ModelSpec('audit_base', 'synthetic', 'unit-test fixture', .003, .01, (
        Stage('A', .001, .2, (), 'conv', .1, .1, ('conv',)),
        Stage('B', .002, .1, ('A',), 'conv', .2, .1, ('conv',))))
    doubled_ops = replace(base, name='audit_double_MACs', macs_g=.006,
                          stages=tuple(replace(b, macs_g=2*b.macs_g) for b in base.blocks))
    doubled_tensor = replace(base, name='audit_double_tensor', stages=(
        replace(base.blocks[0], output_mb=.4), replace(base.blocks[1], input_mb=.4)))
    groups = ((0, 1, 1), (1, 2, 1))
    topo = make_topology('mesh', 2, cfg.chiplet.width_mm, cfg.chiplet.spacing_mm)
    rows = []
    results = []
    for model in (base, doubled_ops, doubled_tensor):
        workload = build_pipeline_workload(model, 2, groups)
        result = evaluate_one(model, 'mesh', 2, cfg, workload=workload)
        results.append(result)
        inputs = build_effective_inputs(topo, workload, cfg)
        inputs['verbose'] = False
        raw_power = rc.compute_power_summary(inputs, {})
        raw_area = rc.compute_area_summary(inputs, {})
        raw_latency = rc.compute_latency(inputs, {})
        assert math.isclose(result.power_fixed_utilization_w, raw_power['total_power']+result.link_static_power_w)
        assert math.isclose(result.total_area_mm2, raw_area['total_interposer_area'])
        assert math.isclose(result.rapid_avg_latency_cycles, raw_latency['avg'])
        assert math.isclose(result.e2e_latency_cycles, result.avg_latency_ns*cfg.chiplet.frequency_hz/1e9)
        assert math.isclose(result.avg_latency_ns, result.e2e_compute_latency_ns+
                            result.e2e_communication_serialization_ns+result.e2e_communication_path_latency_ns)
        rows.append(dict(name=model.name, raw_power=raw_power, raw_area=raw_area, raw_network_latency_cycles=raw_latency,
            adapter_fixed_power_w=result.power_fixed_utilization_w, static_link_power_w=result.link_static_power_w,
            power_avg_batch1_w=result.total_power_w, energy_per_inference_j=result.energy_per_inference_j,
            compute_dynamic_energy_j=result.compute_dynamic_energy_j, static_energy_j=result.static_energy_j,
            compute_ns=result.e2e_compute_latency_ns, serialization_ns=result.e2e_communication_serialization_ns,
            path_ns=result.e2e_communication_path_latency_ns, batch1_ns=result.avg_latency_ns,
            dynamic_link_energy_j=result.link_dynamic_energy_per_inference_j))
    a, b, c = results
    assert a.power_fixed_utilization_w == b.power_fixed_utilization_w == c.power_fixed_utilization_w
    assert a.total_area_mm2 == b.total_area_mm2 == c.total_area_mm2
    assert math.isclose(b.e2e_compute_latency_ns, 2*a.e2e_compute_latency_ns)
    assert math.isclose(c.e2e_communication_serialization_ns, 2*a.e2e_communication_serialization_ns)
    assert math.isclose(c.link_dynamic_energy_per_inference_j, 2*a.link_dynamic_energy_per_inference_j)
    assert math.isclose(b.compute_dynamic_energy_j, 2*a.compute_dynamic_energy_j)
    for r in results:
        assert math.isclose(r.total_power_w*r.power_observation_window_s, r.energy_per_inference_j)
    assert a.rapid_avg_latency_ns == b.rapid_avg_latency_ns == c.rapid_avg_latency_ns
    models = load_models(ROOT/'configs/models.json')
    real_rows = []
    # Actual legal mappings, both using the same nine-chiplet 3x3 mesh.
    for name, plan in [('resnet50', ((0,9,2),(9,14,2),(14,17,4),(17,18,1))),
                       ('resnet18', ((0,9,8),(9,10,1)))]:
        m = models[name]
        w = build_pipeline_workload(m, 2, plan)
        r = evaluate_one(m, 'mesh', 9, cfg, workload=w)
        assert r.architecture_feasible, r.architecture_violations
        real_rows.append(dict(model=name, groups=plan, power_w=r.total_power_w, area_mm2=r.total_area_mm2,
            die_area_mm2=r.total_chiplet_area_mm2, chiplet_power_w=r.total_chiplet_power_w,
            power_fixed_utilization_w=r.power_fixed_utilization_w, energy_per_inference_j=r.energy_per_inference_j,
            compute_dynamic_energy_j=r.compute_dynamic_energy_j, static_energy_j=r.static_energy_j,
            static_power_w=r.static_power_w, chiplet_active_times_s=r.chiplet_active_times_s,
            link_power_w=r.total_link_power_w, compute_ms=r.e2e_compute_latency_ns/1e6,
            serialization_ms=r.e2e_communication_serialization_ns/1e6,
            path_ms=r.e2e_communication_path_latency_ns/1e6, batch1_ms=r.avg_latency_ns/1e6,
            dynamic_link_energy_j=r.link_dynamic_energy_per_inference_j))
    assert real_rows[0]['power_fixed_utilization_w'] == real_rows[1]['power_fixed_utilization_w']
    assert real_rows[0]['area_mm2'] == real_rows[1]['area_mm2']
    hashes = {name: hashlib.sha256((Path(cfg.rapidchiplet.root)/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
              for name in ('rapidchiplet.py','helpers.py','validation.py','booksim_wrapper.py')}
    return dict(reference_root=cfg.rapidchiplet.root, reference_lf_sha256=hashes,
                bandwidth_bits_per_cycle=cfg.network.link_bandwidth_bits_per_cycle,
                synthetic_checks=rows, real_model_fixed_hardware=real_rows,
                note='Synthetic cases verify formulas; real model cases are fixed legal mappings, not optimized runs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rapid-root', default=load_config(ROOT/'configs/defaults.json').rapidchiplet.root)
    args = parser.parse_args()
    data = run_audit(args.rapid_root)
    target = ROOT/'validation/ppa_original_audit.json'
    target.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    print(target)
    print(json.dumps(data['real_model_fixed_hardware'], indent=2))


if __name__ == '__main__':
    main()
