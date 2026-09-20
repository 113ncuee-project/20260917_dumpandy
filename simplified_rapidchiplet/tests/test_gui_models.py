import copy
import json
import math
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from xml.etree import ElementTree

from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.model import ModelSpec, Stage, load_models
from simple_rapidchiplet.mapping import mapping_action_is_feasible, build_mapping_plan
from simple_rapidchiplet.communication import build_communication_events, BITS_PER_MIB
from simple_rapidchiplet.workload import build_pipeline_workload
from simple_rapidchiplet.evaluator import evaluate_one, resolve_ppa_weights
from simple_rapidchiplet.preference_dse import make_preference_profile, score_result, q_learning_search, write_search_outputs
from simple_rapidchiplet.gui_server import Application, make_server, validate_request, attach_routes

ROOT = Path(__file__).resolve().parents[1]


class ConstraintsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config(ROOT / 'configs/defaults.json')
        cls.cfg = replace(cls.cfg, max_chiplets=3, rapidchiplet=replace(cls.cfg.rapidchiplet, backend='local'))
        cls.model = ModelSpec('toy', 'test', 'synthetic', .003, .01, (
            Stage('A', .001, .2, (), 'conv', .1, .1, ('conv',)),
            Stage('B', .002, .1, ('A',), 'conv', .2, .1, ('conv',))))
        cls.candidate = evaluate_one(cls.model, 'mesh', 1, cls.cfg,
            workload=build_pipeline_workload(cls.model, 2, ((0,2,1),)))

    def test_metric_switches_are_independent(self):
        p = make_preference_profile(max_power_w=10, max_area_mm2=100, max_latency_ns=1000,
                                    strict_latency=False, strict_area=True, strict_power=False)
        c = replace(self.candidate, avg_latency_ns=1100, total_area_mm2=90, total_power_w=11)
        soft = score_result(c, p)
        self.assertTrue(soft.admissible)
        self.assertFalse(soft.feasible)
        self.assertGreater(soft.penalty, 0)
        self.assertFalse(score_result(replace(c,total_area_mm2=101),p).admissible)
        self.assertFalse(score_result(c,replace(p,strict_latency=True)).admissible)
        self.assertFalse(score_result(c,replace(p,strict_power=True)).admissible)

    def test_soft_bonus_penalty_is_continuous_and_monotone(self):
        p = make_preference_profile('power', max_power_w=1, max_area_mm2=100, max_latency_ns=1e7,
                                    strict_latency=False, strict_area=False, strict_power=False)
        rewards = [score_result(replace(self.candidate,total_power_w=x),p) for x in (.5,.999999,1,1.000001,2,1e30)]
        self.assertEqual([r.reward for r in rewards], sorted((r.reward for r in rewards),reverse=True))
        self.assertAlmostEqual(rewards[1].reward,rewards[3].reward,places=5)
        self.assertGreater(rewards[0].bonus,rewards[4].bonus)
        self.assertGreater(rewards[4].penalty,rewards[0].penalty)
        self.assertTrue(all(r.admissible for r in rewards))
        invalid = score_result(replace(self.candidate,architecture_feasible=False),p)
        self.assertLess(invalid.reward,min(r.reward for r in rewards))
        self.assertFalse(invalid.admissible)
        self.assertFalse(score_result(replace(self.candidate,total_power_w=math.nan),p).admissible)

    def test_hard_rejection_never_delivers_candidate_or_policy(self):
        profile=make_preference_profile(max_power_w=.01)
        result=q_learning_search(self.model,self.cfg,profile,evaluation_budget=10,max_episodes=2000,seed=2)
        self.assertEqual(result.status,'no_admissible_design')
        self.assertIsNone(result.best_candidate)
        self.assertIsNone(result.best_state)
        self.assertIsNone(result.policy_rollout['candidate'])
        self.assertFalse(result.to_dict()['global_optimum_certified'])
        with tempfile.TemporaryDirectory() as tmp:
            files=write_search_outputs(tmp,[result])
            self.assertIsNone(json.loads(files['json'].read_text(encoding='utf-8'))[0]['best_candidate'])
            self.assertIn('no_admissible_design',files['csv'].read_text(encoding='utf-8-sig'))

    def test_soft_archive_uses_reward_and_q_policy_matches_exhaustive_search(self):
        profile=make_preference_profile('latency',max_power_w=1,max_area_mm2=100,max_latency_ns=1e5,
                                        strict_power=False,strict_area=False,strict_latency=False)
        for seed in (1,2,3):
            result=q_learning_search(self.model,self.cfg,profile,evaluation_budget=10,max_episodes=2000,seed=seed)
            self.assertEqual(result.unique_evaluations,result.design_space_size)
            self.assertAlmostEqual(result.best_reward,max(h['reward'] for h in result.history if h['admissible']))
            self.assertTrue(result.policy_rollout['matches_best_reward'])
            self.assertTrue(result.best_breakdown.admissible)

    def test_cancel_stops_training(self):
        with self.assertRaises(InterruptedError):
            q_learning_search(self.model,self.cfg,make_preference_profile(),should_cancel=lambda:True)

    def test_both_evaluator_and_rl_use_moderate_presets(self):
        for name in ('power','latency','area'):
            profile=make_preference_profile(name)
            w=resolve_ppa_weights(name)
            self.assertEqual(sorted(profile.weights),[.2,.2,.6])
            self.assertEqual(profile.weights,(w.latency,w.area,w.power))


class CalibratedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models=load_models(ROOT/'configs/models.json')

    def test_calibrated_shapes_counts_and_real_forward_records(self):
        expected={'resnet50':(25557032,4089184256,18),'resnet18':(11689512,1814073344,10),
                  'mobilenet_v2':(3504872,300774272,20),'squeezenet1_1':(1235496,349151936,10)}
        records=json.loads((ROOT/'validation/model_forward_validation.json').read_text(encoding='utf-8'))
        for report in records:
            name=report['model'];m=self.models[name];params,macs,blocks=expected[name]
            self.assertEqual(report['parameters'],params)
            self.assertEqual(report['conv_linear_macs'],macs)
            self.assertEqual(report['output_shape'],[1,1000])
            self.assertTrue(report['output_finite'] and report['block_forward_matches_full_model'])
            self.assertEqual(len(m.blocks),blocks)
            self.assertAlmostEqual(sum(b.weight_mb for b in m.blocks)*1024**2/4,params)
            self.assertAlmostEqual(sum(b.macs_g for b in m.blocks)*1e9,macs,places=4)
            self.assertTrue(all(b.weight_mb>0 for b in m.blocks))
            for a,b in zip(m.blocks,m.blocks[1:]):
                self.assertAlmostEqual(a.output_mb,b.input_mb)

    def test_depthwise_no_dense_input_broadcast_or_partial_reduction(self):
        model=self.models['mobilenet_v2']
        block=model.blocks[1] # first IR: DW then PW, no expansion
        self.assertEqual(block.input_partition,'channel')
        isolated=replace(model,stages=(replace(block,depends_on=()),))
        events=build_communication_events(isolated,((0,1,2),),('output_channel',))
        distribution=[e for e in events if e['kind']=='input_distribution']
        self.assertAlmostEqual(sum(e['traffic_bits'] for e in distribution)/BITS_PER_MIB,block.input_mb/2)
        inner=[e for e in events if e['kind']=='internal_redistribution']
        self.assertEqual(len(inner),1) # DW -> dense PW all-gather, each half once
        self.assertAlmostEqual(inner[0]['traffic_bits']/BITS_PER_MIB,block.internal_activation_mb[0])
        self.assertFalse(any(e['kind']=='partial_output_reduction' for e in events))
        self.assertFalse(mapping_action_is_feasible(model,1,2,2,'input_channel',sram_mb=16))

    def test_expansion_to_depthwise_stays_local_then_gathers_for_projection(self):
        model=self.models['mobilenet_v2'];block=model.blocks[2]
        isolated=replace(model,stages=(replace(block,depends_on=()),))
        events=build_communication_events(isolated,((0,1,2),),('output_channel',))
        self.assertEqual(block.input_partition,'replicated')
        self.assertEqual(len(block.internal_activation_mb),1)
        self.assertEqual(sum(e['kind']=='internal_redistribution' for e in events),1)
        self.assertGreater(block.peak_activation_mb,block.internal_activation_mb[0])
        plan=build_mapping_plan(isolated,((0,1,2),),('output_channel',),sram_mb=16)
        self.assertGreaterEqual(plan.groups[0].memory_per_chiplet_mb,2*block.peak_activation_mb)

    def test_fire_concat_is_local_and_unsupported_parallelism_is_masked(self):
        model=self.models['squeezenet1_1']
        for i,b in enumerate(model.blocks):
            if b.block_type=='fire':
                self.assertFalse(mapping_action_is_feasible(model,i,i+1,2,'output_channel',sram_mb=16))
                self.assertFalse(mapping_action_is_feasible(model,i,i+1,2,'input_channel',sram_mb=16))
                self.assertTrue(mapping_action_is_feasible(model,i,i+1,1,'single',sram_mb=16))
        self.assertEqual(build_communication_events(model,((0,len(model.blocks),1),),('single',)),())


class GuiApiTests(unittest.TestCase):
    def setUp(self):
        self.app=Application(ROOT)
        self.data=dict(models=['squeezenet1_1'],preference='balanced',limits=dict(power_w=16,area_mm2=800,latency_ms=500),
                       strict=dict(power=True,area=True,latency=True),budget=1,seed=7)
        self.server=make_server(self.app,0)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        if self.app.active_job:self.app.cancel(self.app.active_job)
        self.server.shutdown();self.server.server_close();self.worker.join(timeout=2)

    def request(self,path,body=None,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-DSE-Token']=self.app.token
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urlopen(req,timeout=15) as response:return response.read()

    def wait_job(self,job_id):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            result=json.loads(self.request('/api/jobs/'+job_id))
            if result['status']!='running':return result
            time.sleep(.05)
        self.fail('GUI search did not finish in time')

    def test_http_search_actual_result_routes_and_downloads(self):
        config=json.loads(self.request('/api/config'))
        self.assertEqual(len(config['models']),4)
        self.assertIn('Power',self.request('/').decode())
        # ResNet18 warm baseline necessarily has physical links under 16MiB.
        data=copy.deepcopy(self.data);data['models']=['resnet18'];data['strict']['latency']=False
        started=json.loads(self.request('/api/jobs',data))
        done=self.wait_job(started['id'])
        self.assertEqual(done['status'],'completed',done['errors'])
        r=done['results'][0];c=r['best_candidate']
        self.assertTrue(r['best_breakdown']['admissible'])
        graph=c['connection_graph'];physical={frozenset((e['source'],e['target'])) for e in graph['physical_links']}
        self.assertEqual(len(graph['nodes']),c['selected_chiplets'])
        self.assertTrue(graph['routed_traffic'])
        for flow in graph['routed_traffic']:
            self.assertEqual(flow['path'][0],flow['source']);self.assertEqual(flow['path'][-1],flow['target'])
            self.assertTrue(all(frozenset(pair) in physical for pair in zip(flow['path'],flow['path'][1:])))
        export=json.loads(self.request('/api/jobs/'+done['id']+'/results.json'))
        self.assertEqual(export['results'][0]['best_candidate']['connection_graph'],graph)
        self.assertIn('resnet18',self.request('/api/jobs/'+done['id']+'/summary.csv').decode('utf-8-sig'))
        svg=ElementTree.fromstring(self.request('/api/jobs/'+done['id']+'/placement.svg?model=resnet18&event=all'))
        ns={'s':'http://www.w3.org/2000/svg'}
        self.assertEqual(len(svg.findall('s:rect',ns)),c['selected_chiplets'])
        self.assertEqual(len(svg.findall('s:line',ns)),len(graph['physical_links']))
        self.assertEqual(len(svg.findall('s:polyline',ns)),len(graph['routed_traffic']))
        for rect,node in zip(svg.findall('s:rect',ns),graph['nodes']):
            self.assertEqual(float(rect.get('x')),node['x'])
            self.assertEqual(float(rect.get('y')),node['y'])
            self.assertEqual(float(rect.get('width')),c['effective_hardware']['chiplet']['width_mm'])

    def test_http_strict_no_result_and_soft_result(self):
        data=copy.deepcopy(self.data);data['limits']['power_w']=.1
        first=self.wait_job(json.loads(self.request('/api/jobs',data))['id'])
        self.assertEqual(first['results'][0]['status'],'no_admissible_design')
        self.assertIsNone(first['results'][0]['best_candidate'])
        data['strict']['power']=False
        second=self.wait_job(json.loads(self.request('/api/jobs',data))['id'])
        self.assertIsNotNone(second['results'][0]['best_candidate'])
        self.assertGreater(second['results'][0]['best_breakdown']['penalty'],0)

    def test_bad_inputs_csrf_and_nonwhitelisted_files_rejected(self):
        for mutation in ({'models':[]},{'budget':1.5},{'seed':-1},{'strict':{'power':'false','area':True,'latency':True}},
                         {'limits':{'power_w':float('nan'),'area_mm2':1,'latency_ms':1}},{'target_fps':30}):
            with self.assertRaises(ValueError):validate_request(dict(self.data,**mutation),self.app.models)
        with self.assertRaises(HTTPError) as error:self.request('/api/jobs',self.data,token=False)
        self.assertEqual(error.exception.code,403)
        with self.assertRaises(HTTPError) as error:self.request('/configs/defaults.json')
        self.assertEqual(error.exception.code,404)


if __name__=='__main__':unittest.main()
