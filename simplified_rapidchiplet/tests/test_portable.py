import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.rapidchiplet_engine import evaluate_with_rapidchiplet
from simple_rapidchiplet.model import load_models
from simple_rapidchiplet.topology import make_topology
from simple_rapidchiplet.workload import build_pipeline_workload

ROOT=Path(__file__).resolve().parents[1]


class PortableTests(unittest.TestCase):
    def test_default_root_is_portable_and_official_required(self):
        path=ROOT/'configs/defaults.json'
        raw=json.loads(path.read_text(encoding='utf-8'))
        self.assertFalse(Path(raw['rapidchiplet']['root']).is_absolute())
        cfg=load_config(path)
        self.assertEqual(Path(cfg.rapidchiplet.root),ROOT/'.runtime/rapidchiplet')
        self.assertEqual(cfg.rapidchiplet.backend,'official')

    def test_relative_root_resolves_from_config_not_working_directory(self):
        current=Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as folder:
                try:
                    os.chdir(folder)
                    cfg=load_config(ROOT/'configs/defaults.json')
                    self.assertEqual(Path(cfg.rapidchiplet.root),ROOT/'.runtime/rapidchiplet')
                finally:
                    os.chdir(current)
        finally:
            os.chdir(current)

    def test_missing_official_core_never_silently_falls_back(self):
        cfg=load_config(ROOT/'configs/defaults.json')
        cfg=replace(cfg,rapidchiplet=replace(cfg.rapidchiplet,root=str(ROOT/'missing-official-for-test')))
        model=load_models(ROOT/'configs/models.json')['squeezenet1_1']
        workload=build_pipeline_workload(model,2,((0,len(model.blocks),1),))
        topo=make_topology('mesh',1,cfg.chiplet.width_mm,cfg.chiplet.spacing_mm)
        with self.assertRaises(FileNotFoundError):
            evaluate_with_rapidchiplet(topo,workload,cfg,'portable-test')

    def test_downloads_are_pinned_and_no_codex_dependency_in_launcher(self):
        lock=json.loads((ROOT/'packaging/runtime-lock.json').read_text(encoding='utf-8'))
        self.assertEqual(len(lock['rapidchiplet']['commit']),40)
        self.assertEqual(set(f['name'] for f in lock['rapidchiplet']['files']),
                         {'rapidchiplet.py','helpers.py','validation.py','booksim_wrapper.py'})
        for file in lock['rapidchiplet']['files']:
            self.assertIn(lock['rapidchiplet']['commit'],file['url'])
            self.assertEqual(len(file['sha256']),64)
        self.assertEqual(len(lock['python']['sha256']),64)
        for path in (ROOT/'Start GUI.cmd',ROOT/'scripts/run_gui.ps1',ROOT/'scripts/bootstrap_windows.ps1'):
            content=path.read_text(encoding='utf-8')
            self.assertNotIn('.cache\\codex',content)
            self.assertNotIn('C:\\Users\\user',content)


if __name__=='__main__':unittest.main()
