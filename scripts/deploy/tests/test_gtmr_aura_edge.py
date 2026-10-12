"""Causal RED for the three AuraFace edge vhosts (GTMSMOKE-1, edge E).

The six RED checks read the maintained production Caddy files read-only. Against
the unchanged production files they must fail: no AuraFace vhost or network join
exists yet. The existing generic, SFace and demo routes are healthy controls that
must stay green. Synthetic compliant and mutant edges prove that each check
passes a correct edge and rejects each named defect, so the production RED comes
from absent AuraFace routing rather than from a broken helper.

The route emulator follows the literal source order of each Caddyfile site
block. It is a config-contract check, not the Caddy runtime: ``caddy validate``,
DNS, ACME and live TLS acceptance remain native gates.

TEST-15 — Prove the green can go red; The Pragmatic Programmer, ch. 9
(SOURCES.md#src-pragmatic-programmer).
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
EDGE_DIR = REPO_ROOT / "apps" / "prototype-description-service"
CADDYFILE = EDGE_DIR / "Caddyfile"
COMPOSE = EDGE_DIR / "docker-compose.caddy.yml"

# Frozen operator mapping: target environment -> public AuraFace hostname.
AURA_TARGETS = {
    "dev-auraface": "auraface.dev.altcontext.com",
    "staging-auraface": "auraface.staging.api.altcontext.com",
    "prod-auraface": "auraface.api.altcontext.com",
}
# Proposed configuration names derived from the environment key (not observed
# resources). Caddy routes only to the stable alias; "-next" is cutover-only.
EXISTING_UPSTREAMS = {
    "api.altcontext.com": "prod-api:8000",
    "staging.api.altcontext.com": "staging-api:8000",
    "dev.api.altcontext.com": "dev-api:8000",
    "fir.dev.api.altcontext.com": "dev-fir-api:8000",
}
EXISTING_NETWORKS = (
    "acx-prod-net",
    "acx-staging-net",
    "acx-dev-net",
    "acx-dev-fir-net",
    "acx-demo-net",
)
DEMO_HOST = "demo.altcontext.com"
DEMO_ADDRESSES = ("demo.altcontext.com", "129-213-40-111.sslip.io")
DEMO_DIRECTIVES = (
    "redir @demo_root /guide/ 302",
    "@xmlrpc path /xmlrpc.php",
    'respond @xmlrpc "Forbidden" 403',
    "reverse_proxy demo-wp:80",
)
ADMIN_PATHS = ("/admin", "/admin/", "/admin/users")
# Directives that could answer from another upstream when the primary route fails.
FALLBACK_DIRECTIVES = frozenset(
    {"handle", "handle_errors", "handle_path", "route", "try_files", "error", "fallback"}
)

_MATCHER = re.compile(r"@(\S+) path (.+)")
_RESPOND = re.compile(r'respond @(\S+) (?:"[^"]*" )?(\d{3})')
_PROXY = re.compile(r"reverse_proxy (\S+)")


def upstream_for(env: str) -> str:
    return f"{env}-api:8000"


def network_for(env: str) -> str:
    return f"acx-{env}-net"


def alias_for(env: str) -> str:
    return f"{env}-api"


AURA_NETWORKS = tuple(network_for(env) for env in AURA_TARGETS)


@dataclass(frozen=True)
class Site:
    addresses: tuple[str, ...]
    directives: tuple[str, ...]  # depth-1 lines only, source order, comments dropped


def parse_sites(text: str) -> list[Site]:
    """Split a Caddyfile into top-level site blocks with their depth-1 directives."""
    sites: list[Site] = []
    addresses: tuple[str, ...] = ()
    directives: list[str] = []
    depth = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if depth == 0:
            if not line.endswith("{"):
                raise AssertionError(f"unsupported top-level Caddyfile line: {line!r}")
            addresses = tuple(part.strip() for part in line[:-1].split(","))
            directives = []
            depth = 1
            continue
        if line == "}":
            depth -= 1
            if depth == 0:
                sites.append(Site(addresses, tuple(directives)))
            continue
        if depth == 1:
            directives.append(line)
        if line.endswith("{"):
            depth += 1
    if depth:
        raise AssertionError("unterminated Caddyfile site block")
    return sites


def _path_matches(pattern: str, path: str) -> bool:
    if "*" not in pattern:
        return path == pattern
    if pattern.count("*") != 1 or not pattern.endswith("/*"):
        raise AssertionError(f"unsupported path pattern {pattern!r} in route emulator")
    return path.startswith(pattern[:-1])


def route(site: Site, path: str) -> tuple[str, int | str | None]:
    """Return the first terminal directive that matches ``path``, in source order."""
    matchers: dict[str, tuple[str, ...]] = {}
    for line in site.directives:
        if m := _MATCHER.fullmatch(line):
            matchers[m.group(1)] = tuple(m.group(2).split())
        elif m := _RESPOND.fullmatch(line):
            name = m.group(1)
            if name not in matchers:
                raise AssertionError(f"respond references undefined matcher @{name}")
            if any(_path_matches(p, path) for p in matchers[name]):
                return ("respond", int(m.group(2)))
        elif m := _PROXY.fullmatch(line):
            return ("proxy", m.group(1))
    return ("unrouted", None)


def _owners(sites: list[Site], host: str) -> list[Site]:
    return [site for site in sites if host in site.addresses]


def _single_site(
    sites: list[Site],
    host: str,
    problems: list[str],
    addresses: tuple[str, ...] | None = None,
) -> Site | None:
    expected = addresses or (host,)
    owners = _owners(sites, host)
    if len(owners) != 1 or owners[0].addresses != expected:
        found = [site.addresses for site in owners]
        problems.append(f"{host}: expected exactly one single-host vhost {expected}; found {found}")
        return None
    return owners[0]


def _report(problems: list[str]) -> None:
    if problems:
        raise AssertionError("; ".join(problems))


def check_exact_aura_vhosts(caddy: str) -> None:
    """Exactly the three frozen AuraFace hostnames, each in its own single-host vhost."""
    sites = parse_sites(caddy)
    frozen = set(AURA_TARGETS.values())
    present = {addr for site in sites for addr in site.addresses if "auraface" in addr}
    problems: list[str] = []
    if missing := sorted(frozen - present):
        problems.append(f"missing AuraFace vhost(s) {missing}")
    if extra := sorted(present - frozen):
        problems.append(f"unexpected AuraFace vhost(s) {extra}")
    for host in sorted(frozen & present):
        owners = _owners(sites, host)
        if len(owners) != 1 or owners[0].addresses != (host,):
            found = [site.addresses for site in owners]
            problems.append(f"{host} must be exactly one single-host vhost; found {found}")
    _report(problems)


def check_aura_proxy_target(caddy: str) -> None:
    """Each AuraFace vhost sends '/' only to its own stable API alias on port 8000."""
    sites = parse_sites(caddy)
    problems: list[str] = []
    for env, host in AURA_TARGETS.items():
        site = _single_site(sites, host, problems)
        if site is None:
            continue
        if (got := route(site, "/")) != ("proxy", upstream_for(env)):
            problems.append(f"{host} '/' -> {got}; expected proxy {upstream_for(env)}")
    _report(problems)


def check_aura_admin_denial(caddy: str) -> None:
    """Public /admin and /admin/* answer 404 before any proxy on every AuraFace vhost."""
    sites = parse_sites(caddy)
    problems: list[str] = []
    for host in AURA_TARGETS.values():
        site = _single_site(sites, host, problems)
        if site is None:
            continue
        for admin_path in ADMIN_PATHS:
            if (got := route(site, admin_path)) != ("respond", 404):
                problems.append(f"{host} {admin_path} -> {got}; expected public 404 before proxy")
    _report(problems)


def check_aura_no_fallback(caddy: str) -> None:
    """No fallback-capable directive and exactly one reverse_proxy per AuraFace vhost."""
    sites = parse_sites(caddy)
    problems: list[str] = []
    for env, host in AURA_TARGETS.items():
        site = _single_site(sites, host, problems)
        if site is None:
            continue
        names = [line.split(None, 1)[0] for line in site.directives]
        if bad := [name for name in names if name in FALLBACK_DIRECTIVES]:
            problems.append(f"{host} has fallback directive(s) {bad}")
        proxies = [line for line in site.directives if line.startswith("reverse_proxy")]
        if proxies != [f"reverse_proxy {upstream_for(env)}"]:
            problems.append(
                f"{host} reverse_proxy directives {proxies}; expected only "
                f"reverse_proxy {upstream_for(env)}"
            )
    _report(problems)


def check_aura_aliases_unique(caddy: str) -> None:
    """Each AuraFace stable alias is used by exactly one vhost, with no reuse anywhere."""
    sites = parse_sites(caddy)
    hosts = Counter(
        m.group(1).rsplit(":", 1)[0]
        for site in sites
        for line in site.directives
        if (m := _PROXY.fullmatch(line))
    )
    problems: list[str] = []
    for env in AURA_TARGETS:
        count = hosts[alias_for(env)]
        if count != 1:
            problems.append(
                f"upstream alias {alias_for(env)} must be used by exactly one vhost; found {count}"
            )
    if reused := sorted(host for host, count in hosts.items() if count > 1):
        problems.append(f"upstream alias(es) reused across vhosts: {reused}")
    _report(problems)


def check_aura_networks(compose: dict) -> None:
    """caddy joins each AuraFace network exactly once, and each is declared external."""
    attached = list(compose["services"]["caddy"]["networks"])
    declared = compose.get("networks") or {}
    problems: list[str] = []
    if dupes := sorted(net for net, count in Counter(attached).items() if count > 1):
        problems.append(f"caddy attaches network(s) more than once: {dupes}")
    for env in AURA_TARGETS:
        net = network_for(env)
        if attached.count(net) != 1:
            problems.append(f"caddy must join {net} exactly once; found {attached.count(net)}")
        if declared.get(net) != {"external": True}:
            problems.append(f"{net} must be declared external; found {declared.get(net)!r}")
    _report(problems)


def check_existing_networks(compose: dict) -> None:
    """Existing generic/SFace/demo networks stay attached to caddy and external."""
    attached = list(compose["services"]["caddy"]["networks"])
    declared = compose.get("networks") or {}
    problems: list[str] = []
    for net in EXISTING_NETWORKS:
        if net not in attached:
            problems.append(f"existing network {net} is no longer attached to caddy")
        if declared.get(net) != {"external": True}:
            problems.append(f"existing network {net} is no longer declared external")
    _report(problems)


def check_existing_routes_unchanged(caddy: str) -> None:
    """Generic prod/staging/dev and SFace dev keep upstream and public /admin denial."""
    sites = parse_sites(caddy)
    problems: list[str] = []
    for host, upstream in EXISTING_UPSTREAMS.items():
        site = _single_site(sites, host, problems)
        if site is None:
            continue
        if (got := route(site, "/")) != ("proxy", upstream):
            problems.append(f"{host} '/' -> {got}; expected proxy {upstream}")
        for admin_path in ADMIN_PATHS:
            if (got := route(site, admin_path)) != ("respond", 404):
                problems.append(f"{host} {admin_path} -> {got}; expected public 404")
    _report(problems)


def check_demo_block_unchanged(caddy: str) -> None:
    """Demo WordPress keeps its hosts, literal guards and upstream; no Aura/FIR sharing."""
    sites = parse_sites(caddy)
    problems: list[str] = []
    site = _single_site(sites, DEMO_HOST, problems, addresses=DEMO_ADDRESSES)
    if site is not None:
        for line in DEMO_DIRECTIVES:
            if line not in site.directives:
                problems.append(f"demo vhost lost directive {line!r}")
        if (got := route(site, "/xmlrpc.php")) != ("respond", 403):
            problems.append(f"demo /xmlrpc.php -> {got}; expected 403")
        if (got := route(site, "/guide/")) != ("proxy", "demo-wp:80"):
            problems.append(f"demo /guide/ -> {got}; expected proxy demo-wp:80")
    _report(problems)


def _load_caddy() -> str:
    return CADDYFILE.read_text(encoding="utf-8")


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _aura_block(
    env: str,
    *,
    address: str | None = None,
    upstream: str | None = None,
    admin_deny: bool = True,
    tail: tuple[str, ...] = (),
) -> str:
    host = address or AURA_TARGETS[env]
    lines = [f"{host} {{", "\t# Synthetic AuraFace fixture; not a production edge."]
    if admin_deny:
        lines += ["\t@admin path /admin /admin/*", "\trespond @admin 404"]
    lines.append(f"\treverse_proxy {upstream or upstream_for(env)}")
    lines += [f"\t{line}" for line in tail]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _caddy_fixture(
    overrides: Mapping[str, str | None] | None = None,
    *,
    existing: str | None = None,
) -> str:
    blocks = {env: _aura_block(env) for env in AURA_TARGETS}
    for env, text in (overrides or {}).items():
        if text is None:
            del blocks[env]
        else:
            blocks[env] = text
    base = _load_caddy() if existing is None else existing
    return base + "\n" + "".join(blocks[env] for env in AURA_TARGETS if env in blocks)


def _compose_fixture(
    *,
    attach: tuple[str, ...] = AURA_NETWORKS,
    external: tuple[str, ...] = AURA_NETWORKS,
    drop: tuple[str, ...] = (),
) -> dict:
    data = copy.deepcopy(_load_compose())
    kept = [net for net in data["services"]["caddy"]["networks"] if net not in drop]
    data["services"]["caddy"]["networks"] = [*kept, *attach]
    for net in AURA_NETWORKS:
        data["networks"][net] = {"external": True} if net in external else {"driver": "bridge"}
    return data


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"fixture anchor must occur exactly once: {old!r}")
    return text.replace(old, new)


def _capture(check: Callable[[object], None], arg: object) -> list[str]:
    try:
        check(arg)
    except AssertionError as exc:
        return [f"{check.__name__}: {exc}"]
    return []


def _edge_problems(caddy: str, compose: dict) -> list[str]:
    problems: list[str] = []
    for check in (
        check_exact_aura_vhosts,
        check_aura_proxy_target,
        check_aura_admin_denial,
        check_aura_no_fallback,
        check_aura_aliases_unique,
        check_existing_routes_unchanged,
        check_demo_block_unchanged,
    ):
        problems += _capture(check, caddy)
    for check in (check_aura_networks, check_existing_networks):
        problems += _capture(check, compose)
    return problems


# RED against the unchanged production files: no AuraFace vhost or network exists.


def test_caddy_declares_exactly_the_three_frozen_auraface_vhosts():
    check_exact_aura_vhosts(_load_caddy())


def test_each_auraface_vhost_proxies_only_its_stable_api_alias():
    check_aura_proxy_target(_load_caddy())


def test_each_auraface_vhost_denies_public_admin_before_proxy():
    check_aura_admin_denial(_load_caddy())


def test_auraface_vhosts_have_no_fallback_or_second_upstream():
    check_aura_no_fallback(_load_caddy())


def test_auraface_upstream_aliases_are_unique_across_vhosts():
    check_aura_aliases_unique(_load_caddy())


def test_caddy_joins_each_auraface_network_exactly_once_as_external():
    check_aura_networks(_load_compose())


# Healthy controls: existing generic, SFace and demo routes must stay green.


def test_existing_generic_and_sface_vhosts_keep_upstreams_and_admin_denial():
    check_existing_routes_unchanged(_load_caddy())


def test_demo_wordpress_vhost_keeps_hosts_upstream_and_guards():
    check_demo_block_unchanged(_load_caddy())


def test_existing_compose_networks_stay_attached_and_external():
    check_existing_networks(_load_compose())


# Satisfiability and mutation controls: synthetic fixtures, not production.


def test_compliant_synthetic_edge_satisfies_every_check():
    assert _edge_problems(_caddy_fixture(), _compose_fixture()) == []


MUTANTS: dict[str, tuple[str, str, Callable[[], tuple[str, dict]]]] = {
    "prod-admin-not-denied": (
        "check_aura_admin_denial",
        "auraface.api.altcontext.com",
        lambda: (
            _caddy_fixture({"prod-auraface": _aura_block("prod-auraface", admin_deny=False)}),
            _compose_fixture(),
        ),
    ),
    "prod-generic-upstream": (
        "check_aura_proxy_target",
        "prod-api:8000",
        lambda: (
            _caddy_fixture(
                {"prod-auraface": _aura_block("prod-auraface", upstream="prod-api:8000")}
            ),
            _compose_fixture(),
        ),
    ),
    "dev-next-alias-routed": (
        "check_aura_proxy_target",
        "dev-auraface-api-next:8000",
        lambda: (
            _caddy_fixture(
                {"dev-auraface": _aura_block("dev-auraface", upstream="dev-auraface-api-next:8000")}
            ),
            _compose_fixture(),
        ),
    ),
    "prod-handle-errors-fallback": (
        "check_aura_no_fallback",
        "handle_errors",
        lambda: (
            _caddy_fixture(
                {
                    "prod-auraface": _aura_block(
                        "prod-auraface",
                        tail=("handle_errors {", "reverse_proxy prod-api:8000", "}"),
                    )
                }
            ),
            _compose_fixture(),
        ),
    ),
    "prod-second-upstream": (
        "check_aura_no_fallback",
        "prod-api:8000",
        lambda: (
            _caddy_fixture(
                {
                    "prod-auraface": _aura_block(
                        "prod-auraface", tail=("reverse_proxy prod-api:8000",)
                    )
                }
            ),
            _compose_fixture(),
        ),
    ),
    "prod-merged-with-generic-host": (
        "check_exact_aura_vhosts",
        "single-host",
        lambda: (
            _caddy_fixture(
                {
                    "prod-auraface": _aura_block(
                        "prod-auraface",
                        address="auraface.api.altcontext.com, api.altcontext.com",
                    )
                }
            ),
            _compose_fixture(),
        ),
    ),
    "prod-vhost-missing": (
        "check_exact_aura_vhosts",
        "missing AuraFace vhost",
        lambda: (_caddy_fixture({"prod-auraface": None}), _compose_fixture()),
    ),
    "prod-network-not-attached": (
        "check_aura_networks",
        "acx-prod-auraface-net",
        lambda: (
            _caddy_fixture(),
            _compose_fixture(attach=(network_for("dev-auraface"), network_for("staging-auraface"))),
        ),
    ),
    "prod-network-not-external": (
        "check_aura_networks",
        "must be declared external",
        lambda: (
            _caddy_fixture(),
            _compose_fixture(
                external=(network_for("dev-auraface"), network_for("staging-auraface"))
            ),
        ),
    ),
    "existing-api-upstream-stolen": (
        "check_existing_routes_unchanged",
        "api.altcontext.com",
        lambda: (
            _caddy_fixture(
                existing=_replace_once(
                    _load_caddy(),
                    "reverse_proxy prod-api:8000",
                    "reverse_proxy prod-auraface-api:8000",
                )
            ),
            _compose_fixture(),
        ),
    ),
    "existing-demo-upstream-stolen": (
        "check_demo_block_unchanged",
        "reverse_proxy demo-wp:80",
        lambda: (
            _caddy_fixture(
                existing=_replace_once(
                    _load_caddy(),
                    "reverse_proxy demo-wp:80",
                    "reverse_proxy prod-auraface-api:8000",
                )
            ),
            _compose_fixture(),
        ),
    ),
    "existing-fir-network-detached": (
        "check_existing_networks",
        "acx-dev-fir-net",
        lambda: (_caddy_fixture(), _compose_fixture(drop=("acx-dev-fir-net",))),
    ),
}


@pytest.mark.parametrize("name", list(MUTANTS))
def test_mutant_edge_is_rejected_by_the_named_check(name):
    expected_check, needle, build = MUTANTS[name]
    caddy, compose = build()
    problems = _edge_problems(caddy, compose)
    assert any(p.startswith(f"{expected_check}:") and needle in p for p in problems), problems
