#!/usr/bin/env python3
"""Generate the same-window checkpoint op for the bounded owner-custody stage.

Coordinator-side only. Writes BAKEOFF-WINDOW-CHECKPOINT-R2.config.json and
BAKEOFF-WINDOW-CHECKPOINT-R2.remote.py into --out-dir (no overwrite). It never
runs the generated program and never touches the VM, GPU or services.

The stage, window and manifest constants come from build_long_window_native_r2.py,
imported by path so they cannot drift from the restage generator.

Example: python3 build_window_checkpoint_r2.py --expect-ops 24 --previous-op <uuid> --out-dir <dir>
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import uuid
from pathlib import Path

_RESTAGE_PATH = Path(__file__).absolute().parent / 'build_long_window_native_r2.py'
_restage_spec = importlib.util.spec_from_file_location('build_long_window_native_r2', _RESTAGE_PATH)
restage = importlib.util.module_from_spec(_restage_spec)
_restage_spec.loader.exec_module(restage)

STAGE = restage.STAGE
OLD_STAGE = restage.OLD_STAGE
WINDOW = restage.WINDOW
WINDOW_ID = restage.WINDOW_ID
MANIFEST_SHA256 = restage.MANIFEST_SHA256
OWNER_CUSTODY_SHA256 = restage.OWNER_CUSTODY_SHA256
CONFIG_NAME = 'BAKEOFF-WINDOW-CHECKPOINT-R2.config.json'
PROGRAM_NAME = 'BAKEOFF-WINDOW-CHECKPOINT-R2.remote.py'
# Same transport shape as BAKEOFF-LONG-WINDOW-NATIVE-R2 (restage generator).
OWNER = 'Bakeoff_LongLive'
UNIT = 'workbay-bakeoff-window-checkpoint-r2-20261020.scope'
ROLE = 'qualified_root_same_window_checkpoint_bounded_stage'
CPU = 0.5
MEMORY = 2147483648
FORECAST = 1073741824
TIMEOUT = 120
MAX_EXPECT_OPS = 32

# Static root program. Header constants are prepended by render_program.
# The checkpoint section mirrors the R1 argv chain; the R1 artifact is not in this tree.
PROGRAM_BODY = r'''import collections,hashlib,importlib.util,json,os,pathlib,stat,subprocess,sys,uuid
P=pathlib.Path
MAX=2*1024*1024
ROOT_UID=0
TREE_BUDGET=4096
OPERATION_BUDGET=32
CHECKPOINT_SECONDS=45
SCRIPTS=frozenset(('capacity-read.sh','final-stop.sh','guest-read.sh','observe.py','owner-custody.py','owner-window.py','root-flow.sh'))
PREDECESSOR='procedure-predecessor.json'
STAGE_NAMES=SCRIPTS|{'approved-scripts.json',PREDECESSOR}
OWNER_WINDOW=['sudo','-n','-H','-u','ubuntu','sudo','-n','/usr/bin/python3','-I','-B',STAGE+'/owner-window.py']
CHECKPOINT_ARGV=OWNER_WINDOW+['checkpoint',WINDOW,WINDOW_ID]
RECONCILE_ARGV=OWNER_WINDOW+['reconcile',WINDOW,WINDOW_ID]
BASE=None
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
    check(s.st_uid==ROOT_UID and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==mode,'unexpected root file: '+str(path))
    return raw
def root_directory(path,mode=0o700):
    s=os.lstat(path)
    check(stat.S_ISDIR(s.st_mode) and s.st_uid==ROOT_UID and stat.S_IMODE(s.st_mode)==mode,'root directory required: '+str(path))
def bounded_names(path,limit):
    names=[]
    with os.scandir(path) as entries:
        for entry in entries:
            check(len(names)<limit,'bounded directory over budget: '+str(path))
            names.append(entry.name)
    return sorted(names)
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
    raw=value if type(value) is bytes else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    write_new(EVIDENCE if base is None else base,name,raw)
def setup():
    global BASE,EVIDENCE,QUALIFIED
    check(os.getuid()==os.geteuid()==ROOT_UID,'root required')
    BASE=P('/root')/('bakeoff-window-checkpoint-r2-'+uuid.uuid4().hex)
    os.mkdir(BASE,0o700)
    fsync_dir('/root')
    EVIDENCE=open_dir(str(BASE))
    os.mkdir('qualified-source',0o700,dir_fd=EVIDENCE)
    QUALIFIED=open_dir('qualified-source',dir_fd=EVIDENCE)
def verify_stage(path):
    """Read-only. The stage must already exist; this program never creates it."""
    root_directory(path)
    check(set(bounded_names(path,len(STAGE_NAMES)))==STAGE_NAMES,'stage must hold exactly the 9 pinned entries: '+str(path))
    manifest=regular(P(path)/'approved-scripts.json',0o400)
    check(sha(manifest)==MANIFEST_SHA256,'stage manifest digest mismatch')
    pins=json.loads(manifest)
    check(type(pins) is dict and set(pins)==SCRIPTS and len(pins)==7,'stage pins must be exactly the 7 scripts')
    files={name:regular(P(path)/name,0o400) for name in sorted(STAGE_NAMES)}
    for name in sorted(SCRIPTS): check(sha(files[name])==pins[name],'stage pin mismatch: '+name)
    check(pins['owner-custody.py']==OWNER_CUSTODY_SHA256,'owner-custody pin changed')
    return files
def qualify(files):
    for name in sorted(files): seal(name,files[name],QUALIFIED)
def guard_window():
    root_directory(WINDOW)
    raw=regular(P(WINDOW)/'window.json',0o400)
    check(json.loads(raw)==dict(id=WINDOW_ID,path=WINDOW,procedure=OLD_STAGE),'window does not name the expected procedure')
    check(len(bounded_names(P(WINDOW)/'ops',EXPECT_OPS))==EXPECT_OPS,'window operation count mismatch')
    return raw
def load_custody(path):
    check(sha(regular(path,0o400))==OWNER_CUSTODY_SHA256,'qualified owner-custody pin mismatch')
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('owner_custody_qualified',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check(P(module.__file__)==P(path),'custody module origin changed')
    return module
def newest_published(c,wfd):
    """checkpoint_floor-equivalent: PREVIOUS must be the one published candidate with the highest sequence."""
    known=c.known_candidates(wfd)
    check(PREVIOUS in known,'PREVIOUS is not a known candidate')
    ops=c.subdir(wfd,'ops')
    try:
        published={}
        for op in bounded_names(ops,OPERATION_BUDGET):
            f=c.subdir(ops,op)
            try: result=c.load_json(f,'result.json')
            finally: os.close(f)
            if result['outcome']=='published':
                check(op in known,'published operation lacks a candidate: '+op)
                published[op]=known[op]['sequence']
    finally: os.close(ops)
    check(PREVIOUS in published,'PREVIOUS is not a published operation')
    check(len(set(published.values()))==len(published),'published candidate sequences conflict')
    check(published[PREVIOUS]==max(published.values()),'PREVIOUS is not the newest published operation')
    return published[PREVIOUS]
def custody_proof(c):
    wfd,window=c.validate_window(WINDOW,WINDOW_ID)
    try:
        c.validate_procedure(wfd,window,STAGE)
        return newest_published(c,wfd)
    finally: os.close(wfd)
def live_paths(c):
    return c.Paths('/run/acx-write','/var/lib/acx-gpu','/var/lib/acx-gpu/lifecycle.lock','/tmp',
                   writer_uid=10001,writer_gid=10001,controller_uid=1001,controller_gid=1001)
def readiness(c,paths,floor):
    """Read-only. Every fence must already exist with its exact role; nothing is created."""
    lock=P(WINDOW)/'window.lock'
    fences=[]
    for p in [lock]+paths.fences('auto'):
        s=os.lstat(p)
        check(c._checkpoint_fence(paths,p,lock,s),'missing or unsafe checkpoint fence: '+str(p))
        fences.append(dict(path=str(p),dev=s.st_dev,ino=s.st_ino,uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode),nlink=s.st_nlink,size=s.st_size))
    view,_=c.checkpoint_view(paths,floor)
    raw=json.dumps(view,sort_keys=True).encode()
    seal('qualified-read-only-readiness.json',dict(fences=fences,state_sha256=sha(raw),floor=floor,previous=PREVIOUS,no_mutation=True,not_a_locked_admission=True))
def tree(root):
    out={}
    def walk(path):
        with os.scandir(path) as entries: items=sorted(entries,key=lambda e:e.name)
        for entry in items:
            check(len(out)<TREE_BUDGET,'window inventory budget exceeded')
            s=os.lstat(entry.path)
            check(not stat.S_ISLNK(s.st_mode),'symlink refused: '+entry.path)
            rel=os.path.relpath(entry.path,str(root))
            if stat.S_ISDIR(s.st_mode):
                out[rel]=dict(type='dir',ino=s.st_ino,mode=stat.S_IMODE(s.st_mode))
                walk(entry.path)
            else:
                raw,f=read_bounded(entry.path)
                out[rel]=dict(type='file',bytes=len(raw),ino=f.st_ino,mode=stat.S_IMODE(f.st_mode),sha256=sha(raw))
    walk(str(root))
    return out
def multiset(inventory):
    """Path-free content identity, so an archive move keeps every entry's multiset count."""
    return collections.Counter((v['type'],v.get('bytes'),v.get('sha256'),v['mode']) for v in inventory.values())
def current(c,paths,floor):
    view,_=c.checkpoint_view(paths,floor)
    return view
def before_inventory(c,paths,floor):
    before=dict(window=tree(WINDOW),current=current(c,paths,floor),ops_previous=tree(P(WINDOW)/'ops'/PREVIOUS))
    seal('before-window.json',before['window'])
    seal('before-current.json',before['current'])
    seal('before-ops-previous.json',before['ops_previous'])
    return before
def run_owner_window(argv,stem):
    """One owner-window command: exclusive evidence files, fixed wait, no signal and no retry on timeout."""
    with open(P(BASE)/(stem+'.stdout'),'xb') as out, open(P(BASE)/(stem+'.stderr'),'xb') as err:
        child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=out,stderr=err)
        try: rc=child.wait(timeout=CHECKPOINT_SECONDS)
        except subprocess.TimeoutExpired:
            seal('UNKNOWN.json',dict(command=stem,argv=argv,wait_seconds=CHECKPOINT_SECONDS,signal=None,retry=False))
            raise SystemExit(124)
    return rc,read_bounded(P(BASE)/(stem+'.stdout'))[0]
def check_receipt(receipt):
    check(type(receipt) is dict and receipt.get('window_id')==WINDOW_ID,'checkpoint receipt names another window')
    check(receipt.get('previous')==PREVIOUS and PREVIOUS in receipt.get('retained',[]),'checkpoint receipt does not retain PREVIOUS')
    check(receipt.get('durable') is True,'checkpoint receipt is not durable')
def after_checkpoint(c,paths,floor,before,window_raw,receipt):
    after=tree(WINDOW)
    seal('after-window.json',after)
    seal('checkpoint-receipt.json',receipt)
    check_receipt(receipt)
    check(current(c,paths,floor)==before['current'],'authority or publications changed; retain evidence')
    check(tree(P(WINDOW)/'ops'/PREVIOUS)==before['ops_previous'],'ops/PREVIOUS inventory changed; retain evidence')
    check(not (multiset(before['window'])-multiset(after)),'window byte multiset not preserved; retain evidence')
    check(len(bounded_names(P(WINDOW)/'ops',OPERATION_BUDGET))==len(receipt['retained']),'active operation count differs from retained')
    check(regular(P(WINDOW)/'window.json',0o400)==window_raw,'window.json changed')
def run():
    setup()
    qualify(verify_stage(STAGE))
    window_raw=guard_window()
    custody=load_custody(str(P(BASE)/'qualified-source'/'owner-custody.py'))
    floor=custody_proof(custody)
    paths=live_paths(custody)
    readiness(custody,paths,floor)
    before=before_inventory(custody,paths,floor)
    rc,out=run_owner_window(CHECKPOINT_ARGV,'checkpoint')
    check(rc==0,'checkpoint exit status '+str(rc))
    receipt=json.loads(out)
    after_checkpoint(custody,paths,floor,before,window_raw,receipt)
    reconcile_rc,reconciled=run_owner_window(RECONCILE_ARGV,'reconcile')
    text=reconciled.decode().strip()
    seal('reconcile.json',dict(returncode=reconcile_rc,stdout=text))
    check(reconcile_rc==0 and text==PREVIOUS,'reconcile did not print PREVIOUS')
    retained=receipt['retained']
    terminal=dict(status='ROOT_QUALIFICATION_TERMINAL',exit_code=0,evidence=str(BASE),stage=STAGE,window_id=WINDOW_ID,
                  previous=PREVIOUS,expect_ops=EXPECT_OPS,retained=retained,archived=receipt['archived'],
                  slots_free=OPERATION_BUDGET-len(retained),GPU_calls=0)
    seal('terminal.json',terminal)
    sys.stdout.write(json.dumps(terminal,sort_keys=True)+'\n')
run()
'''


class Refused(RuntimeError):
    pass


def refuse(condition, message):
    if not condition:
        raise Refused(message)


def canonical_uuid(text):
    try:
        return str(uuid.UUID(text)) == text
    except (TypeError, ValueError):
        return False


def render_program(previous_op, expect_ops):
    constants = [('STAGE', STAGE), ('OLD_STAGE', OLD_STAGE), ('WINDOW', WINDOW), ('WINDOW_ID', WINDOW_ID),
                 ('MANIFEST_SHA256', MANIFEST_SHA256), ('OWNER_CUSTODY_SHA256', OWNER_CUSTODY_SHA256),
                 ('PREVIOUS', previous_op), ('EXPECT_OPS', expect_ops)]
    header = ''.join(f'{name}={value!r}\n' for name, value in constants)
    program = header + PROGRAM_BODY
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


def build(expect_ops, previous_op, out_dir, source=None):
    refuse(type(expect_ops) is int and 1 <= expect_ops <= MAX_EXPECT_OPS, 'integer --expect-ops between 1 and 32 required')
    refuse(canonical_uuid(previous_op), 'canonical --previous-op UUID required')
    refuse(source is None or re.fullmatch(r'[0-9a-f]{40}', source) is not None, 'full 40-hex --source commit required when given')
    program = render_program(previous_op, expect_ops)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    program_path = (out / PROGRAM_NAME).absolute()
    config_path = out / CONFIG_NAME
    for path in (program_path, config_path):
        refuse(not os.path.lexists(path), 'output exists; no overwrite: ' + str(path))
    config = dict(name='BAKEOFF-WINDOW-CHECKPOINT-R2', owner=OWNER, unit=UNIT, model=None, cpu=CPU,
                  memory=MEMORY, forecast=FORECAST, source=source, timeout=TIMEOUT, role=ROLE,
                  program=str(program_path))
    write_output(program_path, program.encode())
    write_output(config_path, (json.dumps(config, indent=2, sort_keys=True) + '\n').encode())
    return config_path, program_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--expect-ops', type=int, required=True, help='operation count the window must hold (1-32)')
    parser.add_argument('--previous-op', required=True,
                        help='canonical UUID of the newest published operation (the checkpoint predecessor)')
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--source', default=None,
                        help='optional 40-hex commit recorded in the config (the restage source is not in this tree)')
    args = parser.parse_args(argv)
    try:
        config_path, program_path = build(args.expect_ops, args.previous_op, args.out_dir, args.source)
    except (Refused, OSError, ValueError) as error:
        parser.exit(2, str(error) + '\n')
    print(config_path)
    print(program_path)


if __name__ == '__main__':
    main()
