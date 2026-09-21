"""Verify the portable runtime, official engine, four models, GUI API and SVG."""
import argparse
import json
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simple_rapidchiplet.gui_server import Application, make_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=2)
    args = parser.parse_args()
    app = Application(ROOT)
    assert app.cfg.rapidchiplet.backend == 'official'
    assert app.cfg.network.link_bandwidth_bits_per_cycle == 256
    assert Path(app.cfg.rapidchiplet.root).is_relative_to(ROOT)
    server = make_server(app, 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def request(path, body=None):
        req = Request(base+path, data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type':'application/json','X-DSE-Token':app.token})
        with urlopen(req,timeout=60) as response: return response.read()
    try:
        assert b'Chiplet Lab' in request('/')
        config = json.loads(request('/api/config'))
        assert len(config['models']) == 4
        assert config['hardware']['network']['link_bandwidth_bits_per_cycle'] == 256
        data = dict(models=[m['name'] for m in config['models']], preference='latency',
                    limits=dict(power_w=16, area_mm2=800, latency_ms=500),
                    strict=dict(power=True, area=True, latency=False), budget=args.budget, seed=20260919)
        job = json.loads(request('/api/jobs',data))
        deadline = time.monotonic()+600
        while job['status']=='running' and time.monotonic()<deadline:
            time.sleep(.05)
            job = json.loads(request('/api/jobs/'+job['id']))
        assert job['status']=='completed', job
        assert len(job['results'])==4 and not job['errors']
        report = dict(python=sys.version, executable=sys.executable, project=str(ROOT),
                      official_root=app.cfg.rapidchiplet.root, job_id=job['id'],
                      bandwidth_bits_per_cycle=app.cfg.network.link_bandwidth_bits_per_cycle,
                      request=data, models=[])
        for r in job['results']:
            c = r['best_candidate']
            assert c and c['backend']=='official' and r['best_breakdown']['admissible'], r
            assert abs(c['power_avg_batch1_w']-c['total_power_w']) < 1e-12
            assert abs(c['total_power_w']*c['power_observation_window_s']-c['energy_per_inference_j']) < 1e-12
            svg = request('/api/jobs/'+job['id']+'/placement.svg?model='+r['model']+'&event=all')
            doc = ElementTree.fromstring(svg)
            assert len(doc.findall('{http://www.w3.org/2000/svg}rect')) == c['selected_chiplets']
            report['models'].append(dict(model=r['model'],backend=c['backend'],chiplets=c['selected_chiplets'],
                                         latency_ms=c['avg_latency_ns']/1e6, power_w=c['total_power_w'],
                                         area_mm2=c['total_area_mm2'], unique_evaluations=r['unique_evaluations'],
                                         energy_per_inference_j=c['energy_per_inference_j'],
                                         power_fixed_utilization_w=c['power_fixed_utilization_w'],
                                         all_targets_met=r['best_breakdown']['feasible'], svg_verified=True))
        assert json.loads(request('/api/jobs/'+job['id']+'/results.json'))['status']=='completed'
        csv = request('/api/jobs/'+job['id']+'/summary.csv')
        assert b'latency_ms' in csv and b'energy_per_inference_j' in csv and b'power_fixed_utilization_w' in csv
        output = ROOT/'results/portable_smoke.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: isolated Python, official RapidChiplet, four models, GUI, JSON, CSV, SVG.')
        print(output)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


if __name__=='__main__':main()
