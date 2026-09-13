"""Compare portable phone inference against the frozen Windows implementation."""
import csv
import gzip
import hashlib
import json
import pickle
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'data/labeled/type-conditioned-sensor-endpoint-ranker.pkl'
BUNDLE=ROOT/'mobile/android/app/src/main/assets/models/endpoint-portable.json.gz'

class PortableEndpointTests(unittest.TestCase):
    def test_export_is_bound_to_frozen_source(self):
        obj=json.loads(gzip.decompress(BUNDLE.read_bytes()))
        self.assertEqual(obj['source_sha256'],hashlib.sha256(MODEL.read_bytes()).hexdigest())
        self.assertEqual(len(obj['models']),4)
        self.assertTrue(all(len(x['fold_estimators'])==12 for x in obj['models'].values()))

    def test_all_twelve_recordings_match_python(self):
        from auto_titrator.type_conditioned_sensor_live_model import predict_type_conditioned_sensor_equivalence
        artifact=pickle.loads(MODEL.read_bytes())
        keys=['time_s','injected_volume_ml','visible_H_mean','visible_S_mean','visible_V_mean','thermal_raw_roi_p50','thermal_raw_roi_p95']
        cases=[];expected=[]
        for p in sorted((ROOT/'머신러닝용 파일모음').glob('*.csv')):
            with p.open(encoding='utf-8-sig',newline='') as stream: raw=list(csv.DictReader(stream))
            rows=[{k:r.get(k,'') for k in keys} for r in raw]
            cases.append({'name':p.name,'type':raw[0]['titration_type'],'rows':rows})
            expected.append(predict_type_conditioned_sensor_equivalence(artifact,rows,raw[0]['titration_type']))
        self.assertEqual(len(cases),12)
        run=subprocess.run(['node',str(ROOT/'tests/js/run_portable_endpoint.js'),str(BUNDLE)],input=json.dumps(cases),text=True,capture_output=True,timeout=180)
        self.assertEqual(run.returncode,0,run.stderr)
        actual=json.loads(run.stdout)
        for case,want,got in zip(cases,expected,actual):
            with self.subTest(run=case['name']):
                self.assertAlmostEqual(got['result']['predicted_equivalence_volume_ml'],want['predicted_equivalence_volume_ml'],places=6)
                self.assertAlmostEqual(got['result']['predicted_equivalence_confidence'],want['predicted_equivalence_confidence'],places=6)
                self.assertEqual(got['result']['candidate_index'],want['candidate_index'])
        self.assertEqual(len(actual),12)

    def test_dense_rows_and_truth_columns_do_not_change_sensor_inference(self):
        from auto_titrator.type_conditioned_sensor_live_model import predict_type_conditioned_sensor_equivalence, resample_sensor_rows_by_volume
        artifact=pickle.loads(MODEL.read_bytes())
        cases=[]; expected=[]; types=set()
        for p in sorted((ROOT/'머신러닝용 파일모음').glob('*.csv')):
            with p.open(encoding='utf-8-sig',newline='') as stream: rows=list(csv.DictReader(stream))
            kind=rows[0]['titration_type']
            if kind in types: continue
            types.add(kind)
            dense,_=resample_sensor_rows_by_volume(rows,0.04)
            for i,r in enumerate(dense):
                r['time_s']=i*0.04
                r['sample_concentration_M']=999999
                r['theoretical_equivalence_volume_ml']=0.00001
                r['progress']=0.99
            cases.append({'name':p.name,'type':kind,'rows':dense})
            expected.append(predict_type_conditioned_sensor_equivalence(artifact,dense,kind))
        result=subprocess.run(['node',str(ROOT/'tests/js/run_portable_endpoint.js'),str(BUNDLE)],input=json.dumps(cases),text=True,capture_output=True,timeout=180)
        self.assertEqual(result.returncode,0,result.stderr)
        for want,got in zip(expected,json.loads(result.stdout)):
            self.assertAlmostEqual(want['predicted_equivalence_volume_ml'],got['result']['predicted_equivalence_volume_ml'],places=6)
            self.assertEqual(want['candidate_index'],got['result']['candidate_index'])

    def test_guard_and_no_theory_fallback(self):
        code="""
        const assert=require('node:assert/strict');
        const e=require('./website/portable-endpoint.js');
        assert.equal(e.readiness([]),'insufficient_usable_sensor_time_volume_observations');
        const rows=Array.from({length:20},(_,i)=>({time_s:i*.2,injected_volume_ml:i*.2,visible_H_mean:42,visible_S_mean:1,visible_V_mean:1, theoretical_equivalence_volume_ml:10}));
        assert.equal(e.readiness(rows),'flat_recorded_sensor_signals');
        assert.throws(()=>e.predict({},rows,'strong_acid_strong_base'),/unsupported/);
        assert.equal(e.evenRound(2.5),2);assert.equal(e.evenRound(3.5),4);
        """
        run=subprocess.run(['node','-e',code],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
