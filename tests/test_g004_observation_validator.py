import ast
import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.hik_whole_apk import g004_observation_validator as v

ROOT = Path(__file__).resolve().parents[1]

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(v.canonical_json_bytes(value))


def run_cli(*args, cwd=None):
    proc = subprocess.run([sys.executable, '-m', 'tools.hik_whole_apk.g004_observation_validator', *args], cwd=cwd or ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f'bad stdout {proc.stdout!r} stderr={proc.stderr!r}') from exc
    return proc, payload


def run_script_cli(*args, cwd=None):
    proc = subprocess.run(
        [sys.executable, str(ROOT/'tools/hik_whole_apk/g004_observation_validator.py'), *args],
        cwd=cwd or ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f'bad stdout {proc.stdout!r} stderr={proc.stderr!r}') from exc
    return proc, payload


def hook(**kw):
    obj = {'schema':'g004-hook-manifest/v1','hook_manifest_id':'HOOK-1','event_schema_id':'g004-event/v1','immutable_source_refs':[{'path':'official.apk','sha256':'a'*64}]}
    obj.update(kw); return obj


def event(eid='EVT-1', **kw):
    obj = {'schema':'g004-event/v1','event_id':eid,'event_schema_id':'g004-event/v1','hook_manifest_id':'HOOK-1','collection_session_id':'sess','run_correlation_id':'corr','sequence':1,'observed_at':'2026-07-23T00:00:00Z'}
    obj.update(kw); return obj


def run(**kw):
    obj = {'schema':'g004-run-manifest/v1','run_manifest_id':'RUN-1','event_ids':['EVT-1'],'collection_session_id':'sess'}
    obj.update(kw); return obj


def replay(**kw):
    obj = {'schema':'g004-replay-fixture/v1','replay_fixture_id':'RPL-1','run_manifest_id':'RUN-1','run_manifest_sha256':'b'*64}
    obj.update(kw); return obj


def bundle(**kw):
    obj = {'schema':'g004-evidence-bundle/v1','evidence_bundle_id':'EVB-1','run_manifest_ids':['RUN-1'],'replay_fixture_ids':['RPL-1']}
    obj.update(kw); return obj


def unknown(**kw):
    obj = {'schema':'g004-unknown-manifest/v1','unknown_manifest_id':'UNK-M-1','unknown_id':'UNK-1','closure_effect':'nonterminal','state':'unknown_hardware_unavailable','owner':'G004'}
    obj.update(kw); return obj


def graph_artifacts():
    hook_value=hook()
    event_value=event()
    run_value=run()
    replay_value=replay(run_manifest_sha256=v.content_digest(run_value, 'run'))
    bundle_value=bundle()
    return hook_value,event_value,run_value,replay_value,bundle_value


def write_graph(root):
    names=('hook.json','event.json','run.json','replay.json','bundle.json')
    for name,value in zip(names, graph_artifacts()):
        write_json(root/name, value)
    return names


class G004ReferenceDagTests(unittest.TestCase):
    def test_rejects_event_run_manifest_back_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); e=event(run_manifest_id='RUN-1'); r=run()
            write_json(root/'event.json', e); write_json(root/'run.json', r)
            _, out = run_cli('validate','--root',td,'--manifest','event.json','--manifest','run.json')
            self.assertFalse(out['ok'])
            self.assertTrue(any(err['field']=='event.run_manifest_id -> run.event_ids[]' for err in out['errors']))

    def test_run_may_reference_event_ids_one_way(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'hook.json', hook()); write_json(root/'event.json', event()); write_json(root/'run.json', run())
            proc,out=run_cli('validate','--root',td,'--manifest','hook.json','--manifest','event.json','--manifest','run.json')
            self.assertEqual(proc.returncode,0,out); self.assertTrue(out['ok'])

    def test_event_allows_non_content_addressed_run_correlation_id(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'hook.json', hook()); write_json(root/'event.json', event(run_correlation_id='RUN-1-human-correlation-only'))
            _,out=run_cli('validate','--root',td,'--manifest','hook.json','--manifest','event.json')
            self.assertTrue(out['ok'], out)

    def test_cycle_error_contains_exact_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'e.json', event(run_manifest_id='RUN-1')); write_json(root/'r.json', run())
            _, out=run_cli('validate','--root',td,'--manifest','e.json','--manifest','r.json')
            self.assertIn('event.run_manifest_id -> run.event_ids[]',[e['field'] for e in out['errors']])

    def test_schema_family_precedes_all_foreign_reference_fields(self):
        cases = [
            (hook(event_id='EVT-X', run_manifest_id='RUN-X'), 'hook'),
            (event(replay_fixture_id='RPL-X', evidence_bundle_id='EVB-X'), 'event'),
            (run(replay_fixture_id='RPL-X', evidence_bundle_id='EVB-X'), 'run'),
            (replay(run_manifest_id='RUN-X', event_id='EVT-X'), 'replay'),
            (bundle(run_manifest_id='RUN-X', replay_fixture_id='RPL-X'), 'bundle'),
            (unknown(run_manifest_id='RUN-X', event_id='EVT-X'), 'unknown'),
        ]
        for artifact, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(v.detect_family(artifact), expected)

    def test_own_family_id_precedes_legal_foreign_reference_ids_without_schema(self):
        cases = [
            ({'event_id':'EVT-1','hook_manifest_id':'HOOK-1'}, 'event'),
            ({'run_manifest_id':'RUN-1','event_ids':['EVT-1']}, 'run'),
            ({'replay_fixture_id':'RPL-1','run_manifest_id':'RUN-1'}, 'replay'),
            ({'evidence_bundle_id':'EVB-1','run_manifest_ids':['RUN-1'],'replay_fixture_ids':['RPL-1']}, 'bundle'),
            ({'unknown_manifest_id':'UNK-1','run_manifest_id':'RUN-1'}, 'unknown'),
            ({'hook_manifest_id':'HOOK-1'}, 'hook'),
        ]
        for artifact, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(v.detect_family(artifact), expected)

    def test_full_one_way_graph_resolves_all_families(self):
        with tempfile.TemporaryDirectory() as td:
            names=write_graph(Path(td))
            args=['validate','--root',td]
            for name in names:
                args.extend(('--bundle' if name == 'bundle.json' else '--manifest', name))
            proc,out=run_cli(*args)
            self.assertEqual(proc.returncode, 0, out)
            self.assertTrue(out['ok'], out)

    def test_duplicate_artifact_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            write_json(root/'hook-a.json', hook())
            write_json(root/'hook-b.json', hook(immutable_source_refs=[]))
            _,out=run_cli('validate','--root',td,'--manifest','hook-a.json','--manifest','hook-b.json')
            self.assertFalse(out['ok'])
            self.assertTrue(any('duplicate artifact ID HOOK-1' in error['message'] for error in out['errors']))

    def test_missing_references_fail_for_every_graph_edge(self):
        cases = [
            (('event.json', event(hook_manifest_id='HOOK-MISSING')), 'missing referenced hook'),
            (('run.json', run(event_ids=['EVT-MISSING'])), 'missing referenced event'),
            (('replay.json', replay(run_manifest_id='RUN-MISSING')), 'missing referenced run'),
            (('bundle.json', bundle(run_manifest_ids=['RUN-MISSING'], replay_fixture_ids=[])), 'missing referenced run'),
            (('bundle.json', bundle(run_manifest_ids=[], replay_fixture_ids=['RPL-MISSING'])), 'missing referenced replay'),
        ]
        for (name,artifact),message in cases:
            with self.subTest(name=name, message=message), tempfile.TemporaryDirectory() as td:
                write_json(Path(td)/name, artifact)
                _,out=run_cli('validate','--root',td,'--bundle' if name == 'bundle.json' else '--manifest',name)
                self.assertFalse(out['ok'])
                self.assertTrue(any(message in error['message'] for error in out['errors']), out)

    def test_event_schema_must_match_referenced_hook(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            write_json(root/'hook.json', hook(event_schema_id='schema-a'))
            write_json(root/'event.json', event(event_schema_id='schema-b'))
            _,out=run_cli('validate','--root',td,'--manifest','hook.json','--manifest','event.json')
            self.assertFalse(out['ok'])
            self.assertTrue(any(error['field']=='event_schema_id' and 'does not match' in error['message'] for error in out['errors']))

    def test_replay_hash_must_match_referenced_run(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            write_json(root/'run.json', run(event_ids=[]))
            write_json(root/'replay.json', replay(run_manifest_sha256='0'*64))
            _,out=run_cli('validate','--root',td,'--manifest','run.json','--manifest','replay.json')
            self.assertFalse(out['ok'])
            self.assertTrue(any(error['field']=='run_manifest_sha256' and 'incorrect hash' in error['message'] for error in out['errors']))

    def test_replay_accepts_explicit_run_manifest_ref_id_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            run_value=run(event_ids=[])
            replay_value=replay(
                run_manifest_ref_id='RUN-1',
                run_manifest_sha256=v.content_digest(run_value,'run'),
            )
            del replay_value['run_manifest_id']
            write_json(root/'run.json',run_value)
            write_json(root/'replay.json',replay_value)
            proc,out=run_cli('validate','--root',td,'--manifest','run.json','--manifest','replay.json')
            self.assertEqual(proc.returncode,0,out)
            self.assertTrue(out['ok'],out)

    def test_evidence_replay_run_must_belong_to_evidence_run_set(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            run_one=run(run_manifest_id='RUN-1',event_ids=[])
            run_two=run(run_manifest_id='RUN-2',event_ids=[])
            replay_one=replay(run_manifest_id='RUN-1',run_manifest_sha256=v.content_digest(run_one,'run'))
            evidence=bundle(run_manifest_ids=['RUN-2'],replay_fixture_ids=['RPL-1'])
            for name,value in (('run-1.json',run_one),('run-2.json',run_two),('replay.json',replay_one),('bundle.json',evidence)):
                write_json(root/name,value)
            _,out=run_cli('validate','--root',td,'--manifest','run-1.json','--manifest','run-2.json','--manifest','replay.json','--bundle','bundle.json')
            self.assertFalse(out['ok'])
            self.assertTrue(any('outside the evidence run set' in error['message'] for error in out['errors']))


class G004CanonicalIdentityTests(unittest.TestCase):
    def test_canonical_json_sorts_keys_and_has_trailing_newline(self):
        self.assertEqual(v.canonical_json_bytes({'b':2,'a':1}), b'{"a":1,"b":2}\n')

    def test_canonical_json_normalizes_nfc(self):
        self.assertEqual(v.canonical_json_bytes({'x':'e\u0301'}), v.canonical_json_bytes({'x':'é'}))

    def test_duplicate_keys_fail(self):
        with self.assertRaises(v.DuplicateKeyError):
            v.load_json_text('{"a":1,"a":2}')

    def test_nfc_colliding_keys_fail(self):
        with self.assertRaises(v.DuplicateKeyError):
            v.load_json_text('{"é":1,"é":2}')

    def test_nonfinite_numbers_fail(self):
        with self.assertRaises(ValueError):
            v.load_json_text('{"x": NaN}')

    def test_key_order_does_not_change_id(self):
        self.assertEqual(v.content_digest({'event_id':'A','schema':'g004-event/v1','event_schema_id':'s'}), v.content_digest({'event_schema_id':'s','schema':'g004-event/v1','event_id':'A'}))

    def test_semantic_change_changes_id(self):
        a=event(); b=event(sequence=2)
        self.assertNotEqual(v.content_digest(a,'event'), v.content_digest(b,'event'))

    def _self_hash_excluded(self, obj, fam):
        base = copy.deepcopy(obj)
        digest = v.content_digest(base, fam)
        changed_hash = copy.deepcopy(base); changed_hash['manifest_sha256']='0'*64
        self.assertEqual(digest, v.content_digest(changed_hash, fam))
        changed_content = copy.deepcopy(base); changed_content['semantic_note']='changed'
        self.assertNotEqual(digest, v.content_digest(changed_content, fam))

    def test_hook_self_hash_is_excluded(self): self._self_hash_excluded(hook(), 'hook')
    def test_event_self_hash_is_excluded(self): self._self_hash_excluded(event(), 'event')
    def test_run_self_hash_is_excluded(self): self._self_hash_excluded(run(), 'run')
    def test_replay_self_hash_is_excluded(self): self._self_hash_excluded(replay(), 'replay')
    def test_bundle_self_hash_is_excluded(self): self._self_hash_excluded(bundle(), 'bundle')
    def test_unknown_self_hash_is_excluded(self): self._self_hash_excluded(unknown(), 'unknown')

    def test_nested_official_source_ref_hash_changes_digest(self):
        first=hook(immutable_source_refs=[{'id':'official-apk','path':'official.apk','sha256':'a'*64}])
        second=copy.deepcopy(first)
        second['immutable_source_refs'][0]['sha256']='b'*64
        self.assertNotEqual(v.content_digest(first,'hook'), v.content_digest(second,'hook'))

    def test_nested_semantic_identity_changes_digest(self):
        first=bundle(source={'id':'official-observation','manifest_sha256':'a'*64})
        second=copy.deepcopy(first)
        second['source']['id']='other-observation'
        self.assertNotEqual(v.content_digest(first,'bundle'), v.content_digest(second,'bundle'))


class G004CliContractTests(unittest.TestCase):
    def test_only_six_required_subcommands_are_public(self):
        parser = v.build_parser(); sub = next(a for a in parser._actions if isinstance(a, argparse_subparsers_type()))
        self.assertEqual(set(sub.choices), set(v.REQUIRED_COMMANDS))

    def test_each_command_emits_required_bounded_json_fields(self):
        required={'ok','checked_files','errors','manifest_ids','event_count','synthetic_evidence_count'}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'h.json', hook()); (root/'events.jsonl').write_bytes(v.canonical_json_bytes(event()));
            cmds=[('validate','--root',td,'--manifest','h.json'),('validate-index','--root',td,'--index','index.json'),('normalize-events','--root',td,'--input','events.jsonl','--output','norm.jsonl'),('pair','--root',td,'--untouched','events.jsonl','--instrumented','events.jsonl','--output','pair.json'),('emit-hook','--root',td,'--hook-manifest','h.json','--event-out','payload.json'),('collect-dry-run','--root',td,'--adapter','untouched','--session','bounded-fields','--output-dir','dry','--no-auto-start')]
            write_json(root/'index.json', {'manifests':['h.json']})
            for cmd in cmds:
                _,out=run_cli(*cmd)
                self.assertTrue(required <= set(out), cmd)
                self.assertLess(len(json.dumps(out)), 20000)

    def test_errors_have_path_field_message_shape(self):
        _,out=run_cli('validate')
        self.assertFalse(out['ok']); self.assertEqual(set(out['errors'][0]), {'path','field','message'})

    def test_validator_requires_explicit_manifest_or_bundle(self):
        _,out=run_cli('validate'); self.assertFalse(out['ok']); self.assertIn('requires', out['errors'][0]['message'])

    def test_validate_index_requires_explicit_index(self):
        proc,out=run_cli('validate-index')
        self.assertNotEqual(proc.returncode,0)
        self.assertEqual(proc.stderr, '')
        self.assertEqual(len(out['errors']), 1)
        self.assertEqual(out['errors'][0]['field'], 'arguments')

    def test_no_command_scans_repository_root(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'nested'/'h.json', hook())
            _,out=run_cli('validate','--root',td,'--manifest','nested')
            self.assertFalse(out['ok']); self.assertIn('no directory scans', out['errors'][0]['message'])

    def test_default_max_filesize_is_five_mib(self):
        self.assertEqual(v.DEFAULT_MAX_BYTES, 5*1024*1024)

    def test_max_filesize_parsing_is_fail_closed(self):
        self.assertEqual(v.parse_filesize('5M'), 5*1024*1024)
        self.assertEqual(v.parse_filesize('5MiB'), 5*1024*1024)
        self.assertEqual(v.parse_filesize('7'), 7)
        for invalid in ('0', '-1', '+5M', '1.5M', '5MBjunk', ' 5M', '5M '):
            with self.subTest(invalid=invalid), self.assertRaises(argparse.ArgumentTypeError):
                v.parse_filesize(invalid)

    def test_oversized_input_fails_before_parse(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'big.json'; p.write_text('{bad', encoding='utf-8')
            _,out=run_cli('validate','--root',td,'--max-bytes','2','--manifest','big.json')
            self.assertFalse(out['ok']); self.assertEqual(out['errors'][0]['field'], 'size')

    def test_exact_verification_command_forms_execute_functionally(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            write_graph(root)
            write_json(root/'index.json', {'manifests':[str(root/'hook.json')]})
            (root/'events.jsonl').write_bytes(v.canonical_json_bytes(event()))
            commands = [
                ('validate','--manifest',str(root/'hook.json'),'--manifest',str(root/'event.json'),'--manifest',str(root/'run.json'),'--manifest',str(root/'replay.json'),'--bundle',str(root/'bundle.json'),'--max-filesize','5M'),
                ('validate-index','--index',str(root/'index.json'),'--max-filesize','5M'),
                ('normalize-events','--input',str(root/'events.jsonl'),'--output',str(root/'normalized.jsonl'),'--max-filesize','5M'),
                ('pair','--untouched',str(root/'events.jsonl'),'--instrumented',str(root/'events.jsonl'),'--output',str(root/'pairs.json'),'--max-filesize','5M'),
                ('emit-hook','--hook-manifest',str(root/'hook.json'),'--event-out',str(root/'hook-event.json'),'--max-filesize','5M'),
                ('collect-dry-run','--adapter','untouched','--session','verification-001','--output-dir',str(root/'dry-run'),'--no-auto-start','--max-filesize','5M'),
            ]
            for command in commands:
                with self.subTest(command=command[0]):
                    proc,out=run_script_cli(*command)
                    self.assertEqual(proc.returncode, 0, (out, proc.stderr))
                    self.assertTrue(out['ok'], out)

    def test_cli_rejects_malformed_max_filesize(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'hook.json'; write_json(path, hook())
            for invalid in ('0', '-1', '1.5M', '5MBjunk'):
                with self.subTest(invalid=invalid):
                    proc=subprocess.run(
                        [sys.executable,str(ROOT/'tools/hik_whole_apk/g004_observation_validator.py'),'validate','--manifest',str(path),'--max-filesize',invalid],
                        cwd=ROOT,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=10,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(proc.stderr, '')
                    out=json.loads(proc.stdout)
                    self.assertEqual(len(out['errors']), 1)
                    self.assertEqual(out['errors'][0]['field'], 'arguments')
                    self.assertIn('size must be a positive integer', out['errors'][0]['message'])

    def test_all_argparse_failures_emit_one_bounded_standard_json_result(self):
        cases = [
            ('validate-index',),
            ('normalize-events','--input','in.jsonl'),
            ('pair','--untouched','u.jsonl'),
            ('emit-hook','--hook-manifest','hook.json'),
            ('collect-dry-run','--adapter','untouched','--output-dir','dry','--no-auto-start'),
            ('collect-dry-run','--adapter','untouched','--session','bad session','--output-dir','dry','--no-auto-start'),
            ('unknown-command',),
        ]
        required={'ok','checked_files','errors','manifest_ids','event_count','synthetic_evidence_count'}
        for command in cases:
            with self.subTest(command=command):
                proc,out=run_script_cli(*command)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stderr, '')
                self.assertEqual(set(out), required)
                self.assertFalse(out['ok'])
                self.assertEqual(len(out['errors']), 1)
                self.assertEqual(set(out['errors'][0]), {'path','field','message'})
                self.assertLess(len(proc.stdout.encode('utf-8')), 4096)

    def test_validate_index_verifies_entry_count_and_raw_sha256_before_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            artifact=root/'hook.json'
            write_json(artifact, hook())
            raw_hash=v.sha256_bytes(artifact.read_bytes())
            write_json(root/'index.json', {
                'entry_count':1,
                'entries':[{'path':'hook.json','sha256':raw_hash,'family':'hook','label':'official-hook'}],
            })
            proc,out=run_cli('validate-index','--index',str(root/'index.json'))
            self.assertEqual(proc.returncode, 0, out)
            self.assertTrue(out['ok'], out)
            self.assertIn('HOOK-1', out['manifest_ids'])

            write_json(root/'bad-hash.json', {
                'entry_count':1,
                'entries':[{'path':'hook.json','sha256':'0'*64,'family':'hook'}],
            })
            _,bad_hash=run_cli('validate-index','--index',str(root/'bad-hash.json'))
            self.assertFalse(bad_hash['ok'])
            self.assertEqual(bad_hash['manifest_ids'], [])
            self.assertTrue(any('raw-file sha256 mismatch' in error['message'] for error in bad_hash['errors']))

            write_json(root/'bad-count.json', {
                'entry_count':2,
                'entries':[{'path':'hook.json','sha256':raw_hash}],
            })
            _,bad_count=run_cli('validate-index','--index',str(root/'bad-count.json'))
            self.assertFalse(bad_count['ok'])
            self.assertEqual(bad_count['manifest_ids'], [])
            self.assertTrue(any(error['field']=='entry_count' for error in bad_count['errors']))

    def test_validate_index_uses_contained_declared_base_without_cli_root(self):
        for base_key in ('base_dir','root'):
            with self.subTest(base_key=base_key), tempfile.TemporaryDirectory() as td:
                root=Path(td)
                artifact=root/'artifacts'/'hook.json'
                write_json(artifact, hook())
                write_json(root/'index.json', {
                    base_key:'artifacts',
                    'entry_count':1,
                    'entries':[{'path':'hook.json','sha256':v.sha256_bytes(artifact.read_bytes())}],
                })
                proc,out=run_cli('validate-index','--index',str(root/'index.json'))
                self.assertEqual(proc.returncode, 0, out)
                self.assertTrue(out['ok'], out)

    def test_validate_index_rejects_declared_base_escape_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root=Path(td)
            write_json(Path(outside)/'hook.json', hook())
            write_json(root/'parent-escape.json', {'base_dir':'../outside','entries':['hook.json']})
            _,parent=run_cli('validate-index','--index',str(root/'parent-escape.json'))
            self.assertFalse(parent['ok'])
            self.assertTrue(any(error['field']=='base_dir' for error in parent['errors']))

            (root/'linked').symlink_to(outside)
            write_json(root/'symlink-escape.json', {'base_dir':'linked','entries':['hook.json']})
            _,symlink=run_cli('validate-index','--index',str(root/'symlink-escape.json'))
            self.assertFalse(symlink['ok'])
            self.assertTrue(any('containment' in error['message'] for error in symlink['errors']))

    def test_package_index_contract_resolves_sibling_family_paths_without_cli_root(self):
        with tempfile.TemporaryDirectory() as td:
            package_root=Path(td)
            artifact=package_root/'hooks'/'hook.json'
            write_json(artifact, hook())
            entry={'path':'hooks/hook.json','sha256':v.sha256_bytes(artifact.read_bytes())}
            index_path=package_root/'indexes'/'all-artifacts.json'
            write_json(index_path, {
                'schema':'g004-index/v1',
                'index_id':'IDX-ALL',
                'family':'all',
                'entry_count':1,
                'files':[entry],
            })
            write_json(package_root/'indexes'/'package.json', {
                'schema':'g004-package-index/v1',
                'package_id':'PKG-G004',
                'artifact_count':1,
                'families':{'all_artifacts':'indexes/all-artifacts.json'},
                'files':[entry],
            })
            write_json(package_root/'hooks'/'undeclared.json', hook(hook_manifest_id='HOOK-UNDECLARED'))
            proc,out=run_cli('validate-index','--index',str(index_path),'--max-filesize','5M')
            self.assertEqual(proc.returncode, 0, out)
            self.assertTrue(out['ok'], out)
            self.assertEqual(out['manifest_ids'], ['HOOK-1'])
            self.assertNotIn(str(package_root/'hooks'/'undeclared.json'), out['checked_files'])

    def test_package_index_contract_requires_explicit_membership_and_mirrored_hash(self):
        cases=('missing-membership','mismatched-package-hash')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                package_root=Path(td)
                artifact=package_root/'hooks'/'hook.json'
                write_json(artifact, hook())
                entry={'path':'hooks/hook.json','sha256':v.sha256_bytes(artifact.read_bytes())}
                index_path=package_root/'indexes'/'all-artifacts.json'
                write_json(index_path, {
                    'schema':'g004-index/v1',
                    'index_id':'IDX-ALL',
                    'family':'all',
                    'entry_count':1,
                    'files':[entry],
                })
                package_entry=dict(entry)
                families={'all_artifacts':'indexes/all-artifacts.json'}
                if case == 'missing-membership':
                    families={'other':'indexes/other.json'}
                else:
                    package_entry['sha256']='0'*64
                write_json(package_root/'indexes'/'package.json', {
                    'schema':'g004-package-index/v1',
                    'package_id':'PKG-G004',
                    'artifact_count':1,
                    'families':families,
                    'files':[package_entry],
                })
                _,out=run_cli('validate-index','--index',str(index_path))
                self.assertFalse(out['ok'])
                self.assertEqual(out['manifest_ids'], [])
                self.assertTrue(any(error['field']=='package_contract' for error in out['errors']), out)

    def test_package_index_contract_rejects_parent_components_and_symlink_entries(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            package_root=Path(td)
            outside_artifact=Path(outside)/'hook.json'
            write_json(outside_artifact, hook())
            (package_root/'hooks').mkdir()
            (package_root/'hooks'/'linked.json').symlink_to(outside_artifact)
            for entry_path in ('../outside.json','hooks/linked.json'):
                with self.subTest(entry_path=entry_path):
                    entry={'path':entry_path,'sha256':v.sha256_bytes(outside_artifact.read_bytes())}
                    index_path=package_root/'indexes'/'all-artifacts.json'
                    write_json(index_path, {
                        'schema':'g004-index/v1',
                        'index_id':'IDX-ALL',
                        'family':'all',
                        'entry_count':1,
                        'files':[entry],
                    })
                    write_json(package_root/'indexes'/'package.json', {
                        'schema':'g004-package-index/v1',
                        'package_id':'PKG-G004',
                        'artifact_count':1,
                        'families':{'all_artifacts':'indexes/all-artifacts.json'},
                        'files':[entry],
                    })
                    _,out=run_cli('validate-index','--index',str(index_path))
                    self.assertFalse(out['ok'])
                    self.assertEqual(out['manifest_ids'], [])
                    self.assertTrue(any('escape' in error['message'] or 'outside' in error['message'] for error in out['errors']), out)

    def test_index_family_metadata_must_match_loaded_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            artifact=root/'event.json'
            write_json(artifact, event())
            write_json(root/'index.json', {
                'schema':'g004-index/v1',
                'index_id':'IDX-HOOKS',
                'family':'hook',
                'base_dir':'.',
                'entry_count':1,
                'files':[{'path':'event.json','sha256':v.sha256_bytes(artifact.read_bytes())}],
            })
            _,out=run_cli('validate-index','--index',str(root/'index.json'))
            self.assertFalse(out['ok'])
            self.assertTrue(any(error['field']=='family' for error in out['errors']), out)

    def test_path_escape_and_symlink_escape_fail(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as od:
            root=Path(td); outside=Path(od)/'o.json'; write_json(outside, hook()); (root/'link.json').symlink_to(outside)
            _,out=run_cli('validate','--root',td,'--manifest','../x.json','--manifest','link.json')
            self.assertFalse(out['ok']); fields=[e['message'] for e in out['errors']]
            self.assertTrue(any('escape' in m or 'outside' in m for m in fields))

    def test_detailed_log_path_must_match_g004_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'h.json', hook())
            _,out=run_cli('validate','--root',td,'--manifest','h.json','--log',str(root/'bad.log'))
            self.assertFalse(out['ok']); self.assertEqual(out['errors'][-1]['field'], 'log')

    def test_validator_uses_stdlib_only(self):
        tree=ast.parse(Path(v.__file__).read_text())
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports += [a.name.split('.')[0] for a in node.names]
            if isinstance(node, ast.ImportFrom) and node.module: imports.append(node.module.split('.')[0])
        allowed=set(sys.stdlib_module_names)|{'__future__'}
        self.assertFalse(sorted(set(imports)-allowed))


class argparse_subparsers_type:
    def __instancecheck__(self, obj):
        import argparse
        return isinstance(obj, argparse._SubParsersAction)


class G004EventNormalizationTests(unittest.TestCase):
    def test_normalize_events_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); rows=[event('A', sequence=1), event('B', sequence=2)]
            (root/'in.jsonl').write_bytes(b''.join(v.canonical_json_bytes(r) for r in rows))
            for name in ['o1.jsonl','o2.jsonl']:
                _,out=run_cli('normalize-events','--root',td,'--input','in.jsonl','--output',name); self.assertTrue(out['ok'], out)
            self.assertEqual((root/'o1.jsonl').read_bytes(), (root/'o2.jsonl').read_bytes())

    def test_sequence_and_monotonic_time_are_semantic(self):
        self.assertNotEqual(v.content_digest(event(sequence=1),'event'), v.content_digest(event(sequence=2),'event'))

    def test_missing_event_schema_id_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); e=event(); del e['event_schema_id']; (root/'in.jsonl').write_bytes(v.canonical_json_bytes(e))
            _,out=run_cli('normalize-events','--root',td,'--input','in.jsonl','--output','out.jsonl')
            self.assertFalse(out['ok']); self.assertEqual(out['errors'][0]['field'], 'event_schema_id')

    def test_duplicate_event_id_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'in.jsonl').write_bytes(v.canonical_json_bytes(event())+v.canonical_json_bytes(event()))
            _,out=run_cli('normalize-events','--root',td,'--input','in.jsonl','--output','out.jsonl')
            self.assertFalse(out['ok']); self.assertTrue(any(e['field']=='event_id' for e in out['errors']))

    def test_out_of_order_sequence_requires_loss_record(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); rows=[event('A',sequence=2),event('B',sequence=1)]
            (root/'in.jsonl').write_bytes(b''.join(v.canonical_json_bytes(r) for r in rows))
            _,out=run_cli('normalize-events','--root',td,'--input','in.jsonl','--output','out.jsonl')
            self.assertFalse(out['ok']); self.assertTrue(any(e['field']=='sequence' for e in out['errors']))

    def test_synthetic_event_remains_non_official(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'in.jsonl').write_bytes(v.canonical_json_bytes(event(synthetic=True,evidence_tier='E1')))
            _,out=run_cli('normalize-events','--root',td,'--input','in.jsonl','--output','out.jsonl')
            self.assertTrue(out['ok'], out); self.assertEqual(out['synthetic_evidence_count'],1)

    def test_fake_live_or_celsius_claim_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'in.jsonl').write_bytes(v.canonical_json_bytes(event(synthetic=True,claim='live Celsius frame')))
            _,out=run_cli('normalize-events','--root',td,'--input','in.jsonl','--output','out.jsonl')
            self.assertFalse(out['ok'])

    def test_overflow_jsonl_number_returns_one_bounded_structured_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'in.jsonl').write_text(
                '{"schema":"g004-event/v1","event_id":"EVT-1","event_schema_id":"g004-event/v1","hook_manifest_id":"HOOK-1","sequence":1,"observed_at":"2026-07-23T00:00:00Z","value":1e999}\n',
                encoding='utf-8',
            )
            proc,out=run_cli('normalize-events','--root',td,'--input','in.jsonl','--output','out.jsonl')
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stderr, '')
            self.assertFalse(out['ok'])
            self.assertEqual(len(out['errors']), 1)
            self.assertEqual(set(out['errors'][0]), {'path','field','message'})
            self.assertEqual(out['errors'][0]['field'], 'json')
            self.assertIn('non-finite JSON number 1e999', out['errors'][0]['message'])
            self.assertLess(len(proc.stdout.encode('utf-8')), 4096)
            self.assertFalse((root/'out.jsonl').exists())


class G004PairingTests(unittest.TestCase):
    def test_pair_accepts_accounted_divergence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'u.jsonl').write_bytes(v.canonical_json_bytes(event(value=1))); (root/'i.jsonl').write_bytes(v.canonical_json_bytes(event(value=2,divergence_reason='hook overhead accounted')))
            _,out=run_cli('pair','--root',td,'--untouched','u.jsonl','--instrumented','i.jsonl','--output','pair.json')
            self.assertTrue(out['ok'], out)

    def test_pair_rejects_unaccounted_instrumented_extra(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'u.jsonl').write_bytes(b''); (root/'i.jsonl').write_bytes(v.canonical_json_bytes(event()))
            _,out=run_cli('pair','--root',td,'--untouched','u.jsonl','--instrumented','i.jsonl','--output','pair.json')
            self.assertFalse(out['ok'])

    def test_pair_rejects_unaccounted_untouched_loss(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'u.jsonl').write_bytes(v.canonical_json_bytes(event())); (root/'i.jsonl').write_bytes(b'')
            _,out=run_cli('pair','--root',td,'--untouched','u.jsonl','--instrumented','i.jsonl','--output','pair.json')
            self.assertFalse(out['ok'])

    def test_pair_rejects_stale_event_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); e=event(manifest_sha256='0'*64); (root/'u.jsonl').write_bytes(v.canonical_json_bytes(e)); (root/'i.jsonl').write_bytes(v.canonical_json_bytes(e))
            _,out=run_cli('pair','--root',td,'--untouched','u.jsonl','--instrumented','i.jsonl','--output','pair.json')
            self.assertFalse(out['ok']); self.assertTrue(any('stale' in e['message'] for e in out['errors']))

    def test_pair_never_rewrites_untouched_event(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); data=v.canonical_json_bytes(event()); (root/'u.jsonl').write_bytes(data); (root/'i.jsonl').write_bytes(data)
            _,out=run_cli('pair','--root',td,'--untouched','u.jsonl','--instrumented','i.jsonl','--output','pair.json')
            self.assertTrue(out['ok']); self.assertEqual((root/'u.jsonl').read_bytes(), data)

    def test_pairing_digest_is_order_stable(self):
        p1={'schema':'g004-pairing-ledger/v1','pairs':[{'event_id':'A'},{'event_id':'B'}]}; p2={'pairs':[{'event_id':'A'},{'event_id':'B'}],'schema':'g004-pairing-ledger/v1'}
        self.assertEqual(v.content_digest(p1,'bundle'), v.content_digest(p2,'bundle'))


class G004HookAndCollectionTests(unittest.TestCase):
    def test_emit_hook_uses_explicit_manifest_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'h.json', hook())
            _,out=run_cli('emit-hook','--root',td,'--hook-manifest','h.json','--event-out','payload.json')
            self.assertTrue(out['ok'], out); self.assertTrue((root/'payload.json').is_file())

    def test_emit_hook_preserves_immutable_source_refs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); h=hook(immutable_source_refs=[{'path':'official/classes.dex','sha256':'b'*64}]); write_json(root/'h.json', h)
            run_cli('emit-hook','--root',td,'--manifest','h.json','--output','payload.json')
            payload=json.loads((root/'payload.json').read_text())
            self.assertEqual(payload['immutable_source_refs'], h['immutable_source_refs'])

    def test_emit_hook_cannot_add_run_manifest_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); write_json(root/'h.json', hook(run_manifest_id='RUN-1'))
            _,out=run_cli('emit-hook','--root',td,'--manifest','h.json','--output','payload.json')
            self.assertFalse(out['ok'])

    def test_collect_dry_run_supports_untouched_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            _,out=run_cli('collect-dry-run','--root',td,'--adapter','untouched','--session','untouched-001','--output-dir','dry','--no-auto-start')
            self.assertTrue(out['ok'], out)

    def test_collect_dry_run_supports_instrumented_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            _,out=run_cli('collect-dry-run','--root',td,'--adapter','instrumented','--session','instrumented-001','--output-dir','dry','--no-auto-start')
            self.assertTrue(out['ok'], out)

    def test_collect_dry_run_requires_no_auto_start(self):
        with tempfile.TemporaryDirectory() as td:
            _,out=run_cli('collect-dry-run','--root',td,'--adapter','untouched','--session','no-start-001','--output-dir','dry')
            self.assertFalse(out['ok'])

    def test_collect_dry_run_requires_session(self):
        with tempfile.TemporaryDirectory() as td:
            proc,out=run_script_cli('collect-dry-run','--adapter','untouched','--output-dir',str(Path(td)/'dry'),'--no-auto-start')
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr, '')
            self.assertEqual(len(out['errors']), 1)
            self.assertIn('--session', out['errors'][0]['message'])

    def test_collect_dry_run_uses_session_deterministically_in_metadata_and_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for output in ('first','second'):
                proc,out=run_cli('collect-dry-run','--root',td,'--adapter','untouched','--session','session-42','--output-dir',output,'--no-auto-start')
                self.assertEqual(proc.returncode, 0, out)
            for name in ('event.json','run.json','replay.json','bundle.json'):
                first=(root/'first'/name).read_bytes()
                second=(root/'second'/name).read_bytes()
                self.assertEqual(first, second)
                artifact=json.loads(first)
                self.assertEqual(artifact['collection_session_id'], 'session-42')
                self.assertIn('session-42', v.artifact_identifier(artifact))

    def test_collect_dry_run_does_not_touch_usb_or_android(self):
        source=Path(v.__file__).read_text().lower()
        forbidden=['usb.core','libusb','androidbridge','jni','javainterface']
        self.assertFalse([word for word in forbidden if word in source])

    def test_collect_dry_run_cannot_claim_live_or_celsius(self):
        with tempfile.TemporaryDirectory() as td:
            _,out=run_cli('collect-dry-run','--root',td,'--adapter','untouched','--session','claims-001','--output-dir','dry','--no-auto-start')
            self.assertTrue(out['ok'], out)
            text=''.join(p.read_text() for p in (Path(td)/'dry').glob('*.json')).lower()
            self.assertNotIn('live', text); self.assertNotIn('celsius', text)

    def test_imports_exactly_29_nonterminal_unknowns(self):
        with tempfile.TemporaryDirectory() as td:
            src=ROOT/'.omx/research/hikmicro-viewer-2.6.0/closure/current.json'
            _,out=run_cli('collect-dry-run','--adapter','untouched','--session','unknowns-001','--output-dir',str(Path(td)/'dry'),'--no-auto-start','--unknown-source',str(src))
            self.assertTrue(out['ok'], out)
            files=sorted((Path(td)/'dry'/'unknowns').glob('*.json'))
            self.assertEqual(len(files), 29)
            self.assertTrue(all(json.loads(p.read_text())['status']=='nonterminal' for p in files))


if __name__ == '__main__':
    unittest.main()
