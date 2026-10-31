"""Provision private FIR runtime credentials, without changing the running stack.

Default: read-only validation/dry run. See docs/runbooks/fir-curation-runtime-roles.md.
Owner credentials enter through a private file (or stdin), never command arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Deliberately explicit existing FIR data-plane tables, not ALL TABLES or future
# default privileges. No payment, portal, operator-recovery, or schema DDL grants.
IDENTITY_TABLES = frozenset(
    [
        "face_observations",
        "media_identities",
        "identity_clusters",
        "identity_members",
        "identity_name_suppressions",
        "identity_cluster_representatives",
        "cluster_merge_receipts",
        "identity_scan_jobs",
        "identity_scan_job_items",
        "identity_clustering_jobs",
        "identity_suggestions",
        "cluster_merge_suggestions",
        "name_suggestions",
        "identity_cluster_blocks",
        "identity_constraints",
        "recognition_runs",
        "recognition_events",
        "clustering_feedback",
        "audit_events",
        "export_jobs",
        "identity_cluster_refresh_queue",
        "clustering_job_reports",
        "assignment_decisions",
        "identity_atlas_runs",
        "identity_atlas_points",
        "identity_atlas_queue_dispositions",
    ]
)
API_WRITE = IDENTITY_TABLES | frozenset(
    [
        "curation_replay_records",
        "describe_startups",
        "describe_operations",
        "describe_demand_leases",
        "describe_load_snapshot_revisions",
        "image_descriptions",
        "image_description_runs",
        "image_description_run_items",
        "usage_reservation",
        "usage_admission_global_state",
    ]
)
WORKER_WRITE = IDENTITY_TABLES | frozenset(["worker_capabilities", "usage_reservation", "usage_admission_global_state"])
READ_ONLY = frozenset(["tenant_entitlement", "worker_capabilities", "mv_identity_cluster_centroids"])
ALIASES = frozenset(
    [
        "POSTGRES_DSN",
        "POSTGRES_SYNC_DSN",
        "PGUSER",
        "PGPASSWORD",
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "DB_NAME",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "SQLALCHEMY_DATABASE_URI",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGPASSFILE",
        "PGOPTIONS",
        "RECOGNITION_VAULT_SECRET_MAP",
        "APP_PGUSER",
        "APP_PGPASSWORD",
    ]
)
NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")


class RefusalError(ValueError):
    """A safe, credential-free operator diagnostic."""


def require(condition, message):
    if not condition:
        raise RefusalError(message)


def private_text(path, *, stdin=False):
    if stdin and path == "-":
        require(not sys.stdin.isatty(), "owner DSN stdin must be redirected, never entered on a terminal")
        value = sys.stdin.read(65537).strip()
        require(len(value) <= 65536, "private input too large")
        return value
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1,
            "input/custody must be a private regular file owned by this operator, mode 0600, one link",
        )
        with os.fdopen(fd, closefd=False) as f:
            value = f.read(65537)
        require(len(value) <= 65536, "private input too large")
        return value.strip()
    finally:
        os.close(fd)


def checked_url(raw):
    # Disallow ALL query parameters rather than attempting to enumerate libpq's
    # nested dsn/service/host/options/credential precedence paths (GTMSMOKE18201).
    require(isinstance(raw, str) and not any(ord(c) < 32 for c in raw), "invalid DSN")
    require(
        "?" not in raw and "#" not in raw, "DSN queries/fragments are forbidden (nested DSN/role/credential override)"
    )
    try:
        u = make_url(raw)
        require(u.drivername in {"postgresql", "postgresql+psycopg", "postgresql+asyncpg"}, "PostgreSQL DSN required")
        require(
            bool(u.username and u.password and u.host and u.port and u.database) and not u.query,
            "explicit complete DSN required",
        )
        require(
            "/" not in u.database and "," not in u.host and not u.host.startswith("/"),
            "single explicit TCP target required",
        )
        return u
    except RefusalError:
        raise
    except Exception:
        raise RefusalError("invalid DSN") from None


def endpoint(url):
    return [url.host, url.port, url.database]


def validate_environment(env, owner):
    require(
        isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()),
        "environment input must be a JSON string mapping",
    )
    require(env.get("ACX_NETWORK_NAME") == "acx-dev-fir-net", "FIR network must remain acx-dev-fir-net")
    require(
        env.get("RECOGNITION_SECRET_BACKEND", "env") == "env",
        "unresolved Vault provider cannot be overridden safely by an environment profile",
    )
    require(env.get("ALLOW_RLS_BYPASS_FOR_TESTS", "0") != "1", "test RLS bypass must not enter a live profile")
    require(
        "PGVECTOR_DIM" in env and env["PGVECTOR_DIM"].isdigit() and int(env["PGVECTOR_DIM"]) > 0,
        "preserve the explicit existing PGVECTOR_DIM",
    )
    # Require actual resolved DSNs: no interpolation guessing or default database.
    for k in ("POSTGRES_DSN", "POSTGRES_SYNC_DSN"):
        require(
            k in env and endpoint(checked_url(env[k])) == endpoint(owner),
            "runtime DSN target differs from asserted owner target",
        )
    for key, value in [
        ("PGHOST", owner.host),
        ("PGPORT", str(owner.port)),
        ("DB_NAME", owner.database),
        ("POSTGRES_DB", owner.database),
        ("PGDATABASE", owner.database),
    ]:
        require(key not in env or env[key] == value, "runtime fallback target differs from explicit DSN")
    for k, v in env.items():
        require(
            "\x00" not in k + v and "\n" not in k + v and "\r" not in k + v, "environment contains control characters"
        )
        if k not in ALIASES:
            require(
                owner.password not in v and not re.search(r"postgres(?:ql)?(?:\+\w+)?://", v, re.I),
                "unrecognized owner credential alias; remove it from resolved input explicitly",
            )
    return env


def environment(path, owner):
    raw = json.loads(private_text(path))
    if isinstance(raw, dict) and "services" in raw:
        require(
            raw.get("networks", {}).get("backend", {}).get("name") == "acx-dev-fir-net",
            "resolved Compose network must be acx-dev-fir-net",
        )
        result = {}
        for service in ("api", "worker"):
            env = dict(raw["services"][service]["environment"])
            env.setdefault("ACX_NETWORK_NAME", "acx-dev-fir-net")
            result[service] = validate_environment(env, owner)
    else:
        shared = validate_environment(raw, owner)
        result = {"api": dict(shared), "worker": dict(shared)}
    require(
        result["api"]["PGVECTOR_DIM"] == result["worker"]["PGVECTOR_DIM"],
        "API/worker existing vector dimension differs",
    )
    return result


def runtime_profile(environments, owner, roles):
    return {
        "services": {
            s: {"environment": service_environment(environments[s], owner, v["name"], v["password"])}
            for s, v in roles.items()
        },
        "networks": {"backend": {"name": "acx-dev-fir-net"}},
    }


def service_environment(env, url, role, password):
    result = dict(env)
    # Override env_file and also neutralize libpq fallback/service aliases. Empty
    # string is intentional: Compose null could inherit the invoking shell.
    result.update(dict.fromkeys(ALIASES, ""))
    result.update(
        POSTGRES_DSN=url.set(drivername="postgresql+asyncpg", username=role, password=password).render_as_string(
            hide_password=False
        ),
        POSTGRES_SYNC_DSN=url.set(drivername="postgresql+psycopg", username=role, password=password).render_as_string(
            hide_password=False
        ),
        PGUSER=role,
        PGPASSWORD=password,
        POSTGRES_USER=role,
        POSTGRES_PASSWORD=password,
        APP_PGUSER=role,
        APP_PGPASSWORD=password,
        PGHOST=url.host,
        PGPORT=str(url.port),
        PGDATABASE=url.database,
        DB_NAME=url.database,
        POSTGRES_DB=url.database,
        ACX_SCHEMA_BOOTSTRAP_MODE="verify",
        ALLOW_RLS_BYPASS_FOR_TESTS="0",
    )
    return {k: v.replace("$", "$$") for k, v in result.items()}


def catalog_preflight(c, expected):
    facts = c.execute(
        text(
            "SELECT current_database(), (SELECT oid FROM pg_database WHERE datname=current_database()), current_schema(), current_setting('server_version_num')::int"
        )
    ).one()
    require(
        facts[0] == expected and facts[2] == "public", "connected database/schema differs from expected existing target"
    )
    require(170000 <= facts[3] < 180000, "this bounded tool requires PostgreSQL 17")
    # Changing PUBLIC would affect unrelated principals. Require an operator to
    # harden it separately; never claim REVOKE FROM this role denies PUBLIC.
    ambient = c.scalar(
        text("""
        SELECT EXISTS (
          SELECT 1 FROM pg_database d, LATERAL aclexplode(COALESCE(d.datacl,acldefault('d',d.datdba))) a
          WHERE d.datname=current_database() AND a.grantee=0 AND a.privilege_type IN ('CREATE','TEMPORARY')
          UNION ALL
          SELECT 1 FROM pg_namespace n, LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a
          WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' AND a.grantee=0 AND a.privilege_type='CREATE'
        )""")
    )
    require(
        not ambient,
        "PUBLIC CREATE/TEMP privileges prevent a no-DDL runtime; operator must harden the existing target separately",
    )
    from scripts.verify_identity_schema import collect_and_validate

    report = collect_and_validate(c)
    require(report["ok"], "existing schema verification failed; drain writers, owner heal/verify before provision")
    return int(facts[1])


def role_row(c, role):
    return (
        c.execute(
            text("""SELECT oid,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication,rolinherit,rolcanlogin,
        shobj_description(oid,'pg_authid') AS custody FROM pg_roles WHERE rolname=:r"""),
            {"r": role},
        )
        .mappings()
        .one_or_none()
    )


def role_safe(c, role, row):
    require(
        row is not None
        and not any(
            row[k] for k in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication", "rolinherit")
        )
        and row["rolcanlogin"],
        "runtime role attributes drifted; refuse adoption or repair",
    )
    require(
        not c.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=:oid OR roleid=:oid)"), {"oid": row["oid"]}
        ),
        "runtime role membership drifted",
    )
    require(
        not c.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_shdepend WHERE refclassid='pg_authid'::regclass AND refobjid=:oid AND deptype='o')"
            ),
            {"oid": row["oid"]},
        ),
        "runtime role owns objects",
    )
    require(
        not c.scalar(
            text(
                "SELECT has_database_privilege(:r,current_database(),'CREATE,TEMP') OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname <> 'information_schema' AND has_schema_privilege(:r,oid,'CREATE'))"
            ),
            {"r": role},
        ),
        "runtime has ambient DDL privileges",
    )
    require(
        not c.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_db_role_setting WHERE setrole=:oid)"), {"oid": row["oid"]}),
        "runtime role has unowned setting overrides",
    )


def manifest(service, maintain=False):
    rw = API_WRITE if service == "api" else WORKER_WRITE
    read = READ_ONLY | {"tenants", "alembic_version"}
    result = {t: {"SELECT"} for t in read}
    result.update({t: {"SELECT", "INSERT", "UPDATE", "DELETE"} for t in rw})
    if service == "api":
        result.update({t: {"SELECT", "UPDATE"} for t in ("tenants", "api_keys")})
    if service == "worker" and maintain:
        result["mv_identity_cluster_centroids"] = {"SELECT", "MAINTAIN"}
    return result


def sequence_manifest(c, service):
    rw = API_WRITE if service == "api" else WORKER_WRITE
    sequences = c.execute(
        text("""SELECT s.relname,t.relname FROM pg_class s
       JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=s.oid AND d.deptype IN ('a','i')
       JOIN pg_class t ON t.oid=d.refobjid
       WHERE s.relkind='S' AND s.relnamespace='public'::regnamespace""")
    ).all()
    return {seq for seq, table in sequences if table in rw}


def verify_grants(c, role, service, maintain=False):
    expected = manifest(service, maintain)
    # Effective rights include PUBLIC, so an ambient or extra direct grant
    # cannot be hidden behind a matching custody marker. Grant options too.
    rows = c.execute(
        text("""SELECT n.nspname,c.relname,p.privilege,
       has_table_privilege(:r,c.oid,p.privilege),
       has_table_privilege(:r,c.oid,p.privilege || ' WITH GRANT OPTION')
       FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
       CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']) AS p(privilege)
       WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' AND c.relkind IN ('r','p','m','v','f')"""),
        {"r": role},
    )
    for schema, table, privilege, actual, grant_option in rows:
        wanted = schema == "public" and privilege in expected.get(table, set())
        require(actual == wanted and not grant_option, "runtime effective table privileges drifted; refuse repair")
    sequences = sequence_manifest(c, service)
    rows = c.execute(
        text("""SELECT n.nspname,c.relname,p.privilege,
       has_sequence_privilege(:r,c.oid,p.privilege),
       has_sequence_privilege(:r,c.oid,p.privilege || ' WITH GRANT OPTION')
       FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
       CROSS JOIN unnest(ARRAY['USAGE','SELECT','UPDATE']) AS p(privilege)
       WHERE n.nspname !~ '^pg_' AND c.relkind='S'"""),
        {"r": role},
    )
    for schema, seq, privilege, actual, grant_option in rows:
        wanted = schema == "public" and seq in sequences and privilege in {"USAGE", "SELECT"}
        require(actual == wanted and not grant_option, "runtime effective sequence privileges drifted; refuse repair")


def grant_manifest(c, role, service, maintain=False):
    def q(name):
        return '"' + name.replace('"', '""') + '"'

    grants = manifest(service, maintain)
    actual = set(
        c.execute(
            text("SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','p','m')")
        ).scalars()
    )
    require(set(grants) <= actual, "required existing runtime tables missing")
    c.execute(text(f"GRANT CONNECT ON DATABASE {q(c.scalar(text('SELECT current_database()')))} TO {q(role)}"))
    c.execute(text(f"GRANT USAGE ON SCHEMA public TO {q(role)}"))
    for table, rights in sorted(grants.items()):
        c.execute(text(f"GRANT {', '.join(sorted(rights))} ON TABLE public.{q(table)} TO {q(role)}"))
    for seq in sorted(sequence_manifest(c, service)):
        c.execute(text(f"GRANT USAGE, SELECT ON SEQUENCE public.{q(seq)} TO {q(role)}"))


def private_write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def provision(args):
    require(
        NAME.fullmatch(args.expected_database) is not None
        and (
            args.expected_database == "alt_context_dev_fir"
            or re.fullmatch(r"acx_(?:role|boot)_[a-z0-9_]+", args.expected_database)
        ),
        "unrelated target database refused",
    )
    for role in (args.api_role, args.worker_role):
        require(
            NAME.fullmatch(role) is not None and role.startswith("acx_"),
            "runtime roles require distinct acx_ identifiers",
        )
    require(args.api_role != args.worker_role, "API and worker require distinct roles")
    owner = checked_url(private_text(args.owner_dsn_file, stdin=True))
    require(
        endpoint(owner) == [args.expected_host, args.expected_port, args.expected_database],
        "owner DSN target differs from explicit expected target",
    )
    require(owner.username not in (args.api_role, args.worker_role), "owner and runtime principals must differ")
    env = environment(args.runtime_environment_file, owner)
    os.environ["PGVECTOR_DIM"] = env["api"]["PGVECTOR_DIM"]
    output = Path(args.profile_dir)
    state = None
    if output.exists() or output.is_symlink():
        info = output.lstat()
        require(
            stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "profile directory must be private and operator owned",
        )
        require(
            {p.name for p in output.iterdir()} == {"custody.json", "runtime.compose.json"},
            "existing profile lacks exact custody files; refuse adoption",
        )
        state = json.loads(private_text(output / "custody.json"))
        private_text(output / "runtime.compose.json")
    engine = create_engine(
        owner.set(drivername="postgresql+psycopg"),
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000 -c lock_timeout=5000"},
    )
    created_files = []
    made_directory = False
    try:
        with engine.begin() as c:
            db_oid = catalog_preflight(c, args.expected_database)  # Before any DDL.
            # Serializes this target/role pair without creating a registry table.
            key = int.from_bytes(
                hashlib.sha256(("|".join([args.expected_database, args.api_role, args.worker_role])).encode()).digest()[
                    :8
                ],
                "big",
                signed=True,
            )
            if args.apply:
                c.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
            rows = {s: role_row(c, r) for s, r in [("api", args.api_role), ("worker", args.worker_role)]}
            if state is not None:
                require(
                    state.get("schema") == "acx/fir-runtime-custody@1"
                    and state.get("worker_centroid_maintain") == args.worker_centroid_maintain,
                    "custody privilege scope differs; refuse silent grant/revocation",
                )
                require(
                    state.get("endpoint") == endpoint(owner) and state.get("database_oid") == db_oid,
                    "custody target identity differs",
                )
                require(set(state.get("roles", {})) == {"api", "worker"}, "invalid custody")
                for service, role in [("api", args.api_role), ("worker", args.worker_role)]:
                    owned = state["roles"][service]
                    require(
                        owned["name"] == role
                        and rows[service] is not None
                        and rows[service]["oid"] == owned["oid"]
                        and rows[service]["custody"] == state["marker"],
                        "role custody evidence differs; refuse adoption/rotation",
                    )
                    role_safe(c, role, rows[service])
                    verify_grants(c, role, service, args.worker_centroid_maintain)
                expected_profile = runtime_profile(env, owner, state["roles"])
                require(
                    json.loads(private_text(output / "runtime.compose.json")) == expected_profile,
                    "profile or input environment drifted; refuse silent regeneration",
                )
                return {"mode": "unchanged" if args.apply else "dry-run", "roles": [args.api_role, args.worker_role]}
            require(all(v is None for v in rows.values()), "unowned existing runtime role; refuse adoption/rotation")
            if not args.apply:
                return {
                    "mode": "dry-run",
                    "roles": [args.api_role, args.worker_role],
                    "worker_scope": (
                        "claim/retry plus centroid MAINTAIN"
                        if args.worker_centroid_maintain
                        else "claim/retry only; centroid maintenance unqualified"
                    ),
                }
            marker = "acx-fir-runtime-custody@1:" + secrets.token_hex(32)
            state = {
                "schema": "acx/fir-runtime-custody@1",
                "endpoint": endpoint(owner),
                "database_oid": db_oid,
                "marker": marker,
                "roles": {},
                "worker_centroid_maintain": args.worker_centroid_maintain,
            }
            for service, role in [("api", args.api_role), ("worker", args.worker_role)]:
                password = secrets.token_urlsafe(48)  # Generated alphabet contains no SQL quote.
                c.execute(
                    text(
                        f"CREATE ROLE \"{role}\" LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD '{password}'"
                    )
                )
                c.execute(text(f"COMMENT ON ROLE \"{role}\" IS '{marker}'"))
                grant_manifest(c, role, service, args.worker_centroid_maintain)
                row = role_row(c, role)
                role_safe(c, role, row)
                verify_grants(c, role, service, args.worker_centroid_maintain)
                state["roles"][service] = {"name": role, "oid": row["oid"], "password": password}
            runtime = runtime_profile(env, owner, state["roles"])
            # Files are staged while DDL is transactional. Any write/commit failure
            # removes only this invocation's files; no caller files are replaced.
            output.mkdir(mode=0o700)
            made_directory = True
            for name, value in [("custody.json", state), ("runtime.compose.json", runtime)]:
                path = output / name
                private_write(path, value)
                created_files.append(path)
        return {
            "mode": "applied",
            "roles": [args.api_role, args.worker_role],
            "worker_scope": (
                "claim/retry plus centroid MAINTAIN"
                if args.worker_centroid_maintain
                else "claim/retry only; centroid maintenance unqualified"
            ),
        }
    except BaseException:
        for path in created_files:
            path.unlink(missing_ok=True)
        if made_directory:
            output.rmdir()
        raise
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-dsn-file", required=True, help="0600 owner URL file, or - for redirected stdin")
    parser.add_argument("--runtime-environment-file", required=True, help="0600 JSON resolved existing environment")
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-port", required=True, type=int)
    parser.add_argument("--api-role", required=True)
    parser.add_argument("--worker-role", required=True)
    parser.add_argument("--profile-dir", required=True)
    parser.add_argument(
        "--worker-centroid-maintain",
        action="store_true",
        help="explicit PG17 MAINTAIN on the existing centroid view only; no ownership or BYPASSRLS",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = provision(args)
    except RefusalError as exc:
        print("refused: " + str(exc), file=sys.stderr)
        return 2
    except Exception:
        # Driver/JSON/OS errors may contain credentials, SQL text, or input bytes.
        print(
            "refused: provisioning failed; inspect target/schema/private custody without exposing credentials",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
