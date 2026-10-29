"""Scoped contract tests; managed producers are absent in the source archive.

Fake Make implements the coordinator-verified CLI, with real Git worktrees.
Fake transport's spec is only a test fixture, not a WorkBay schema claim.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).with_name("build_review_packet.py")
TEST_CMD = "LC_ALL=C uv run --no-project --with pytest python -m pytest scripts/review/test_build_review_packet.py -q -p no:cacheprovider"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def lane(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    (root / "code.txt").write_text("before\n")
    (root / ".gitignore").write_text(".task-state/\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    git(root, "checkout", "-b", "feature/foo")
    (root / "code.txt").write_text("after\n")
    git(root, "commit", "-am", "subject")
    git(root, "checkout", "main")
    make = tmp_path / "make-fake"
    make.write_text(
        "#!/usr/bin/env python3\n"
        + """import hashlib,json,os,pathlib,subprocess,sys
root=pathlib.Path.cwd()
target=sys.argv[1]
opts=dict(arg.split('=',1) for arg in sys.argv[2:])
def git(*a):
 return subprocess.check_output(['git','-C',str(root),*a],text=True).strip()
with (root/'.task-state/calls').open('a') as f: f.write(target+'\\n')
if os.environ.get('FAIL_STEP')==target:
 print('primitive failed',file=sys.stderr);sys.exit(7)
if target=='review-stage':
 tip=git('rev-parse',opts['SUBJECT'])
 wt=pathlib.Path(opts.get('REV_WORKTREE',str(root.parent/'review-wt')))
 branch='review/'+opts['SLUG']+'-'+opts['REV']
 subprocess.run(['git','-C',str(root),'worktree','add','-b',branch,str(wt),'main'],check=True,stdout=subprocess.DEVNULL)
 rel='docs/reviews/_input-'+opts['SLUG']+'-'+tip[:9]+'.patch'
 patch=wt/rel;patch.parent.mkdir(parents=True,exist_ok=True)
 patch.write_bytes(subprocess.check_output(['git','-C',str(root),'diff','main...'+tip]))
 subprocess.run(['git','-C',str(wt),'add',rel],check=True)
 subprocess.run(['git','-C',str(wt),'commit','-m','stage'],check=True,stdout=subprocess.DEVNULL)
 side=wt/'.task-state/secret-sidecar.json';side.parent.mkdir();side.write_text('DO-NOT-LEAK-EXPECTED-POR')
 print(json.dumps(dict(ok=True,patch=str(patch),por_sidecar=str(side),rev_branch=branch,staged_commit=git('-C',str(wt),'rev-parse','HEAD'),subject_tip=tip,worktree=str(wt))))
elif target=='review-harvest':
 wt=opts['WORKTREE'];doc=opts['DOC']
 subprocess.run(['git','-C',wt,'add',doc],check=True)
 subprocess.run(['git','-C',wt,'commit','-m','review'],check=True,stdout=subprocess.DEVNULL)
elif target=='review-adjudicate':
 p=root/'.task-state/review-adjudication'/ (opts['SUBJECT']+'.json')
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'subject_tip':git('rev-parse',opts['SUBJECT'])}))
elif target!='merge-gate': sys.exit(8)
"""
    )
    make.chmod(0o755)
    remote = tmp_path / "remote-fake"
    remote.write_text(
        "#!/usr/bin/env python3\n"
        + """import hashlib,json,os,pathlib,subprocess,sys,time
spec=json.loads(pathlib.Path(sys.argv[sys.argv.index('--agent-spec')+1]).read_text())
wt=pathlib.Path(spec['worktree'])
count=wt.parent/'remote-count'
count.write_text(str(int(count.read_text() if count.exists() else '0')+1))
if os.environ.get('TRANSPORT_SLEEP'): time.sleep(5)
if os.environ.get('TRANSPORT_FAIL'): sys.exit(23)
if os.environ.get('MOVE_TIP'):
 subprocess.run(['git','-C',str(wt),'update-ref','refs/heads/feature/foo','main'],check=True)
brief=pathlib.Path(spec['brief']).read_text()
assert 'DO-NOT-LEAK' not in brief and 'por_sidecar' not in brief
patch=brief.split('<staged-patch>\\n',1)[1].split('</staged-patch>',1)[0].encode()
lines=patch.decode().splitlines();samples=[]
for n in [41,173]+list(range(1,len(lines)+1)):
 if n<=len(lines) and lines[n-1].strip() and [str(n),lines[n-1]] not in samples:
  samples.append([str(n),lines[n-1]])
 if len(samples)==2: break
por=dict(file_count=sum(x.startswith('+++ ') for x in lines),line_count=len(lines),md5=hashlib.md5(patch).hexdigest(),sample_lines=dict(samples))
verdict=os.environ.get('VERDICT','MERGE')
text='VERDICT: '+verdict+'\\nPOR: '+json.dumps(por)+'\\nMEDIUM: improve names\\n'
if os.environ.get('MALFORMED'): text='VERDICT: MERGE\\nPOR: {}\\n'
doc=wt/spec['doc'];doc.parent.mkdir(parents=True,exist_ok=True);doc.write_text(text)
if os.environ.get('EXTRA_WRITE'): (wt/'code.txt').write_text('reviewer edited source')
if os.environ.get('LOST_RESPONSE'): sys.exit(23)
"""
    )
    remote.chmod(0o755)
    template = tmp_path / "spec-template.json"
    template.write_text(
        json.dumps(
            {key: "{" + key + "}" for key in ("backend", "model", "effort", "speed", "brief", "doc", "worktree")}
        )
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"argv": [str(remote), "--agent-spec", "{agent_spec}"], "agent_spec_template": str(template)})
    )
    context = tmp_path / "context.txt"
    context.write_text("Prior art decisions20545/17577: only pipeline adjudication authorizes MERGE.\n")
    return dict(root=root, make=make, config=config, context=context, tmp=tmp_path)


def invoke(lane, mode="prepare", extra=(), env=None):
    args = [
        sys.executable,
        str(SCRIPT),
        mode,
        "--repo",
        str(lane["root"]),
        "--packet",
        str(lane["root"] / ".task-state/packet"),
        "--subject",
        "feature/foo",
        "--slug",
        "foo",
        "--config",
        str(lane["config"]),
        "--context",
        str(lane["context"]),
        "--make",
        str(lane["make"]),
        *extra,
    ]
    return subprocess.run(args, text=True, capture_output=True, env={**os.environ, **(env or {})})


def receipt(lane):
    return json.loads((lane["root"] / ".task-state/packet/receipt.json").read_text())


def calls(lane):
    return (lane["root"] / ".task-state/calls").read_text().splitlines()


def test_dry_run_does_no_io_or_spend(lane):
    result = invoke(lane, "check")
    assert result.returncode == 0, result.stderr
    assert not (lane["root"] / ".task-state").exists()
    plan = json.loads(result.stdout)
    assert plan["selection"] == dict(backend="codex-remote", model="gpt-6.1-sol", effort="xhigh", speed="fast")
    assert "review-stage" in str(plan["commands"])


def test_prepare_binds_patch_and_git_and_hides_sidecar(lane):
    result = invoke(lane)
    assert result.returncode == 0, result.stderr
    r = receipt(lane)
    assert r["subject_tip"] == git(lane["root"], "rev-parse", "feature/foo")
    assert r["subject_tree"] == git(lane["root"], "rev-parse", "feature/foo^{tree}")
    assert r["integration_tip"] == git(lane["root"], "rev-parse", "main")
    assert r["base"] == git(lane["root"], "merge-base", "main", "feature/foo")
    patch = Path(r["stage"]["patch"]).read_bytes()
    assert r["patch_sha256"] == hashlib.sha256(patch).hexdigest()
    brief = Path(r["artifacts"]["brief"]).read_text()
    assert "decisions20545/17577" in brief
    assert "Expected POR" not in brief and "DO-NOT-LEAK" not in brief and "por_sidecar" not in brief
    assert calls(lane) == ["review-stage"]


def test_resume_executes_pipeline_once_and_records_commands(lane):
    assert invoke(lane).returncode == 0
    result = invoke(lane, "resume")
    assert result.returncode == 0, result.stderr
    r = receipt(lane)
    assert r["status"] == "passed"
    assert calls(lane) == ["review-stage", "review-harvest", "review-adjudicate", "merge-gate"]
    assert [s["name"] for s in r["steps"]] == ["stage", "remote", "harvest", "adjudicate", "gate"]
    assert all(s["exit_code"] == 0 and s["outcome"] == "passed" and s["argv"] for s in r["steps"])
    assert Path(r["artifacts"]["review_doc"]).exists()
    assert invoke(lane, "resume").returncode == 0
    assert (lane["tmp"] / "remote-count").read_text() == "1"


@pytest.mark.parametrize("env,error", [({"TRANSPORT_FAIL": "1"}, "transport"), ({"MALFORMED": "1"}, "POR")])
def test_remote_failures_are_loud_and_resume_never_redispatches(lane, env, error):
    result = invoke(lane, "execute", env=env)
    assert result.returncode != 0 and error.lower() in result.stderr.lower()
    assert receipt(lane)["status"] == "failed"
    assert calls(lane) == ["review-stage"]
    assert invoke(lane, "resume").returncode != 0
    assert (lane["tmp"] / "remote-count").read_text() == "1"


def test_stale_tip_prevents_remote_and_post_remote_gate(lane):
    assert invoke(lane).returncode == 0
    git(lane["root"], "update-ref", "refs/heads/feature/foo", "main")
    result = invoke(lane, "resume")
    assert result.returncode != 0 and "stale" in result.stderr.lower()
    assert not (lane["tmp"] / "remote-count").exists()


@pytest.mark.parametrize("dirty", ["tracked", "staged", "untracked"])
def test_dirty_review_checkout_stops_before_first_remote_and_can_resume(lane, dirty):
    assert invoke(lane).returncode == 0
    wt = Path(receipt(lane)["stage"]["worktree"])
    path = wt / ("notes.txt" if dirty == "untracked" else "code.txt")
    original = path.read_bytes() if path.exists() else None
    user_bytes = b"user work must survive\x00\n"
    path.write_bytes(user_bytes)
    if dirty == "staged":
        git(wt, "add", "code.txt")
    status = git(wt, "status", "--porcelain", "--untracked-files=all")

    result = invoke(lane, "resume")

    assert path.read_bytes() == user_bytes
    assert git(wt, "status", "--porcelain", "--untracked-files=all") == status
    assert not (lane["tmp"] / "remote-count").exists(), result.stderr
    assert result.returncode != 0 and "clean" in result.stderr.lower()
    assert calls(lane) == ["review-stage"]
    assert not any(step["name"] == "remote" for step in receipt(lane)["steps"])
    assert receipt(lane)["status"] == "failed"

    # Reconcile only fixture-owned dirt, then reuse the prepared packet.
    if original is None:
        path.unlink()
    else:
        path.write_bytes(original)
        if dirty == "staged":
            git(wt, "add", "code.txt")
    result = invoke(lane, "resume")
    assert result.returncode == 0, result.stderr
    assert (lane["tmp"] / "remote-count").read_text() == "1"


@pytest.mark.parametrize("mode", ["check", "execute"])
@pytest.mark.parametrize("doc", ["docs/reviews/./foo-r1.md", "docs/reviews//foo-r1.md"])
def test_noncanonical_doc_is_rejected_before_stage_or_remote(lane, mode, doc):
    result = invoke(lane, mode, extra=("--doc", doc))

    assert not (lane["tmp"] / "remote-count").exists(), result.stderr
    assert result.returncode != 0 and "DOC" in result.stderr
    assert not (lane["root"] / ".task-state").exists()


def test_tip_moves_during_remote_refuses_harvest(lane):
    result = invoke(lane, "execute", env={"MOVE_TIP": "1"})
    assert result.returncode != 0 and "stale" in result.stderr.lower()
    assert calls(lane) == ["review-stage"]


@pytest.mark.parametrize("artifact", ["patch", "brief", "agent_spec"])
def test_prepared_input_tamper_is_rejected(lane, artifact):
    assert invoke(lane).returncode == 0
    r = receipt(lane)
    path = r["stage"]["patch"] if artifact == "patch" else r["artifacts"][artifact]
    with Path(path).open("a") as f:
        f.write("tamper")
    result = invoke(lane, "resume")
    assert result.returncode != 0, result.stdout
    assert not (lane["tmp"] / "remote-count").exists()


@pytest.mark.parametrize("step", ["review-stage", "review-harvest", "review-adjudicate", "merge-gate"])
def test_primitive_failures_stop_chain_and_are_recorded(lane, step):
    result = invoke(lane, "execute", env={"FAIL_STEP": step})
    assert result.returncode != 0
    r = receipt(lane)
    assert r["status"] == "failed"
    assert r["steps"][-1]["exit_code"] == 7
    assert r["steps"][-1]["outcome"] == "failed"
    if step != "merge-gate":
        assert "merge-gate" not in calls(lane)


def test_adjudication_failure_can_resume_without_second_spend(lane):
    assert invoke(lane, "execute", env={"FAIL_STEP": "review-adjudicate"}).returncode != 0
    result = invoke(lane, "resume")
    assert result.returncode == 0, result.stderr
    assert (lane["tmp"] / "remote-count").read_text() == "1"
    assert calls(lane).count("review-harvest") == 1


def test_revise_is_harvested_and_adjudicated_but_never_passes_gate(lane):
    result = invoke(lane, "execute", env={"VERDICT": "REVISE"})
    assert result.returncode != 0
    assert calls(lane) == ["review-stage", "review-harvest", "review-adjudicate"]
    assert receipt(lane)["status"] == "revise"


@pytest.mark.parametrize(
    "args", [("--backend", "grok-remote"), ("--rev", "3"), ("--backend", "claude-remote"), ("--doc", "../escape.md")]
)
def test_invalid_selection_or_doc_is_rejected_before_stage(lane, args):
    assert invoke(lane, "execute", extra=args).returncode != 0
    assert not (lane["tmp"] / "remote-count").exists()
    assert not (lane["root"] / ".task-state/calls").exists()


def test_explicit_opus_selection_is_bound(lane):
    result = invoke(lane, extra=("--backend", "claude-remote", "--model", "claude-opus-5-5"))
    assert result.returncode == 0, result.stderr
    assert receipt(lane)["selection"]["backend"] == "claude-remote"


def test_optional_context_io_and_missing_executable_fail_before_spend(lane):
    lane["context"].unlink()
    result = invoke(lane, "execute")
    assert result.returncode != 0 and "context" in result.stderr.lower()
    assert not (lane["tmp"] / "remote-count").exists()


def test_missing_transport_exec_is_recorded(lane):
    assert invoke(lane).returncode == 0
    config = json.loads(lane["config"].read_text())
    Path(config["argv"][0]).unlink()
    result = invoke(lane, "resume")
    assert result.returncode != 0 and "transport" in result.stderr.lower()
    assert receipt(lane)["steps"][-1]["outcome"] == "failed"


def test_passed_packet_rejects_review_doc_tamper(lane):
    assert invoke(lane, "execute").returncode == 0
    doc = Path(receipt(lane)["artifacts"]["review_doc"])
    doc.write_text(doc.read_text() + "changed after pass\n")
    result = invoke(lane, "resume")
    assert result.returncode != 0 and "changed" in result.stderr.lower()


def test_timeout_is_failed_transport_without_repeat_spend(lane):
    result = invoke(lane, "execute", extra=("--timeout", "1"), env={"TRANSPORT_SLEEP": "1"})
    assert result.returncode != 0 and "transport" in result.stderr
    assert "timeout" in receipt(lane)["steps"][-1]["error"]
    assert invoke(lane, "resume").returncode != 0
    assert (lane["tmp"] / "remote-count").read_text() == "1"


def test_explicit_lost_response_recovery_validates_without_dispatch(lane):
    assert invoke(lane, "execute", env={"LOST_RESPONSE": "1"}).returncode != 0
    assert invoke(lane, "resume").returncode != 0
    result = invoke(lane, "resume", extra=("--recover-doc",))
    assert result.returncode == 0, result.stderr
    assert receipt(lane)["recovery"]["explicit"] is True
    assert receipt(lane)["steps"][1]["outcome"] == "failed"
    assert (lane["tmp"] / "remote-count").read_text() == "1"
    assert invoke(lane, "resume").returncode == 0


def test_unrelated_reviewer_write_blocks_harvest(lane):
    result = invoke(lane, "execute", env={"EXTRA_WRITE": "1"})
    assert result.returncode != 0 and "exactly one" in result.stderr
    assert calls(lane) == ["review-stage"]


def test_staged_mode_uses_existing_committed_patch_without_restage(lane):
    assert invoke(lane).returncode == 0
    imported = lane["tmp"] / "stage.json"
    imported.write_text(json.dumps(dict(receipt(lane)["stage"], ok=True)))
    other = str(lane["root"] / ".task-state/imported")
    result = invoke(lane, "staged", extra=("--packet", other, "--stage-json", str(imported)))
    assert result.returncode == 0, result.stderr
    assert calls(lane) == ["review-stage"]
    assert invoke(lane, "resume", extra=("--packet", other)).returncode == 0


def test_stage_json_malformed_is_rejected_without_spend(lane):
    imported = lane["tmp"] / "stage.json"
    imported.write_text('{"ok":true}')
    result = invoke(lane, "staged", extra=("--stage-json", str(imported)))
    assert result.returncode != 0 and "malformed" in result.stderr
    assert not (lane["tmp"] / "remote-count").exists()


def test_output_parent_symlink_escape_is_rejected(lane):
    assert invoke(lane).returncode == 0
    wt = Path(receipt(lane)["stage"]["worktree"])
    outside = lane["tmp"] / "outside"
    outside.mkdir()
    (wt / "docs/reviews/escape").symlink_to(outside, target_is_directory=True)
    imported = lane["tmp"] / "stage.json"
    imported.write_text(json.dumps(dict(receipt(lane)["stage"], ok=True)))
    result = invoke(
        lane,
        "staged",
        extra=(
            "--packet",
            str(lane["root"] / ".task-state/imported"),
            "--stage-json",
            str(imported),
            "--doc",
            "docs/reviews/escape/review.md",
        ),
    )
    assert result.returncode != 0 and "escape" in result.stderr.lower()


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("review_packet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "patch,expected",
    [
        (b"\n+++ file\n+hi\n", {"2": "+++ file", "3": "+hi"}),
        (b"\n", {}),
        (("\n".join(["x"] * 173) + "\n").encode(), {"41": "x", "173": "x"}),
        (("\n".join(["x"] * 40 + [""] + ["y"] * 132) + "\n").encode(), {"173": "y", "1": "x"}),
    ],
)
def test_por_corrected_nonblank_samples_without_clamping(module, patch, expected):
    assert module.patch_por(patch)["sample_lines"] == expected


def test_optional_lock_import_failure_is_loud(module, monkeypatch, tmp_path):
    import builtins

    original = builtins.__import__

    def fail(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("no POSIX lock")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail)
    with pytest.raises(module.PacketError, match="lock"):
        with module.packet_lock(tmp_path):
            pass
