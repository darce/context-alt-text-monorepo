#!/usr/bin/env python3
"""Generate the no-mutation root stage op for the bounded owner-custody procedure.

Coordinator-side only. Reads the reviewed procedure bytes from git, verifies them
against the pinned manifest, and writes BAKEOFF-LONG-WINDOW-NATIVE-R2.config.json
and BAKEOFF-LONG-WINDOW-NATIVE-R2.remote.py into --out-dir (no overwrite).
It never runs the generated program and never touches the VM, GPU or services.

Example: python3 build_long_window_native_r2.py --source <40-hex> --expect-ops 24 --out-dir <dir>
"""
import argparse
import ast
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

PROCEDURE_DIR = '.task-state/bakeoff-rounds-20261017/qualifications/owner-resume-start-r4'
MANIFEST_NAME = 'approved-scripts.json'
MANIFEST_SHA256 = 'cd399f1f0d55fd1dbf4eb980d0accbdb6b2ac27536f4f11a222b3262bdcbb495'
OWNER_WINDOW_SHA256 = '60c0cfdceedbf778be717300d7d0d5c071a07860be333abcd694e4e0c430281b'
OWNER_CUSTODY_SHA256 = 'e86b763b95ce9be67964b925c2f6ce7ea3c73ddbd4ababd70b4d36a95c407c2f'
SCRIPTS = frozenset(('capacity-read.sh', 'final-stop.sh', 'guest-read.sh', 'observe.py',
                     'owner-custody.py', 'owner-window.py', 'root-flow.sh'))
EXPECTED_NAMES = SCRIPTS | {MANIFEST_NAME}
STAGE = '/root/bakeoff-owner-long-window-20261020-cd399f1f0d55/procedure'
OLD_STAGE = '/root/owner-stop-contract-r3/procedure'
OLD_MANIFEST_SHA256 = '991aa72e923562bec93659190e87f9d223514da3073b424df5d36a60f1e77406'
CURRENT_STAGE = '/root/bakeoff-owner-long-window-20261019-45c86daf3bc3/procedure'
CURRENT_MANIFEST_SHA256 = '45c86daf3bc312eea23ab1382965b56dcbc1c97dd1c82070decc6ee617d3c5ca'
WINDOW = '/tmp/qwen-owner-window.rcqmefq9'
WINDOW_ID = '223eb2de-b63a-4b19-a31e-a34d07a8e187'
CONFIG_NAME = 'BAKEOFF-LONG-WINDOW-NATIVE-R2.config.json'
PROGRAM_NAME = 'BAKEOFF-LONG-WINDOW-NATIVE-R2.remote.py'

# Static root program. Constants and the embedded files are prepended by render_program.
PROGRAM_BODY = '''import base64,hashlib,importlib.util,json,os,pathlib,stat,sys,time,uuid
P=pathlib.Path
MAX=2*1024*1024
SCRIPTS=frozenset(('capacity-read.sh','final-stop.sh','guest-read.sh','observe.py','owner-custody.py','owner-window.py','root-flow.sh'))
NAMES=SCRIPTS|{'approved-scripts.json'}
EVIDENCE=None
QUALIFIED=None
def check(condition,message):
    if not condition: raise RuntimeError(message)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def read_bounded(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        s=os.fstat(fd)
        check(stat.S_ISREG(s.st_mode) and s.st_size<=MAX,'bounded regular file required: '+str(path))
        raw=b''
        while len(raw)<=MAX:
            chunk=os.read(fd,MAX+1-len(raw))
            if not chunk: break
            raw+=chunk
        check(len(raw)==s.st_size,'file changed during read: '+str(path))
        return raw,s
    finally: os.close(fd)
def regular(path,mode):
    raw,s=read_bounded(path)
    check(s.st_uid==0 and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==mode,'unexpected root file: '+str(path))
    return raw
def root_directory(path):
    s=os.lstat(path)
    check(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o700,'root private directory required: '+str(path))
def open_dir(path,dir_fd=None):
    return os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=dir_fd)
def fsync_dir(path):
    fd=open_dir(path)
    try: os.fsync(fd)
    finally: os.close(fd)
def write_new(dirfd,name,raw):
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o400,dir_fd=dirfd)
    try:
        view=memoryview(raw)
        while view: view=view[os.write(fd,view):]
        os.fsync(fd)
    finally: os.close(fd)
    os.fsync(dirfd)
def seal(name,value,base=None):
    raw=value if type(value) is bytes else (json.dumps(value,sort_keys=True,indent=2)+'\\n').encode()
    write_new(EVIDENCE if base is None else base,name,raw)
def verify_procedure(path,manifest_sha256):
    root_directory(path)
    check(set(os.listdir(path))==NAMES,'procedure inventory mismatch: '+path)
    manifest=regular(P(path)/'approved-scripts.json',0o400)
    check(sha(manifest)==manifest_sha256,'procedure manifest digest mismatch: '+path)
    pins=json.loads(manifest)
    check(type(pins) is dict and set(pins)==SCRIPTS,'procedure pin set mismatch: '+path)
    files={}
    for name in sorted(SCRIPTS):
        raw=regular(P(path)/name,0o400)
        check(sha(raw)==pins[name],'procedure pin mismatch: '+name)
        files[name]=sha(raw)
    return dict(manifest_sha256=manifest_sha256,files=files)
def decode_files():
    embedded=v['files']
    check(set(embedded)==NAMES,'embedded file set mismatch')
    files={name:base64.b64decode(embedded[name],validate=True) for name in embedded}
    manifest=files['approved-scripts.json']
    check(sha(manifest)==MANIFEST_SHA256,'embedded manifest digest mismatch')
    pins=json.loads(manifest)
    check(type(pins) is dict and set(pins)==SCRIPTS,'embedded pin set mismatch')
    for name in sorted(SCRIPTS): check(sha(files[name])==pins[name],'embedded pin mismatch: '+name)
    check(sha(files['owner-window.py'])==OWNER_WINDOW_SHA256,'embedded owner-window pin mismatch')
    return files
def validate_window():
    root_directory(WINDOW)
    window=json.loads(regular(P(WINDOW)/'window.json',0o400))
    check(window==dict(id=WINDOW_ID,path=WINDOW,procedure=OLD_STAGE),'window does not name the expected predecessor')
    check(len(list((P(WINDOW)/'ops').iterdir()))==EXPECT_OPS,'window operation count mismatch')
def tree(root):
    out={}
    def walk(path):
        with os.scandir(path) as entries: items=sorted(entries,key=lambda e:e.name)
        for entry in items:
            check(len(out)<4096,'window inventory budget exceeded')
            s=os.lstat(entry.path)
            check(not stat.S_ISLNK(s.st_mode),'symlink refused: '+entry.path)
            rel=os.path.relpath(entry.path,root)
            if stat.S_ISDIR(s.st_mode):
                out[rel]=dict(type='dir',ino=s.st_ino,mode=stat.S_IMODE(s.st_mode))
                walk(entry.path)
            else:
                raw,f=read_bounded(entry.path)
                out[rel]=dict(type='file',bytes=len(raw),ino=f.st_ino,mode=stat.S_IMODE(f.st_mode),sha256=sha(raw))
    walk(root)
    return out
def authority():
    paths=[P('/var/lib/acx-gpu/intent-authority.json')]
    paths+=sorted(P('/run/acx-write').glob('*/gpu-intent.json'))
    paths+=sorted(P('/var/lib/acx-gpu/intents').glob('*/gpu-intent.json'))
    check(len(paths)<=4096,'authority inventory budget exceeded')
    out={}
    for p in paths:
        raw,f=read_bounded(p)
        out[str(p)]=dict(bytes=len(raw),ino=f.st_ino,mode=stat.S_IMODE(f.st_mode),sha256=sha(raw))
    return out
def snapshot():
    return dict(window=tree(WINDOW),authority=authority())
def create_stage(files):
    parent=P(STAGE).parent
    check(parent.parent==P('/root'),'stage must be a direct child of /root')
    os.mkdir(parent,0o700)
    fsync_dir(str(parent.parent))
    os.mkdir(STAGE,0o700)
    fsync_dir(str(parent))
    sfd=open_dir(STAGE)
    try:
        for name in sorted(files):
            write_new(sfd,name,files[name])
            seal(name,files[name],QUALIFIED)
    finally: os.close(sfd)
def predecessor_proof(old):
    proof=dict(schema='acx-owner-procedure-predecessor/v1',window_id=WINDOW_ID,window_path=WINDOW,procedure=OLD_STAGE,
               manifest_sha256=old['manifest_sha256'],owner_window_sha256=old['files']['owner-window.py'],
               owner_custody_sha256=old['files']['owner-custody.py'])
    raw=(json.dumps(proof,sort_keys=True)+'\\n').encode()
    sfd=open_dir(STAGE)
    try: write_new(sfd,'procedure-predecessor.json',raw)
    finally: os.close(sfd)
    seal('procedure-predecessor.json',raw)
def load_custody():
    spec=importlib.util.spec_from_file_location('owner_custody_stage',P(STAGE)/'owner-custody.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check(P(module.__file__)==P(STAGE)/'owner-custody.py','custody module origin changed')
    return module
def check_predecessor(c):
    wfd,window=c.validate_window(WINDOW,WINDOW_ID)
    try: c.validate_procedure(wfd,window,STAGE)
    finally: os.close(wfd)
def readiness_check(c):
    paths=c.Paths('/run/acx-write','/var/lib/acx-gpu','/var/lib/acx-gpu/lifecycle.lock','/tmp',
                  writer_uid=10001,writer_gid=10001,controller_uid=1001,controller_gid=1001)
    # Floor None keeps only the newest authority record, so the view stays under the job budget.
    started=time.monotonic()
    status,view=c.native_job(lambda:c.view(paths,'stop',None),5)
    elapsed=time.monotonic()-started
    check(status==0 and view is not None,'read-only readiness view unknown')
    return dict(status=status,elapsed_seconds=round(elapsed,3),view_sha256=sha(json.dumps(view,sort_keys=True).encode()))
def run():
    global EVIDENCE,QUALIFIED
    check(os.getuid()==os.geteuid()==0,'root required')
    evidence=P('/root')/('bakeoff-long-window-native-r2-'+uuid.uuid4().hex)
    os.mkdir(evidence,0o700)
    EVIDENCE=open_dir(str(evidence))
    os.mkdir('qualified-source',0o700,dir_fd=EVIDENCE)
    QUALIFIED=open_dir('qualified-source',dir_fd=EVIDENCE)
    validate_window()
    old=verify_procedure(OLD_STAGE,OLD_MANIFEST_SHA256)
    current=verify_procedure(CURRENT_STAGE,CURRENT_MANIFEST_SHA256)
    seal('predecessors.json',dict(old=old,current=current))
    files=decode_files()
    before=snapshot()
    create_stage(files)
    seal('stage-verified.json',verify_procedure(STAGE,MANIFEST_SHA256))
    predecessor_proof(old)
    custody=load_custody()
    check_predecessor(custody)
    readiness=readiness_check(custody)
    seal('readiness.json',readiness)
    after=snapshot()
    seal('inventory-before.json',before)
    seal('inventory-after.json',after)
    check(json.dumps(before['window'],sort_keys=True)==json.dumps(after['window'],sort_keys=True),'window inventory changed; retain evidence')
    check(json.dumps(before['authority'],sort_keys=True)==json.dumps(after['authority'],sort_keys=True),'authority inventory changed; retain evidence')
    terminal=dict(status='ROOT_STAGE_TERMINAL',exit_code=0,evidence=str(evidence),stage=STAGE,source=SOURCE,
                  manifest_sha256=MANIFEST_SHA256,readiness=readiness,window_unchanged=True,authority_unchanged=True,GPU_calls=0)
    seal('terminal.json',terminal)
    sys.stdout.write(json.dumps(terminal,sort_keys=True,indent=2)+'\\n')
run()
'''


class Refused(RuntimeError):
    pass


def refuse(condition, message):
    if not condition:
        raise Refused(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_tree(source):
    """Return the procedure directory as {name: bytes}, read with git show."""
    listing = subprocess.run(['git', 'ls-tree', f'{source}:{PROCEDURE_DIR}'],
                             capture_output=True, text=True, check=True).stdout
    tree = {}
    for line in listing.splitlines():
        meta, name = line.split('\t', 1)
        mode, kind, _ = meta.split()
        refuse(kind == 'blob' and mode in ('100644', '100755'), 'non-regular procedure entry: ' + name)
        tree[name] = subprocess.run(['git', 'show', f'{source}:{PROCEDURE_DIR}/{name}'],
                                    capture_output=True, check=True).stdout
    return tree


def verify_tree(tree):
    names = set(tree)
    if names != EXPECTED_NAMES:
        raise Refused('procedure file set must be exactly 8 files; missing %s, extra %s'
                      % (sorted(EXPECTED_NAMES - names), sorted(names - EXPECTED_NAMES)))
    manifest = tree[MANIFEST_NAME]
    refuse(sha(manifest) == MANIFEST_SHA256, 'manifest digest mismatch')
    pins = json.loads(manifest)
    refuse(type(pins) is dict and set(pins) == SCRIPTS and len(pins) == 7,
           'pins must be exactly the 7 procedure scripts')
    for name in sorted(SCRIPTS):
        refuse(sha(tree[name]) == pins[name], 'pin mismatch: ' + name)
    refuse(pins['owner-window.py'] == OWNER_WINDOW_SHA256 and pins['owner-custody.py'] == OWNER_CUSTODY_SHA256,
           'fixed owner-custody pins changed')
    return tree


def render_program(source, expect_ops, files):
    constants = [('SOURCE', source), ('EXPECT_OPS', expect_ops), ('STAGE', STAGE),
                 ('OLD_STAGE', OLD_STAGE), ('OLD_MANIFEST_SHA256', OLD_MANIFEST_SHA256),
                 ('CURRENT_STAGE', CURRENT_STAGE), ('CURRENT_MANIFEST_SHA256', CURRENT_MANIFEST_SHA256),
                 ('WINDOW', WINDOW), ('WINDOW_ID', WINDOW_ID), ('MANIFEST_SHA256', MANIFEST_SHA256),
                 ('OWNER_WINDOW_SHA256', OWNER_WINDOW_SHA256)]
    header = ''.join(f'{name}={value!r}\n' for name, value in constants)
    embedded = {name: base64.b64encode(raw).decode() for name, raw in sorted(files.items())}
    program = header + f"v={{'files':{embedded!r}}}\n" + PROGRAM_BODY
    ast.parse(program)
    return program


def write_output(path, raw):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError as error:
        raise Refused('output exists; no overwrite: ' + str(path)) from error
    try:
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def build(source, expect_ops, out_dir, load_tree=git_tree):
    refuse(re.fullmatch(r'[0-9a-f]{40}', source or '') is not None, 'full 40-hex source commit required')
    refuse(type(expect_ops) is int and expect_ops > 0, 'positive --expect-ops required')
    files = verify_tree(load_tree(source))
    program = render_program(source, expect_ops, files)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    program_path = (out / PROGRAM_NAME).absolute()
    config_path = out / CONFIG_NAME
    for path in (program_path, config_path):
        refuse(not os.path.lexists(path), 'output exists; no overwrite: ' + str(path))
    config = dict(name='BAKEOFF-LONG-WINDOW-NATIVE-R2', owner='Bakeoff_LongLive',
                  unit='workbay-bakeoff-long-window-native-r2-20261020.scope', model=None, cpu=0.5,
                  memory=2147483648, forecast=1073741824, source=source, timeout=120,
                  role='qualified_root_bounded_view_stage_no_window_mutation', program=str(program_path))
    write_output(program_path, program.encode())
    write_output(config_path, (json.dumps(config, indent=2, sort_keys=True) + '\n').encode())
    return config_path, program_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', required=True, help='40-hex commit that holds the reviewed procedure')
    parser.add_argument('--expect-ops', type=int, required=True, help='operation count the window must hold')
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config_path, program_path = build(args.source, args.expect_ops, args.out_dir)
    except (Refused, OSError, subprocess.CalledProcessError, ValueError) as error:
        parser.exit(2, str(error) + '\n')
    print(config_path)
    print(program_path)


if __name__ == '__main__':
    main()
