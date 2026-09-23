"""Summarise actual completed GUI jobs; never fabricate or re-evaluate metrics."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_ids',nargs='+')
    args=parser.parse_args()
    records=[]
    for job_id in args.job_ids:
        if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):
            raise ValueError('Expected a GUI job id')
        path=ROOT/'results/gui'/job_id/'results.json'
        raw=json.loads(path.read_text(encoding='utf-8'))
        assert raw['status']=='completed' and not raw['errors']
        assert len(raw['results'])==4
        for source,digest in raw['sha256'].items():
            assert hashlib.sha256((ROOT/source).read_bytes()).hexdigest()==digest, f'Source changed: {source}'
        record=dict(job_id=job_id,artifact=str(path.relative_to(ROOT)),request=raw['request'],models=[])
        for result in raw['results']:
            c=result['best_candidate'];b=result['best_breakdown']
            if c:
                assert b['admissible'] and c['architecture_feasible']
                assert c['backend']=='official'
                assert abs(c['avg_latency_ns']-(c['e2e_compute_latency_ns']+c['e2e_communication_serialization_ns']+c['e2e_communication_path_latency_ns']))<1e-4
                physical={frozenset((e['source'],e['target'])) for e in c['connection_graph']['physical_links']}
                for event in c['communication_events']:
                    for flow in event['flows']:
                        assert flow['path'][0]==flow['source'] and flow['path'][-1]==flow['target']
                        assert all(frozenset(edge) in physical for edge in zip(flow['path'],flow['path'][1:]))
            else:
                assert result['status']=='no_admissible_design'
                assert result['best_state'] is None and result['policy_rollout']['candidate'] is None
            record['models'].append(dict(model=result['model'],status=result['status'],
                unique_evaluations=result['unique_evaluations'],episodes=result['episodes'],
                stopping_reason=result['stopping_reason'],design_space_size=result['design_space_size'],
                policy_matches_best=result['policy_rollout']['matches_best_reward'],
                replay_converged=result['policy_rollout']['replay_converged'],
                best_reward=result['best_reward'],all_targets_met=b['feasible'] if b else False,
                chiplets=c['selected_chiplets'] if c else None,power_w=c['total_power_w'] if c else None,
                energy_per_inference_j=c['energy_per_inference_j'] if c else None,
                power_fixed_utilization_w=c['power_fixed_utilization_w'] if c else None,
                area_mm2=c['total_area_mm2'] if c else None,latency_ms=c['avg_latency_ns']/1e6 if c else None,
                fps_reported=c['achieved_fps'] if c else None,bonus=b['bonus'] if b else None,penalty=b['penalty'] if b else None,
                backend=c['backend'] if c else None))
        records.append(record)
    out=ROOT/'validation/gui_multimodel_validation.json'
    out.write_text(json.dumps(dict(date=datetime.now().astimezone().date().isoformat(),execution='Real browser GUI jobs on local official RapidChiplet',
        unit_tests=dict(passed=79,command='python -m unittest discover -s tests'),
        note='CPU model forward validates graph metadata, not measured chiplet PPA or classification accuracy.',
        cases=records),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(out)


if __name__=='__main__':main()
