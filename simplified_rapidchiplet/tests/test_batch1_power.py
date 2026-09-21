import math
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.evaluator import evaluate_one
from simple_rapidchiplet.model import ModelSpec, Stage
from simple_rapidchiplet.power import estimate_batch1_power
from simple_rapidchiplet.preference_dse import make_preference_profile, score_result, q_learning_search
from simple_rapidchiplet.workload import build_pipeline_workload
import simple_rapidchiplet.evaluator as evaluator

ROOT = Path(__file__).resolve().parents[1]


class Batch1PowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = load_config(ROOT/'configs/defaults.json')
        cls.cfg = replace(cfg, rapidchiplet=replace(cfg.rapidchiplet, backend='local'))
        cls.model = ModelSpec('power_fixture', 'synthetic', 'test', .003, .01, (
            Stage('A', .001, .2, (), 'conv', .1, .1, ('conv',)),
            Stage('B', .002, .1, ('A',), 'conv', .2, .1, ('conv',))))

    def evaluate(self, model=None, cfg=None):
        m = model or self.model
        return evaluate_one(m, 'mesh', 2, cfg or self.cfg,
                            workload=build_pipeline_workload(m, 2, ((0,1,1),(1,2,1))))

    def core(self, **overrides):
        args = dict(assigned_ops=(19.2e6, 0), compute_efficiencies=(1., 1.),
                    observation_window_s=.002, link_static_power_w=.04,
                    router_static_power_w=.02, link_dynamic_energy_j=1e-6)
        args.update(overrides)
        return estimate_batch1_power(self.cfg, **args)

    def test_energy_conservation_and_average_components(self):
        r = self.evaluate()
        t = r.avg_latency_ns / 1e9
        self.assertAlmostEqual(r.total_power_w*t, r.energy_per_inference_j, places=14)
        self.assertEqual(r.total_power_w, r.power_avg_batch1_w)
        self.assertEqual(t, r.power_observation_window_s)
        self.assertAlmostEqual(r.energy_per_inference_j, r.static_energy_j+
                               r.compute_dynamic_energy_j+r.link_dynamic_energy_j, places=14)
        self.assertAlmostEqual(r.total_power_w, r.total_chiplet_power_w+
                               r.total_link_power_w+r.total_interposer_power_w, places=12)

    def test_more_MACs_increase_compute_energy_not_a_model_size_factor(self):
        m = replace(self.model, macs_g=self.model.macs_g*2,
                    stages=tuple(replace(b, macs_g=b.macs_g*2) for b in self.model.blocks))
        a, b = self.evaluate(), self.evaluate(m)
        self.assertAlmostEqual(b.compute_dynamic_energy_j, 2*a.compute_dynamic_energy_j, places=14)
        self.assertEqual(a.link_dynamic_energy_j, b.link_dynamic_energy_j)
        self.assertEqual(a.total_area_mm2, b.total_area_mm2)
        self.assertEqual(a.power_fixed_utilization_w, b.power_fixed_utilization_w)

    def test_more_traffic_increases_link_energy(self):
        m = replace(self.model, stages=(replace(self.model.blocks[0], output_mb=.4),
                                        replace(self.model.blocks[1], input_mb=.4)))
        a, b = self.evaluate(), self.evaluate(m)
        self.assertAlmostEqual(b.link_dynamic_energy_j, 2*a.link_dynamic_energy_j, places=14)
        self.assertEqual(a.compute_dynamic_energy_j, b.compute_dynamic_energy_j)
        self.assertEqual(a.total_area_mm2, b.total_area_mm2)
        self.assertGreater(b.static_energy_j, a.static_energy_j)  # longer Batch-1 window

    def test_idle_installed_chiplet_has_zero_compute_energy_but_static_power(self):
        r = self.core()
        self.assertEqual(r.chiplet_active_times_s, (.001, 0))
        self.assertEqual(r.chiplet_compute_dynamic_energies_j[1], 0)
        self.assertAlmostEqual(r.chiplet_static_power_w, 2*(.15+.03))
        self.assertAlmostEqual(r.static_energy_j, (2*(.15+.03)+.04+.02)*.002)
        self.assertAlmostEqual(r.compute_dynamic_energy_j, .85*.75*.001)

    def test_waiting_does_not_count_as_active_compute(self):
        a, b = self.core(), self.core(observation_window_s=.004)
        self.assertEqual(a.compute_dynamic_energy_j, b.compute_dynamic_energy_j)
        self.assertEqual(a.chiplet_active_times_s, b.chiplet_active_times_s)
        self.assertAlmostEqual(b.static_energy_j, 2*a.static_energy_j)
        self.assertLess(b.power_avg_batch1_w, a.power_avg_batch1_w)

    def test_mapping_efficiency_changes_active_time_and_energy(self):
        a, b = self.core(), self.core(compute_efficiencies=(.5, 1.))
        self.assertAlmostEqual(b.chiplet_active_times_s[0], 2*a.chiplet_active_times_s[0])
        self.assertAlmostEqual(b.compute_dynamic_energy_j, 2*a.compute_dynamic_energy_j)

    def test_active_times_match_latency_group_compute_not_group_service(self):
        r = self.evaluate()
        for t, compute_ns in zip(r.chiplet_active_times_s, r.e2e_group_compute_times_ns):
            self.assertAlmostEqual(t, compute_ns/1e9, places=14)
        self.assertLess(sum(r.chiplet_active_times_s), r.power_observation_window_s)

    def test_longer_physical_links_change_static_power(self):
        cfg = replace(self.cfg, chiplet=replace(self.cfg.chiplet, spacing_mm=.30))
        a, b = self.evaluate(), self.evaluate(cfg=cfg)
        self.assertAlmostEqual(b.link_static_power_w-a.link_static_power_w, .15*.005)
        self.assertEqual(a.compute_dynamic_energy_j, b.compute_dynamic_energy_j)
        self.assertEqual(a.link_dynamic_energy_j, b.link_dynamic_energy_j)  # same bits/hops

    def test_zero_dynamic_coefficients_give_static_average(self):
        cfg = replace(self.cfg, power=replace(self.cfg.power, chiplet_peak_dynamic_w=0,
                                             link_dynamic_pj_per_bit=0))
        r = self.evaluate(cfg=cfg)
        self.assertEqual(r.compute_dynamic_energy_j, 0)
        self.assertEqual(r.link_dynamic_energy_j, 0)
        self.assertAlmostEqual(r.total_power_w, r.static_power_w)

    def test_constraints_use_average_power_and_ignore_legacy_diagnostic(self):
        r = self.evaluate()
        limit = (r.total_power_w+r.power_fixed_utilization_w)/2
        p = make_preference_profile(max_power_w=limit)
        self.assertLess(r.total_power_w, limit)
        self.assertTrue(score_result(r, p).admissible)
        a = score_result(r, p)
        b = score_result(replace(r, power_fixed_utilization_w=1e9, achieved_fps=1e9), p)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a.power_ratio, r.total_power_w/limit)

    def test_throughput_changes_do_not_change_power_or_search(self):
        cfg = replace(self.cfg, max_chiplets=3)
        p = make_preference_profile(cfg=cfg)
        a = q_learning_search(self.model, cfg, p, evaluation_budget=10, max_episodes=2000, seed=3)
        original = evaluator.evaluate_with_rapidchiplet
        def changed(*args, **kwargs):
            return replace(original(*args, **kwargs), network_limited_fps=.00001)
        with patch.object(evaluator, 'evaluate_with_rapidchiplet', side_effect=changed):
            b = q_learning_search(self.model, cfg, p, evaluation_budget=10, max_episodes=2000, seed=3)
        self.assertEqual(a.best_state, b.best_state)
        self.assertEqual(a.best_reward, b.best_reward)
        self.assertEqual(a.best_candidate.total_power_w, b.best_candidate.total_power_w)
        self.assertEqual(a.best_candidate.energy_per_inference_j, b.best_candidate.energy_per_inference_j)
        self.assertNotEqual(a.best_candidate.achieved_fps, b.best_candidate.achieved_fps)

    def test_invalid_windows_and_activity_are_rejected(self):
        for window in (0, -1, math.nan, math.inf):
            with self.subTest(window=window), self.assertRaises(ValueError):
                self.core(observation_window_s=window)
        for changes in ({'assigned_ops':(-1.,0)}, {'compute_efficiencies':(0.,1.)},
                        {'link_dynamic_energy_j':math.nan}, {'observation_window_s':.0001}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.core(**changes)


if __name__ == '__main__':
    unittest.main()
