"""Export trusted fitted sklearn endpoint pipelines, without fitting or retraining.

The portable runtime uses only fitted numbers and the frozen candidate algorithm.
This artifact is for completed-run analysis, never causal pump control.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def estimator(value):
    if value is None:
        return None
    steps = []
    for _, model in value.steps:
        name = type(model).__name__
        if name == 'StandardScaler':
            steps.append(dict(kind='scale', mean=model.mean_.tolist(), scale=model.scale_.tolist()))
        elif name == 'PLSRegression':
            steps.append(dict(kind='linear', center=model._x_mean.tolist(), coef=model.coef_.reshape(-1).tolist(), intercept=float(model.intercept_.reshape(-1)[0])))
        elif name == 'LinearDiscriminantAnalysis':
            if model.coef_.shape[0] != 1:
                raise ValueError('Only fitted binary LDA is supported')
            steps.append(dict(kind='linear', center=[0.0]*model.coef_.shape[1], coef=model.coef_[0].tolist(), intercept=float(model.intercept_[0])))
        elif name == 'KernelRidge':
            if model.kernel != 'rbf':
                raise ValueError('Only fitted RBF kernel is supported')
            steps.append(dict(kind='rbf', gamma=float(model.gamma), x=model.X_fit_.tolist(), dual=model.dual_coef_.reshape(-1).tolist()))
        elif name == 'QuadraticDiscriminantAnalysis':
            if list(model.classes_) != [0, 1]:
                raise ValueError('Only binary QDA with classes [0,1] is supported')
            steps.append(dict(kind='qda', means=model.means_.tolist(), priors=model.priors_.tolist(), rotations=[x.tolist() for x in model.rotations_], scalings=[x.tolist() for x in model.scalings_]))
        else:
            raise ValueError(f'Unsupported fitted estimator: {name}')
    return steps

def export_bundle(path: Path):
    raw=path.read_bytes()
    artifact=pickle.loads(raw)  # Trusted repo artifact only; never load user uploads.
    if artifact.get('artifact_type') != 'type_conditioned_sensor_endpoint_ranker_v1':
        raise ValueError('Unsupported endpoint artifact')
    result={k:artifact[k] for k in ('artifact_type','model_key','prediction_scope','deployment_strategy') if k in artifact}
    result.update(portable_schema='endpoint_portable_v1', source_sha256=hashlib.sha256(raw).hexdigest(), models={})
    for kind,entry in artifact['models'].items():
        result['models'][kind]={
            'config':entry['config'],
            'training_median_positive_volume_step_ml':entry.get('training_median_positive_volume_step_ml'),
            'global_estimator':estimator(entry.get('global_estimator')),
            'type_estimator':estimator(entry.get('type_estimator')),
            'fold_estimators':[{key:estimator(fold.get(key)) for key in ('global_estimator','type_estimator')} for fold in entry.get('fold_estimators',[])],
        }
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=ROOT/'data/labeled/type-conditioned-sensor-endpoint-ranker.pkl')
    p.add_argument('--output',type=Path,default=ROOT/'mobile/android/app/src/main/assets/models/endpoint-portable.json.gz')
    args=p.parse_args()
    text=json.dumps(export_bundle(args.input),allow_nan=False,separators=(',',':')).encode()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(gzip.compress(text,mtime=0) if args.output.suffix=='.gz' else text)
    print(f'Exported {len(text)} JSON bytes to {args.output} ({args.output.stat().st_size} bytes). No retraining.')
if __name__=='__main__':main()
