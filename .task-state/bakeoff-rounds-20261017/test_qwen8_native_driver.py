"""CPU-only source contract tests; importing this module performs no external work."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid


def load_source():
    path=Path(__file__).with_name('QWEN8-VLLM-ALL38-R23.remote.py')
    return path.read_text(),ast.parse(path.read_text())


def extracted():
    source,tree=load_source()
    names={'reviewed_helper','transfer_payload','require_restored','restore_program','guest'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name in names]
    ns=dict(base64=base64,hashlib=hashlib,json=json,re=re,uuid=uuid,subprocess=subprocess)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<driver-functions>','exec'),ns)
    for n in tree.body:
        if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='SETUP_PROGRAM'for t in n.targets):ns['setup']=ast.literal_eval(n.value)
    return ns


class DriverTests(unittest.TestCase):
    def test_placeholder_and_wrong_hash_refused(self):
        f=extracted()['reviewed_helper']
        with self.assertRaises(ValueError):f('__unfilled__','__unfilled__')
        with self.assertRaises(ValueError):f(base64.b64encode(b'helper'),'0'*64)
        data=Path(__file__).parents[2]/'references/gpu_vllm_maintenance.py'
        helper=data.read_bytes()
        self.assertEqual(f(base64.b64encode(helper),hashlib.sha256(helper).hexdigest()),helper)

    def test_private_transfer_actual_setup_producer(self):
        ns=extracted();operation=str(uuid.uuid4());helper=b'# sealed helper fixture\n';key=b'a'*64
        for mode,bindings in [('host',None),('bridge',{'8000/tcp':[{'HostIp':'','HostPort':'8000'}]})]:
            route=dict(original_network_mode=mode,original_port_bindings=bindings)
            payload=ns['transfer_payload'](operation,route,helper,key)
            with tempfile.TemporaryDirectory()as td:
                # Redirect only /run and root ownership observations; real private files.
                real_path=Path
                def mapped(value):return real_path(td)if value=='/run'else real_path(value)
                actual_stat=Path.lstat
                def root_stat(p):
                    s=actual_stat(p)
                    return types.SimpleNamespace(st_uid=0,st_gid=0,st_nlink=s.st_nlink,st_mode=s.st_mode)
                calls=[]
                def run(args,**kw):
                    calls.append((args,kw))
                    root=Path(td)/('bakeoff-vllm-'+uuid.UUID(operation).hex)
                    self.assertEqual(set(x.name for x in root.iterdir()),{'gpu_vllm_maintenance.py','spec.json','api-key'})
                    self.assertEqual((root/'gpu_vllm_maintenance.py').read_bytes(),helper)
                    self.assertEqual((root/'api-key').read_bytes(),key)
                    spec=json.loads((root/'spec.json').read_bytes())
                    self.assertEqual(spec,dict(version=1,operation=operation,**route))
                    self.assertEqual(root.stat().st_mode&0o777,0o700)
                    return types.SimpleNamespace(returncode=0,stdout=b'{"status":"ready"}')
                output=types.SimpleNamespace(buffer=io.BytesIO())
                with patch('pathlib.Path',mapped),patch.object(real_path,'lstat',root_stat),patch('os.geteuid',return_value=0),patch('sys.stdin',io.StringIO(payload.decode())),patch('sys.stdout',output),patch('subprocess.run',run):
                    exec(compile(ns['setup'],'<setup>','exec'),{})
                self.assertEqual(calls[0][0][0:3],['/usr/bin/python3','-I','-B'])
                self.assertIn('prepare',calls[0][0]);self.assertEqual(calls[0][1]['timeout'],525)
                self.assertNotIn(key.decode(),repr(calls)+output.buffer.getvalue().decode()+ns['setup'])

    def test_private_transport_suppresses_failed_output(self):
        ns=extracted();logs=[];ns['save']=lambda *args:logs.append(args)
        secret=b'z'*64
        with patch('subprocess.run',return_value=types.SimpleNamespace(returncode=1,stdout=secret,stderr=secret))as run:
            with self.assertRaises(RuntimeError):ns['guest']('public-command',570,private_stdin=secret)
        args,kw=run.call_args
        self.assertEqual(kw['input'],secret);self.assertNotIn(secret.decode(),repr(args)+repr(logs))
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('public-command',570,output=secret,stderr=secret)):
            with self.assertRaises(RuntimeError):ns['guest']('public-command',570,private_stdin=secret)
        self.assertNotIn(secret.decode(),repr(logs))

    def test_restore_uncertainty_and_finite_commands(self):
        ns=extracted()
        receipt=dict(original_Qwen_restored=True,candidate_absent=True,guest_private_key_absent=True)
        ns['require_restored'](receipt)
        for field in receipt:
            with self.assertRaises(RuntimeError):ns['require_restored'](dict(receipt,**{field:False}))
        calls=[]
        with patch('subprocess.run',side_effect=lambda a,**kw:(calls.append((a,kw))or types.SimpleNamespace(returncode=0,stdout=b'{}'))),patch('sys.stdout',types.SimpleNamespace(buffer=io.BytesIO())):
            exec(ns['restore_program']('/run/bakeoff-vllm-'+uuid.uuid4().hex,str(uuid.uuid4()),'owned.service'),{})
        self.assertEqual([kw['timeout']for a,kw in calls],[125,110])
        self.assertIn('restore',calls[1][0]);self.assertTrue(calls[1][0][3].endswith('/gpu_vllm_maintenance.py'))

    def test_uncertain_restore_blocks_public_withdraw(self):
        source,tree=load_source()
        final=next(n.finalbody for n in tree.body if isinstance(n,ast.Try)and n.finalbody)
        with tempfile.TemporaryDirectory()as td:
            ns=extracted();logs=[];public_calls=[]
            replies=iter([b'{}',b'{"original_Qwen_restored":true,"candidate_absent":false,"guest_private_key_absent":true}',b'private-tar-fixture'])
            ns.update(child=None,keyfile=Path(td)/'absent-key',maintenance_attempted=True,setup_unit='owned.scope',maintenance_root='/run/bakeoff-vllm-'+uuid.uuid4().hex,operation=str(uuid.uuid4()),candidate_unit='owned.service',base=Path(td),safe_withdraw=False,owned_start='owned-start',Path=Path,os=__import__('os'),shlex=__import__('shlex'),guest=lambda *a,**kw:next(replies),save=lambda *a:logs.append(a),public=lambda *a:public_calls.append(a))
            with self.assertRaisesRegex(RuntimeError,'restoration unknown'):
                exec(compile(ast.Module(body=final,type_ignores=[]),'<actual-finally>','exec'),ns)
            self.assertFalse(ns['safe_withdraw']);self.assertEqual(public_calls,[])
            self.assertIn('RESTORE-UNKNOWN.json',[row[0]for row in logs])
            self.assertEqual((Path(td)/'guest-private-uncertain.tar').read_bytes(),b'private-tar-fixture')

    def test_actual_completion_callback_rejects_wrong_model(self):
        source,tree=load_source();callback=None
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant)and isinstance(node.value,str)and 'def observed(self,parser,value):'in node.value:callback=ast.parse(node.value)
        self.assertIsNotNone(callback)
        function=next(n for n in callback.body if isinstance(n,ast.FunctionDef))
        with tempfile.TemporaryDirectory()as td:
            ns=dict(json=json,os=__import__('os'),p=Path(td)/'raw.json',expected='Qwen/Qwen3-VL-8B-Instruct',original=lambda *a:'parsed')
            exec(compile(ast.Module(body=[function],type_ignores=[]),'<callback>','exec'),ns)
            client=types.SimpleNamespace(_redact_response=lambda v:v)
            with self.assertRaises(SystemExit):ns['observed'](client,None,dict(choices=[],model='restored-Qwen'))
            self.assertEqual(ns['observed'](client,None,dict(choices=[],model=ns['expected'])),'parsed')
            envelopes=list(Path(td).glob('completion-envelope-*.json'))
            self.assertEqual(len(envelopes),2)
            self.assertEqual(json.loads(envelopes[0].read_text())['model'],'restored-Qwen')

    def test_fixed_source_clocks_and_pins(self):
        source,tree=load_source()
        for token in ('__PREVIOUS_AUTO__','__REVIEWED_HELPER_B64__','__REVIEWED_HELPER_SHA256__'):self.assertEqual(source.count(token),1)
        self.assertIn('RuntimeMaxSec=540',source);self.assertIn('guest(command,570',source)
        self.assertIn('guest(\'sudo -n /usr/bin/python3 -I -B -c \'+shlex.quote(cleanup),245)',source)
        self.assertIn('min(1200,',source);self.assertIn('child.wait(timeout=5)',source)
        self.assertNotIn('1543415',source);self.assertNotIn('credential_b64',source)
        manifest=next(ast.literal_eval(n.value)for n in tree.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='MODEL_MANIFEST'for t in n.targets))
        ref=Path(__file__).parents[2]/'references/model-download-spec.json'
        self.assertEqual(manifest,json.loads(ref.read_bytes()));self.assertEqual(len(manifest['components']),14)
        compile(source,'driver','exec')
        compile(Path(__file__).with_name('run_qwen8_vllm_all38_r23.py').read_text(),'wrapper','exec')


if __name__=='__main__':unittest.main()
