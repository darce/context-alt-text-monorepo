"""Shared edge is a read-only prerequisite, never a demo deploy mutation."""
import base64
import json
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from test_sync_demo_preflight import REPO_ROOT, SCRIPT

CONVERGE = "OCI_HOST='test-host.invalid' OCI_USER='test-user' ACX_EDGE_APPLY=1 bash scripts/deploy/recognition-service.sh sync-runtime prod"
RECOGNITION = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
HELPER = REPO_ROOT / "scripts" / "deploy" / "lib" / "shared-edge.sh"
SERVICE = REPO_ROOT / "apps" / "prototype-description-service"
ALL_NETWORKS = (
    "acx-prod-net", "acx-staging-net", "acx-dev-net", "acx-dev-fir-net", "acx-demo-net",
    "acx-dev-auraface-net", "acx-staging-auraface-net", "acx-prod-auraface-net",
)
WITHOUT_STAGING_PROD_AURA = tuple(n for n in ALL_NETWORKS if n not in ("acx-staging-auraface-net", "acx-prod-auraface-net"))
PORTAL_BLOCK = "# BEGIN APP_PORTAL_VHOST\napp.altcontext.com {\n\treverse_proxy app-portal:3000\n}\n# END APP_PORTAL_VHOST\n"
CADDY_CID = "abcdef1234567890"


def run_deploy(tmp_path, failure="", extra_env=None, timeout=30):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    body = tmp_path / "probe"
    ssh = bin_dir / "ssh"
    ssh.write_text("""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$CALLS"
if [[ "$*" == *'sudo -n timeout -k 5'* ]]; then
  printf '%s' "${@: -1}" > "$COMMAND"
  [[ "$FAILURE" != stall ]] || { printf '%s\n' "$$" > "$STALLED"; exec sleep 300; }
  cat > "$BODY"
  case "$FAILURE" in
    sudo) echo 'sudo: a password is required' >&2; exit 1 ;;
    lock_busy) echo 'ERROR: shared edge drift: lock_busy' >&2; exit 75 ;;
    '') exit 0 ;;
    *) echo "ERROR: shared edge drift: $FAILURE" >&2; exit 1 ;;
  esac
fi
if [[ "$*" == *bash* ]]; then cat >> "$CALLS"; fi
""")
    scp = bin_dir / "scp"
    scp.write_text('#!/usr/bin/env bash\nprintf "scp %s\\n" "$*" >> "$CALLS"\n')
    ssh.chmod(0o755)
    scp.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               CALLS=str(log), BODY=str(body), COMMAND=str(tmp_path / "command"),
               STALLED=str(tmp_path / "stalled"), FAILURE=failure, PLUGIN_ZIP="",
               OCI_HOST="test-host.invalid", OCI_USER="test-user",
               ACX_DEMO_GPU_PREFLIGHT="0", LC_ALL="C", **(extra_env or {}))
    result = subprocess.run(["bash", str(SCRIPT)], cwd=REPO_ROOT, env=env,
                            capture_output=True, text=True, timeout=timeout)
    return result, log.read_text(), body.read_text() if body.exists() else ""


def test_converged_edge_proceeds_without_edge_writes(tmp_path):
    result, calls, body = run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "docker-compose.demo.yml up -d" in calls
    assert "systemctl daemon-reload" in calls
    assert "Caddyfile.new" not in calls
    assert "docker-compose.caddy.yml.new" not in calls
    assert "docker compose -f docker-compose.caddy.yml up" not in calls
    assert "sudo -n timeout -k 5 120 bash -s -- 120 prod " in calls
    assert "Frozen interface (lane impl-portal-shared-helper)" in body
    assert "edge_effective_caddyfile" in body
    assert 'edge_required_networks "$base" "$overlay"' in body
    assert 'edge_lock_acquire "$edge_dir/app/activation.journal.lock" 0' in body
    assert 'edge_lock_release "$handle"' in body


@pytest.mark.parametrize("failure", ["caddyfile", "compose", "network:acx-demo-net", "lock_busy", "sudo"])
def test_probe_refuses_before_demo_mutation(tmp_path, failure):
    result, calls, body = run_deploy(tmp_path, failure)
    assert result.returncode != 0
    assert failure in result.stderr
    assert CONVERGE in result.stderr
    assert "chown" not in result.stderr
    for marker in ("scp ", "docker-compose.demo.yml", "bootstrap-wp.sh", "systemctl", "sudo mkdir"):
        assert marker not in calls
    assert body


def test_no_raw_edge_writer():
    source = SCRIPT.read_text()
    for forbidden in ("> Caddyfile", "mv docker-compose.caddy.yml",
                      "docker compose -f docker-compose.caddy.yml up"):
        assert forbidden not in source


def test_stalled_transport_is_bounded_on_the_local_clock(tmp_path):
    # RES-02: the remote `timeout` cannot end a session whose transport stalls.
    started = time.monotonic()
    try:
        result, calls, _ = run_deploy(tmp_path, "stall", {"ACX_REMOTE_COMMAND_TIMEOUT": "1"}, timeout=40)
    finally:
        elapsed = time.monotonic() - started
        stalled = [int((tmp_path / "stalled").read_text())] if (tmp_path / "stalled").exists() else []
        alive = _alive(stalled)
        for pid in alive:
            os.kill(pid, signal.SIGKILL)
    assert stalled, "the fixture never stalled the transport"
    assert result.returncode == 124, result.stderr
    assert elapsed < 1 + 10 + 4, f"local bound is deadline + 10 s; took {elapsed:.1f}s"
    assert "edge state UNKNOWN" in result.stderr
    assert CONVERGE in result.stderr
    assert not alive, "stalled ssh survived the local deadline"
    for marker in ("scp ", "docker-compose.demo.yml", "bootstrap-wp.sh", "systemctl", "sudo mkdir"):
        assert marker not in calls


# The cases below run the streamed program with the real frozen helper and real
# `docker compose config`; only daemon reads (network ls, ps, inspect) are faked.
# The live edge is what recognition-service.sh edge_desired + edge_copy install.


def _alive(pids):
    alive = []
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        alive.append(pid)
    return alive


def _kill_groups(pids):
    for pid in pids:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.fixture(scope="module")
def real_docker():
    missing = [tool for tool in ("flock", "jq", "timeout", "python3", "ps", "base64") if shutil.which(tool) is None]
    if shutil.which("realpath") is None or subprocess.run(
            ["realpath", "-m", "/nonexistent/edge"], capture_output=True).returncode != 0:
        missing.append("GNU realpath")
    docker = shutil.which("docker")
    if docker is None or subprocess.run([docker, "compose", "version"], capture_output=True,
                                        timeout=30).returncode != 0:
        missing.append("docker compose")
    if missing:
        pytest.skip(f"real shared-edge helper needs {', '.join(missing)}")
    return docker


@pytest.fixture(scope="module")
def streamed(tmp_path_factory):
    capture = tmp_path_factory.mktemp("capture")
    result, _, body = run_deploy(capture)
    assert result.returncode == 0, result.stderr
    command = (capture / "command").read_text()
    args = shlex.split(command.split(" bash -s -- ", 1)[1])
    assert args[:2] == ["120", "prod"]
    return body, args


class Edge:
    def __init__(self, docker):
        # recognition's program refuses paths outside [A-Za-z0-9_./-]; pytest's
        # parametrized tmp_path names carry brackets.
        self.root = Path(tempfile.mkdtemp(prefix="sync-demo-edge-test.", dir="/tmp")).resolve()
        self.dir = self.root / "opt" / "acx-backend"
        (self.dir / "app").mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.docker_log = self.root / "docker.log"
        self.pids = self.root / "stalled.pids"
        (self.bin / "docker").write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_LOG"
stall() {{ printf '%s\\n' "$$" >> "$STALLED_PIDS"; exec sleep 300; }}
if [[ "$1" == compose && " $* " == *' config '* ]]; then
  if [[ "$STALL" == repo-model && " $* " == *'/compose.repo.yml '* ]]; then stall; fi
  if [[ "$STALL" == helper-chain && " $* " != *' --project-directory '* ]]; then sleep 6; fi
  if [[ "$STALL" == late-helper && " $* " != *' --project-directory '* ]]; then stall; fi
  exec {shlex.quote(docker)} "$@"
fi
if [[ "$1" == compose && " $* " == *' ps '* ]]; then printf '%s\\n' {CADDY_CID}; exit 0; fi
if [[ "$1 $2" == 'network ls' ]]; then
  printf x >> "$DOCKER_LOG.inventory"
  if [[ "$STALL" == helper-chain && "$(cat "$DOCKER_LOG.inventory")" == xx ]]; then stall; fi
  printf '%s\\n' $INVENTORY
  exit 0
fi
if [[ "$1" == inspect ]]; then printf '%s\\n' "$CADDY_NETWORKS"; exit 0; fi
echo "unexpected docker call: $*" >&2
exit 97
""")
        (self.bin / "docker").chmod(0o755)
        (self.dir / "Caddyfile").write_text("# previous edge\n\n" + PORTAL_BLOCK)
        self.inventory = ALL_NETWORKS
        self.attached = ALL_NETWORKS

    def env(self, tmpdir, stall=""):
        tmpdir.mkdir(exist_ok=True)
        return dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", TMPDIR=str(tmpdir),
                    DOCKER_LOG=str(self.docker_log), STALLED_PIDS=str(self.pids), STALL=stall,
                    INVENTORY=" ".join(self.inventory),
                    CADDY_NETWORKS=json.dumps({name: {} for name in self.attached}), LC_ALL="C")

    def writer(self, action, driver=""):
        """Recognition's own program: the designated writer and its probe."""
        text = RECOGNITION.read_text()
        start = text.index("cat <<'EDGE_PROGRAM'\n") + len("cat <<'EDGE_PROGRAM'\n")
        program = text[start:text.index("\nEDGE_PROGRAM\n", start)] + "\n"
        if driver:
            program = program.split('\ncase "$action" in\n', 1)[0] + driver
        inputs = [base64.b64encode((SERVICE / name).read_bytes()).decode()
                  for name in ("Caddyfile", "docker-compose.caddy.yml")]
        return subprocess.run(
            ["bash", "-s", "--", action, str(self.dir / "app"), "", "60", "prod", "t1", str(self.root / "backup"), *inputs],
            input=HELPER.read_text() + program, env=self.env(self.root / "tmp-writer"),
            capture_output=True, text=True, timeout=120)

    def converge(self):
        # edge_desired renders the files; converge installs them with edge_copy.
        result = self.writer("probe", """
handle="$(edge_lock_acquire "$lock" 0 600 0)"
probe_without_journal=1
scratch="$(mktemp -d)"
edge_desired "$scratch" "$1" "$2"
edge_copy "$scratch/Caddyfile" "$live"
edge_copy "$scratch/docker-compose.caddy.yml" "$base"
rm -rf -- "$scratch"
edge_lock_release "$handle" 5
""")
        assert result.returncode == 0, result.stderr
        assert (self.dir / "docker-compose.caddy.yml").read_text().startswith("{")

    def writer_probe(self):
        result = self.writer("probe")
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def probe(self, streamed, budget=60, stall=""):
        body, args = streamed
        program = body.replace("/opt/acx-backend", str(self.dir))
        tmpdir = self.root / "tmp-probe"
        self.docker_log.unlink(missing_ok=True)
        Path(f"{self.docker_log}.inventory").unlink(missing_ok=True)
        started = time.monotonic()
        proc = subprocess.Popen(
            ["timeout", "-k", "5", str(budget), "bash", "-s", "--", str(budget), *args[1:]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=self.env(tmpdir, stall), start_new_session=True)
        try:
            _, stderr = proc.communicate(program, timeout=budget + 5)
        except subprocess.TimeoutExpired:
            # Nested timeout groups escape the outer process group. Record
            # liveness before test cleanup and kill only this fixture's groups
            # before draining pipes, so a failing regression cannot hang pytest.
            alive = _alive(self.stalled())
            _kill_groups(alive)
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=5)
            pytest.fail(f"probe streams still open after deadline {budget}s + 5s kill grace; live stalled pids: {alive}")
        finally:
            self.stalled_alive = _alive(self.stalled())
            _kill_groups(self.stalled_alive)
        self.leftovers = sorted(path.name for path in tmpdir.iterdir())
        calls = self.docker_log.read_text().splitlines() if self.docker_log.exists() else []
        return proc.returncode, stderr, time.monotonic() - started, calls

    def stalled(self):
        return [int(pid) for pid in self.pids.read_text().split()] if self.pids.exists() else []

    def close(self):
        _kill_groups(_alive(self.stalled()))
        shutil.rmtree(self.root, ignore_errors=True)


@pytest.fixture
def edge(real_docker):
    edge = Edge(real_docker)
    yield edge
    edge.close()


@pytest.mark.parametrize("inventory", [ALL_NETWORKS, WITHOUT_STAGING_PROD_AURA], ids=["all-networks", "aura-absent"])
def test_probe_accepts_the_designated_writer_output(edge, streamed, inventory):
    # REF-19: one writer. Whatever recognition installs must read as converged.
    edge.inventory = edge.attached = inventory
    edge.converge()
    assert edge.writer_probe() == "0 0 1"
    rc, stderr, _, calls = edge.probe(streamed)
    assert rc == 0, stderr
    assert any(" ps -q caddy" in call for call in calls)
    assert PORTAL_BLOCK in (edge.dir / "Caddyfile").read_text()
    assert edge.leftovers == [], "probe left its scratch, compose generation or lock state behind"


@pytest.mark.parametrize("drift,writer_view", [
    ("caddyfile", "1 0 1"),
    ("compose", "0 1 1"),
    ("network:acx-demo-net", "0 1 0"),
    ("network:acx-dev-net", "0 1 0"),
])
def test_probe_refuses_drift_that_the_writer_converges(edge, streamed, drift, writer_view):
    edge.converge()
    if drift == "caddyfile":
        with (edge.dir / "Caddyfile").open("a") as live:
            live.write("# hand edit\n")
    elif drift == "compose":
        model = json.loads((edge.dir / "docker-compose.caddy.yml").read_text())
        model["services"]["caddy"]["image"] = "caddy:2.8-alpine"
        (edge.dir / "docker-compose.caddy.yml").write_text(json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n")
    else:
        edge.attached = tuple(n for n in ALL_NETWORKS if n != drift.split(":", 1)[1])
    assert edge.writer_probe() == writer_view
    rc, stderr, _, _ = edge.probe(streamed)
    assert rc == 1
    assert f"ERROR: shared edge drift: {drift}" in stderr
    assert edge.leftovers == []


@pytest.mark.parametrize("holder", ["lock", "journal"])
def test_busy_edge_is_refused_before_any_read(edge, streamed, holder):
    edge.converge()
    lock = edge.dir / "app" / "activation.journal.lock"
    held = None
    if holder == "lock":
        held = subprocess.Popen(["flock", str(lock), "sleep", "60"], start_new_session=True)
        deadline = time.monotonic() + 10
        while subprocess.run(["flock", "-n", str(lock), "true"]).returncode == 0:
            assert time.monotonic() < deadline, "test holder never took the lock"
            time.sleep(0.05)
    else:
        (edge.dir / "app" / "activation.journal").write_text("version=recognition-edge-1\n")
    try:
        rc, stderr, _, calls = edge.probe(streamed)
    finally:
        if held is not None:
            os.killpg(held.pid, signal.SIGKILL)
            held.wait()
    assert rc == 75, stderr
    assert "ERROR: shared edge drift: lock_busy" in stderr
    assert calls == []
    assert edge.leftovers == []
    assert subprocess.run(["flock", "-n", str(lock), "true"]).returncode == 0


@pytest.mark.parametrize("stall,budget", [("repo-model", 4), ("helper-chain", 10)])
def test_stalled_helper_read_ends_within_the_probe_budget(edge, streamed, stall, budget):
    # RES-31: edge_bounded_run leads its own process group, beyond the outer
    # timeout's reach. helper-chain: the helper's slow `config` leaves its next
    # read (`network ls`) a full EDGE_OP_DEADLINE that would run past the budget.
    edge.converge()
    if stall == "helper-chain":
        (edge.dir / "docker-compose.caddy.yml").write_bytes((SERVICE / "docker-compose.caddy.yml").read_bytes())
    rc, stderr, elapsed, _ = edge.probe(streamed, budget, stall)
    assert edge.stalled(), "the fixture never stalled a helper read"
    assert not edge.stalled_alive, "a stalled helper read outlived the probe"
    assert elapsed < budget + 2, f"probe held its streams {elapsed:.1f}s; deadline {budget}s"
    assert rc == 3, stderr
    assert "edge state UNKNOWN" in stderr
    assert edge.leftovers == []
    assert subprocess.run(["flock", "-n", str(edge.dir / "app" / "activation.journal.lock"), "true"]).returncode == 0


def test_late_nested_docker_read_is_contained_after_marker_crosses_deadline(edge, streamed):
    # TEST-15 / RES-31: the old one-shot scan runs while grep is still reading
    # the optional-network marker. Only afterwards does the frozen helper start
    # a new timeout group for Docker, using its earlier EDGE_OP_DEADLINE.
    edge.converge()
    (edge.dir / "docker-compose.caddy.yml").write_bytes((SERVICE / "docker-compose.caddy.yml").read_bytes())
    real_grep = shlex.quote(shutil.which("grep"))
    grep = edge.bin / "grep"
    grep.write_text(f"""#!/usr/bin/env bash
if [[ "$*" == *optional-auraface-networks* ]]; then sleep 10.3; fi
exec {real_grep} "$@"
""")
    grep.chmod(0o755)
    # A separate process group that is not descended from the probe must live.
    canary = subprocess.Popen(["sleep", "60"], start_new_session=True)
    budget = 12
    try:
        rc, stderr, elapsed, calls = edge.probe(streamed, budget, "late-helper")
        canary_alive = canary.poll() is None
    finally:
        canary.kill()
        canary.wait()
    assert edge.stalled(), "the delayed marker never reached the subsequent stalled Docker read"
    assert any(call.startswith("compose -f ") and " config " in call for call in calls)
    assert elapsed >= budget - 2, "the marker did not cross stop_at"
    assert elapsed < budget + 5, f"probe streams stayed open {elapsed:.2f}s beyond deadline + grace"
    assert not edge.stalled_alive, "late-born Docker child survived the probe"
    assert canary_alive, "the reaper killed a process outside the probe's descendants"
    assert rc == 3, stderr
    assert "edge state UNKNOWN" in stderr
    assert edge.leftovers == []
    assert subprocess.run(["flock", "-n", str(edge.dir / "app" / "activation.journal.lock"), "true"]).returncode == 0


def test_interrupted_caddy_parser_cleans_helper_scratch(edge, streamed):
    edge.converge()
    real_python = shlex.quote(shutil.which("python3"))
    parser_live = edge.root / "parser-live"
    python = edge.bin / "python3"
    python.write_text(f"""#!/usr/bin/env bash
if [[ "$1" == - && "$2" == */shared-edge-caddy.*/live ]]; then
  [[ -s "$2" && -s "${{2%/live}}/base" ]] || exit 98
  printf '%s\\n' "$2" > {shlex.quote(str(parser_live))}
  printf '%s\\n' "$$" >> "$STALLED_PIDS"
  exec sleep 300
fi
exec {real_python} "$@"
""")
    python.chmod(0o755)
    budget = 4
    rc, stderr, elapsed, calls = edge.probe(streamed, budget)
    assert parser_live.exists() and edge.stalled(), "the parser never stalled with both helper copies present"
    assert rc == 124, stderr
    assert elapsed < budget + 5, f"parser kept probe streams open {elapsed:.2f}s"
    assert not edge.stalled_alive, "interrupted parser survived the probe"
    assert calls == [], "the parser should time out before Docker reads"
    assert subprocess.run(["flock", "-n", str(edge.dir / "app" / "activation.journal.lock"), "true"]).returncode == 0
    assert edge.leftovers == [], "interrupted Caddy parsing left helper scratch outside the owned probe scratch"
