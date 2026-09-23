import json
import math
import unittest
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.model import ModelSpec, Stage, load_models
from simple_rapidchiplet.workload import build_pipeline_workload
from simple_rapidchiplet.evaluator import evaluate_one, _score_results, resolve_ppa_weights
from simple_rapidchiplet.preference_dse import (DesignState, EvaluationOracle, make_preference_profile,
                                               score_result, q_learning_search, legal_actions)
from simple_rapidchiplet import rapidchiplet_engine as engine
from simple_rapidchiplet.communication import redistribute
from simple_rapidchiplet.routing import shortest_paths_for_pairs
from simple_rapidchiplet.topology import make_topology
from simple_rapidchiplet.mapping import build_mapping_plan
from simple_rapidchiplet.block_extractor import validate_block_graph

ROOT = Path(__file__).resolve().parents[1]
BITS = 8 * 1024**2


def toy():
    return ModelSpec('toy', 'test', 'synthetic', .003, .01, (
        Stage('A', .001, 8., (), 'Conv', 1., .1, ('Conv',)),
        Stage('B', .002, 2., ('A',), 'Conv', 8., .1, ('Conv',)),
    ))


def flows(workload, kind=None):
    result = {}
    for event in workload.communication_events:
        if kind is None or event['kind'] == kind:
            for f in event['flows']:
                key = (f['source'], f['target'])
                result[key] = result.get(key, 0.) + f['bits']/BITS
    return result


class PpaTrafficRlTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(ROOT/'configs/defaults.json')
        # Synthetic 8 MiB tensors need > 16 MiB for input + two live buffers.
        self.cfg = replace(self.cfg, chiplet=replace(self.cfg.chiplet, sram_mb=64.),
                           rapidchiplet=replace(self.cfg.rapidchiplet, backend='local'))
        self.model = toy()

    def test_one_to_many_oc_copies_full_tensor(self):
        w = build_pipeline_workload(self.model, 2, ((0,1,1),(1,2,3)),
                                    mapping_strategies=('single','output_channel'))
        self.assertEqual(flows(w, 'dependency_transfer'), {(0,1):8.,(0,2):8.,(0,3):8.})
        self.assertEqual(w.total_traffic_bits_per_inference/BITS,24.)

    def test_one_to_many_ic_scatters_shards_then_reduces(self):
        w = build_pipeline_workload(self.model, 2, ((0,1,1),(1,2,2)),
                                    mapping_strategies=('single','input_channel'))
        self.assertEqual(flows(w, 'dependency_transfer'), {(0,1):4.,(0,2):4.})
        self.assertEqual(flows(w, 'partial_output_reduction'), {(2,1):2.})

    def test_many_to_one_oc_gathers_each_shard_once(self):
        w=build_pipeline_workload(self.model,2,((0,1,2),(1,2,1)),mapping_strategies=('output_channel','single'))
        self.assertEqual(flows(w,'dependency_transfer'),{(0,2):4.,(1,2):4.})
        # Root input is 1 MiB, not max(input, output)=8; no old chain output.
        self.assertEqual(flows(w,'input_distribution'),{(0,1):1.})
        self.assertEqual(w.total_traffic_bits_per_inference/BITS,9.)

    def test_many_to_one_ic_only_reduction_owner_sends_next(self):
        w=build_pipeline_workload(self.model,2,((0,1,2),(1,2,1)),mapping_strategies=('input_channel','single'))
        self.assertEqual(flows(w,'partial_output_reduction'),{(1,0):8.})
        self.assertEqual(flows(w,'dependency_transfer'),{(0,2):8.})

    def test_many_to_many_ownership_not_uniform_pair_division(self):
        oc=build_pipeline_workload(self.model,2,((0,1,2),(1,2,2)),mapping_strategies=('output_channel','output_channel'))
        self.assertEqual(flows(oc,'dependency_transfer'),{(0,2):4.,(1,2):4.,(0,3):4.,(1,3):4.})
        ic=build_pipeline_workload(self.model,2,((0,1,2),(1,2,2)),mapping_strategies=('output_channel','input_channel'))
        self.assertEqual(flows(ic,'dependency_transfer'),{(0,2):4.,(1,3):4.})

    def test_multiblock_group_preserves_internal_redistribution(self):
        w=build_pipeline_workload(self.model,2,((0,2,2),),mapping_strategies=('output_channel',))
        self.assertEqual(flows(w,'dependency_transfer'),{(0,1):4.,(1,0):4.})

    def test_branch_fanout_and_join_keep_distinct_tensors(self):
        m=replace(self.model, macs_g=.004, stages=(self.model.blocks[0],
            Stage('B',.001,2.,('A',),operators=('Conv',)),
            Stage('C',.001,3.,('A',),operators=('Conv',)),
            Stage('D',.001,5.,('B','C'),input_mb=5.,operators=('Concat',))))
        w=build_pipeline_workload(m,2,((0,1,1),(1,2,1),(2,3,1),(3,4,1)))
        self.assertEqual(flows(w),{(0,1):8.,(0,2):8.,(1,3):2.,(2,3):3.})
        result=evaluate_one(m,'mesh',4,self.cfg,workload=w)
        tasks={t['name']:t for t in result.schedule['tasks']}
        self.assertGreaterEqual(tasks['D']['start_cycles'],max(tasks['B']['finish_cycles'],tasks['C']['finish_cycles']))

    def test_join_critical_path_uses_data_arrival_not_compute_finish(self):
        m=replace(self.model,stages=(self.model.blocks[0],
            Stage('B',.001,8.,('A',),input_mb=8.,operators=('Conv',)),
            Stage('C',.002,.1,('A',),input_mb=8.,operators=('Conv',)),
            Stage('D',.001,8.1,('B','C'),input_mb=8.1,operators=('Concat',))))
        w=build_pipeline_workload(m,2,((0,1,1),(1,2,1),(2,3,1),(3,4,1)))
        result=evaluate_one(m,'mesh',4,self.cfg,workload=w)
        tasks={t['name']:t for t in result.schedule['tasks']}
        self.assertGreater(tasks['C']['finish_cycles'],tasks['B']['finish_cycles'])
        self.assertEqual(result.schedule['critical_path'],['A','B','D'])

    def test_e2e_rapid_and_routes_have_identical_flows(self):
        w=build_pipeline_workload(self.model,2,((0,1,2),(1,2,1)),mapping_strategies=('output_channel','single'))
        result=evaluate_one(self.model,'mesh',3,self.cfg,workload=w)
        self.assertAlmostEqual(sum(e['traffic_bits'] for e in result.e2e_boundary_timings),w.total_traffic_bits_per_inference)
        topology=make_topology('mesh',3,self.cfg.chiplet.width_mm,self.cfg.chiplet.spacing_mm)
        inputs=engine.build_effective_inputs(topology,w,self.cfg)
        self.assertEqual(inputs['traffic_by_chiplet'],w.traffic_bits_per_inference)
        for pair,path in shortest_paths_for_pairs(topology,w.traffic_bits_per_inference).items():
            self.assertEqual((path[0],path[-1]),pair)
            for a,b in zip(path,path[1:]):
                self.assertIn(tuple(sorted((a,b))),topology.edge_lengths())
        self.assertEqual(sum(e['traffic_bits'] for e in result.e2e_boundary_timings if e['kind']=='dependency_transfer'),8*BITS)

    def test_invalid_ownership_is_rejected(self):
        with self.assertRaises(ValueError):
            redistribute(((0,0.,.5),),((1,0.,1.),),1.)
        # Total length alone would miss an overlap and a compensating gap.
        with self.assertRaises(ValueError):
            redistribute(((0,0.,.5),(1,.25,.75)),((2,0.,1.),),1.)
        with self.assertRaises(ValueError):
            redistribute(((0,0.,1.),),((1,0.,1.),),math.nan)

    def test_ic_inner_layers_and_identity_are_not_erased_by_fusion(self):
        block=Stage('residual',.001,8.,(),input_mb=8.,operators=('Conv','Conv','Add'),
                    internal_activation_mb=(4.,),residual_shortcut=True)
        m=replace(self.model,stages=(block,))
        w=build_pipeline_workload(m,2,((0,1,2),),mapping_strategies=('input_channel',))
        self.assertEqual(flows(w,'input_distribution'),{(0,1):4.})
        self.assertEqual(flows(w,'partial_output_reduction'),{(1,0):12.})
        self.assertEqual(flows(w,'internal_redistribution'),{(0,1):2.})
        self.assertEqual(flows(w,'identity_shortcut_gather'),{})  # leader retains the root input
        self.assertEqual(w.total_traffic_bits_per_inference/BITS,18.)

    def test_ic_identity_gather_depends_on_where_input_is_resident(self):
        m=replace(self.model,stages=(self.model.blocks[0],
            replace(self.model.blocks[1],residual_shortcut=True)))
        external=build_pipeline_workload(m,2,((0,1,1),(1,2,2)),
                                         mapping_strategies=('single','input_channel'))
        self.assertEqual(flows(external,'identity_shortcut_gather'),{(2,1):4.})
        same_group=build_pipeline_workload(m,2,((0,2,2),),mapping_strategies=('input_channel',))
        self.assertEqual(flows(same_group,'identity_shortcut_gather'),{})

    def test_ic_projection_has_its_own_reduction(self):
        block=Stage('projection',.001,8.,(),input_mb=2.,operators=('Conv','Projection','Add'),
                    projection_shortcut=True,residual_shortcut=True)
        w=build_pipeline_workload(replace(self.model,stages=(block,)),2,((0,1,2),),
                                  mapping_strategies=('input_channel',))
        self.assertEqual(flows(w,'partial_output_reduction'),{(1,0):16.})
        self.assertEqual(flows(w,'identity_shortcut_gather'),{})

    def test_stem_memory_accounts_for_tensor_before_pool(self):
        m=load_models(ROOT/'configs/models.json')['resnet50']
        stem=replace(m,stages=m.blocks[:1])
        self.assertFalse(build_mapping_plan(stem,((0,1,1),),sram_mb=5.).feasible)
        self.assertTrue(build_mapping_plan(stem,((0,1,1),),sram_mb=16.).feasible)

    def test_bad_model_sizes_and_duplicate_dependencies_fail(self):
        for block in (replace(self.model.blocks[1],input_mb=math.nan),
                      replace(self.model.blocks[1],depends_on=('A','A'))):
            with self.assertRaises(ValueError):
                validate_block_graph(replace(self.model,stages=(self.model.blocks[0],block)))

    def test_default_hardware_preserves_supplied_0815_values(self):
        cfg=load_config(ROOT/'configs/defaults.json')
        self.assertEqual((cfg.power.chiplet_static_w,cfg.power.chiplet_peak_dynamic_w,cfg.power.phy_w),(.15,.85,.03))
        self.assertEqual((cfg.power.link_static_w_per_mm,cfg.power.link_dynamic_pj_per_bit),(.005,.5))
        self.assertEqual((cfg.chiplet.frequency_hz,cfg.network.link_bandwidth_bits_per_cycle),(200000000,256.))
        self.assertEqual((cfg.network.link_latency_base_cycles,cfg.network.link_latency_cycles_per_mm),(1.,.25))
        self.assertEqual(cfg.chiplet.sram_mb,16.)
        self.assertEqual(cfg.ppa,dict(max_latency_ns=500000000.,max_area_mm2=800.,max_power_w=16.))

    def test_old_fps_input_is_rejected_and_reports_have_no_fps_target(self):
        from simple_rapidchiplet.report import write_outputs
        data=json.loads((ROOT/'configs/defaults.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'old.json'
            data['evaluation']['target_fps']=30
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'FPS is a reported metric'):
                load_config(path)
            result=evaluate_one(self.model,'mesh',1,self.cfg,
                                workload=build_pipeline_workload(self.model,2,((0,2,1),)))
            self.assertTrue(all(write_outputs(directory,[result],[result]).values()))
            self.assertNotIn('target_fps',(Path(directory)/'summary.csv').read_text())
            self.assertNotIn('FPS Bonus',(Path(directory)/'report.html').read_text())

    def test_cache_distinguishes_strategies_and_preserves_result_metadata(self):
        profile=make_preference_profile(cfg=self.cfg)
        oracle=EvaluationOracle(self.model,self.cfg,profile,16)
        oc=DesignState('balanced',2,3,((0,1,2),(1,2,1)),mapping_strategies=('output_channel','single'))
        ic=replace(oc,mapping_strategies=('input_channel','single'))
        a,b=oracle.evaluate(oc),oracle.evaluate(ic)
        self.assertEqual(oracle.unique_evaluations,2)
        self.assertIs(oracle.evaluate(ic),b)
        self.assertEqual(b.mapping_plan['groups'][0]['strategy'],'input_channel')
        self.assertNotEqual(a.avg_latency_ns,b.avg_latency_ns)

    def test_fps_never_changes_reward_or_ppa_score(self):
        w=build_pipeline_workload(self.model,2,((0,2,1),))
        a=evaluate_one(self.model,'mesh',1,self.cfg,workload=w)
        b=replace(a,achieved_fps=.0001,network_limited_fps=9999999)
        profile=make_preference_profile(cfg=self.cfg)
        self.assertEqual(score_result(a,profile),score_result(b,profile))
        scored=_score_results([a,b],resolve_ppa_weights('balanced'))
        self.assertEqual(scored[0].ppa_score,scored[1].ppa_score)
        self.assertFalse(hasattr(self.cfg,'target_fps'))
        self.assertFalse(hasattr(profile,'min_fps'))

    def test_feasible_reward_always_beats_infeasible_even_large_cost(self):
        a=evaluate_one(self.model,'mesh',1,self.cfg,workload=build_pipeline_workload(self.model,2,((0,2,1),)))
        p=make_preference_profile(cfg=self.cfg)
        costly=replace(a,avg_latency_ns=1e18)
        invalid=replace(a,architecture_feasible=False,architecture_violations=('invalid',))
        self.assertGreater(score_result(costly,p).reward,score_result(invalid,p).reward)
        self.assertFalse(score_result(replace(a,total_power_w=math.nan),p).feasible)

    def test_small_space_q_policy_matches_independent_enumeration_multiseed(self):
        cfg=replace(self.cfg,max_chiplets=3)
        p=make_preference_profile('latency',cfg=cfg)
        designs=[(((0,2,1),),('single',))]
        for n in (2,3):
            for strategy in ('output_channel','input_channel'):
                designs.append((((0,2,n),),(strategy,)))
        designs.append((((0,1,1),(1,2,1)),('single','single')))
        for strategy in ('output_channel','input_channel'):
            designs.extend([(((0,1,1),(1,2,2)),('single',strategy)),
                            (((0,1,2),(1,2,1)),(strategy,'single'))])
        expected=max(score_result(evaluate_one(self.model,'mesh',sum(g[2] for g in groups),cfg,
            workload=build_pipeline_workload(self.model,2,groups,mapping_strategies=strategies)),p).reward
            for groups,strategies in designs)
        for seed in (1,2,3,4,5):
            result=q_learning_search(self.model,cfg,p,evaluation_budget=10,max_episodes=2000,seed=seed)
            self.assertEqual(result.design_space_size,10)
            self.assertEqual(result.unique_evaluations,10)
            self.assertEqual(result.stopping_reason,'design_space_exhausted')
            self.assertAlmostEqual(result.best_reward,expected)
            self.assertAlmostEqual(result.policy_rollout['reward']['reward'],expected)
            self.assertTrue(result.q_table)
            self.assertIn('mapping_strategies',result.history[0])

    def test_no_feasible_mapping_and_invalid_search_settings_fail_clearly(self):
        cfg=replace(self.cfg,max_chiplets=1,chiplet=replace(self.cfg.chiplet,sram_mb=.01))
        with self.assertRaisesRegex(ValueError,'No complete mapping'):
            q_learning_search(self.model,cfg,make_preference_profile(cfg=cfg))
        for opts in (dict(evaluation_budget=0),dict(max_episodes=0),dict(discount=.95),dict(epsilon_decay=1.1)):
            with self.assertRaises(ValueError):
                q_learning_search(self.model,self.cfg,make_preference_profile(),**opts)

    def test_q_values_drive_exploitation_and_episode_limit_is_reported(self):
        result=q_learning_search(self.model,self.cfg,make_preference_profile(cfg=self.cfg),
            evaluation_budget=10,max_episodes=3,epsilon_start=0.,epsilon_end=0.,seed=7)
        self.assertEqual(result.unique_evaluations,1)
        self.assertEqual(result.stopping_reason,'episode_limit')
        self.assertGreater(sum(h['exploit_steps'] for h in result.history),0)
        self.assertTrue(result.policy_rollout['matches_best_reward'])
        self.assertFalse(result.to_dict()['global_optimum_certified'])

    def test_resnet_metadata_and_mask_have_physical_bounds(self):
        m=load_models(ROOT/'configs/models.json')['resnet50']
        self.assertAlmostEqual(m.macs_g,4.089184256)
        self.assertAlmostEqual(sum(b.weight_mb for b in m.blocks),97.49234008789062)
        self.assertEqual(m.blocks[0].output_mb,.765625)
        self.assertEqual(m.blocks[1].output_mb,3.0625)
        actions=legal_actions(DesignState('balanced'),len(m.blocks),16,m,16.)
        self.assertTrue(actions)
        self.assertTrue(all(a.mapping_strategy!='spatial' for a in actions))
        self.assertFalse(any(a.group_length==1 and a.chiplets==2 and a.mapping_strategy=='input_channel' for a in actions))

    def test_official_and_local_use_same_power_bandwidth_and_geometry(self):
        try:
            rc=engine._load_rapidchiplet_module(self.cfg.rapidchiplet.root)
        except (ImportError,FileNotFoundError) as exc:
            self.skipTest(str(exc))
        w=build_pipeline_workload(self.model,2,((0,1,1),(1,2,1)))
        official=replace(self.cfg,rapidchiplet=replace(self.cfg.rapidchiplet,backend='official'))
        seen=[]
        original=rc.rapidchiplet
        def capture(inputs,intermediates,*args,**kwargs):
            out=original(inputs,intermediates,*args,**kwargs)
            seen.append((inputs,intermediates.copy()))
            return out
        with patch.object(rc,'rapidchiplet',side_effect=capture):
            a=evaluate_one(self.model,'mesh',2,official,workload=w)
            changed=replace(official,network=replace(official.network,link_bandwidth_bits_per_cycle=512.),
                            power=replace(official.power,chiplet_static_w=.25))
            b=evaluate_one(self.model,'mesh',2,changed,workload=w)
        local=evaluate_one(self.model,'mesh',2,self.cfg,workload=w)
        self.assertEqual(set(seen[0][1]['link_bandwidths'].values()),{256.})
        self.assertEqual(set(seen[1][1]['link_bandwidths'].values()),{512.})
        self.assertAlmostEqual(a.chiplet_fixed_utilization_power_w,2*.8175)
        self.assertAlmostEqual(b.power_fixed_utilization_w-a.power_fixed_utilization_w,.2)
        self.assertAlmostEqual(b.network_limited_fps,2*a.network_limited_fps)
        self.assertGreater(a.e2e_communication_serialization_ns, 0)
        self.assertAlmostEqual(b.e2e_communication_serialization_ns,
                               a.e2e_communication_serialization_ns / 2)
        for attr in ('total_power_w','network_limited_fps','rapid_avg_latency_ns','total_area_mm2'):
            self.assertAlmostEqual(getattr(a,attr),getattr(local,attr),msg=attr)
        self.assertFalse(seen[0][0]['packaging']['is_active'])


if __name__=='__main__':
    unittest.main()
