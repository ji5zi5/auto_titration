#!/usr/bin/env python3
"""Dense, bounded aggregation search around the frozen typewise rankers.

This is same-12-run post-hoc development selection, not nested validation.
Every candidate score vector still comes from a fit excluding its evaluated run.
"""
import json, math, sys, time
from dataclasses import asdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
OUTPUT=ROOT/'data/ml/dense_type_conditioned_aggregation_search'
OUTPUT.mkdir(parents=True,exist_ok=True)
from auto_titrator.ml_typewise_eval import load_runs
from tools import search_advanced_type_conditioned_sensor_rankers as adv
from tools.sensor_transition_candidate_union import generate_union_candidates
from tools.type_conditioned_sensor_sequence_search import TYPE_CONFIGS

runs=load_runs(ROOT/'머신러닝용 파일모음')
sets={str(r.path):generate_union_candidates(r.rows) for r in runs}
# Frozen scorer families from current 0.359791% result.
specs={t:adv.Spec(c.family,c.feature_subset if c.feature_subset!='full_sensor' else 'full',c.feature_transform,c.parameter) for t,c in TYPE_CONFIGS.items()}
start=time.time(); out={}; combination_count=0
for typ,spec in specs.items():
    truns=[r for r in runs if r.titration_type==typ]
    folds={}
    for test in truns:
        outer=[r for r in runs if r.path!=test.path]
        same=[r for r in outer if r.titration_type==typ]
        folds[str(test.path)]=(adv.score_one(outer,sets[str(test.path)],sets,spec),adv.score_one(same,sets[str(test.path)],sets,spec))
    best=None
    # Dense deterministic post-hoc aggregation. Every score vector came from a fit excluding test.
    current=TYPE_CONFIGS[typ]
    if typ == "strong_acid_strong_base":
        weights=np.array([1.0]); temps=np.geomspace(0.2,2.0,30); blends=np.linspace(0,0.3,13); topks=[40,64,80,100,0]
    elif typ == "weak_acid_strong_base":
        weights=np.linspace(0.5,1.0,51); temps=np.geomspace(0.2,2.0,50); blends=np.linspace(0,0.3,16); topks=list(range(10,31))+[40,64,0]
    elif typ == "strong_acid_weak_base":
        weights=np.array([1.0]); temps=np.geomspace(0.02,0.5,60); blends=np.linspace(0,0.3,16); topks=list(range(10,31))+[40,64,80,100,0]
    else:
        weights=np.array([1.0]); temps=np.geomspace(0.02,0.5,60); blends=np.linspace(0,0.3,16); topks=list(range(2,16))+[20,30,40,64,0]
    combination_count += len(weights)*len(temps)*len(blends)*len(topks)
    for norm in (current.score_normalization,):
      normalized={p:(adv.normalize(a,norm),adv.normalize(b,norm)) for p,(a,b) in folds.items()}
      for w in weights:
        prepared=[]
        for test in truns:
          a,b=normalized[str(test.path)]; score=w*a+(1-w)*b
          order=np.argsort(-score,kind='stable')
          prepared.append((test,score,order))
        for topk in topks:
          for temp in temps:
            centroids=[]; tops=[]
            for test,score,order in prepared:
              chosen=order if topk==0 else order[:min(topk,len(order))]
              z=(score[chosen]-score[chosen].max())/temp; ew=np.exp(z); ew/=ew.sum()
              centroids.append(float(np.dot(ew,[sets[str(test.path)][int(i)].boundary for i in chosen])))
              tops.append(sets[str(test.path)][int(order[0])].boundary)
            frames=np.rint(np.outer(1-blends,centroids)+np.outer(blends,tops)).astype(int)
            ape=np.empty_like(frames,dtype=float)
            for j,test in enumerate(truns):
              frames[:,j]=np.clip(frames[:,j],0,len(test.rows)-1)
              actual=float(test.theoretical_equivalence_volume_ml)
              ape[:,j]=[abs(float(test.rows[int(f)]['injected_volume_ml'])-actual)/actual*100 for f in frames[:,j]]
            means=ape.mean(axis=1); bi=int(np.argmin(means)); mape=float(means[bi])
            key=(mape,norm,float(w),int(topk),float(temp),float(blends[bi]))
            if best is None or key[:1] < best[:1]:
              rows=[]
              for j,test in enumerate(truns):
                frame=int(frames[bi,j]); pred=float(test.rows[frame]['injected_volume_ml']); actual=float(test.theoretical_equivalence_volume_ml)
                rows.append({'run_name':test.path.name,'titration_type':typ,'selected_frame':frame,'predicted_ml':pred,'actual_ml':actual,'signed_error_ml':pred-actual,'ape_percent':abs(pred-actual)/actual*100})
              best=key+(rows,)
    mape,norm,w,topk,temp,blend,rows=best
    out[typ]={'mape_percent':mape,'spec':asdict(spec),'normalization':norm,'global_weight':w,'top_k':topk,'temperature':temp,'top_blend':blend,'rows':rows}
    print(typ,mape,norm,w,topk,temp,blend,flush=True)
allrows=[r for x in out.values() for r in x['rows']]
y=np.array([r['actual_ml'] for r in allrows]); p=np.array([r['predicted_ml'] for r in allrows]); e=p-y
summary={'claim_scope':'same_12_run_post_hoc_dense_aggregation_selection_not_independent_validation','runtime_seconds':time.time()-start,'dense_combinations_compared':combination_count,'type_results':out,'metrics':{'mae_ml':float(np.mean(abs(e))),'rmse_ml':float(np.sqrt(np.mean(e*e))),'mape_percent':float(np.mean(abs(e)/y)*100)},'rows':allrows}
(OUTPUT/'dense_search_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary['metrics'],indent=2))
