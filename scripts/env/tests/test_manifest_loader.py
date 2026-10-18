from __future__ import annotations

import dataclasses
import importlib
import re

import pytest


def _manifest_module():
    return importlib.import_module("env.manifest")


BACKEND_TARGETS = '''
    version = 1

    [targets.api]
    audience = "backend"
    envs = ["local", "ci"]
    path = "apps/api/.env"
    example = "apps/api/.env.example"
    sections = ["Runtime", "Database", "Security"]

    [targets.worker]
    audience = "backend"
    envs = ["local"]
    path = "apps/worker/.env"
    example = "apps/worker/.env.example"
    sections = ["Database", "Security"]
'''

PUBLIC_TARGETS = '''
    version = 1

    [targets.client]
    audience = "public_build"
    envs = ["local"]
    path = "apps/client/.env"
    example = "apps/client/.env.example"
    sections = ["Runtime", "Database", "Security"]

    [targets.api]
    audience = "backend"
    envs = ["local", "ci"]
    path = "apps/api/.env"
    example = "apps/api/.env.example"
    sections = ["Runtime", "Database", "Security"]
'''


@pytest.mark.parametrize(
    ("targets", "fragments", "remove_targets", "filename", "needle"),
    [
        pytest.param(
            BACKEND_TARGETS,
            {"safe": ""},
            True,
            "targets.toml",
            "targets",
            id="missing-targets-file",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 2
                    [[var]]
                    name = "VERSIONED"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                    values = { local = "safe" }
                '''
            },
            False,
            "bad.toml",
            "version",
            id="unsupported-version",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "EXTRA_KEY"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                    values = { local = "safe" }
                    surprise = true
                '''
            },
            False,
            "bad.toml",
            "surprise",
            id="unknown-var-key",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "NO_EXAMPLE"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    values = { local = "safe" }
                '''
            },
            False,
            "bad.toml",
            "example",
            id="missing-example",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "BAD_REQUIRED"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                    required = "yes"
                    values = { local = "safe" }
                '''
            },
            False,
            "bad.toml",
            "required",
            id="wrong-required-type",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "a-first": '''
                    version = 1
                    [[var]]
                    name = "DUPLICATE_VAR"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "first"
                    values = { local = "first" }
                ''',
                "z-second": '''
                    version = 1
                    [[var]]
                    name = "DUPLICATE_VAR"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "second"
                    values = { local = "second" }
                ''',
            },
            False,
            "z-second.toml",
            "DUPLICATE_VAR",
            id="duplicate-name-across-fragments",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "UNKNOWN_TARGET_VAR"
                    class = "public"
                    targets = ["missing-target"]
                    section = "Runtime"
                    example = "safe"
                    values = { local = "safe" }
                '''
            },
            False,
            "bad.toml",
            ("UNKNOWN_TARGET_VAR", "missing-target"),
            id="unknown-target",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "BAD_SECTION"
                    class = "public"
                    targets = ["api"]
                    section = "NotConfigured"
                    example = "safe"
                    values = { local = "safe" }
                '''
            },
            False,
            "bad.toml",
            "section",
            id="section-not-in-target",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "SECTION_ON_EVERY_TARGET"
                    class = "public"
                    targets = ["api", "worker"]
                    section = "Runtime"
                    example = "safe"
                    values = { local = "safe" }
                '''
            },
            False,
            "bad.toml",
            "SECTION_ON_EVERY_TARGET",
            id="section-missing-from-one-target",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "TWO_SOURCES"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                    values = { local = "safe" }
                    derive = "${OTHER}"
                '''
            },
            False,
            "bad.toml",
            "TWO_SOURCES",
            id="values-and-derive",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "NO_SOURCE"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                '''
            },
            False,
            "bad.toml",
            "NO_SOURCE",
            id="no-values-secret-or-derive",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "SECRET_WITH_VALUES"
                    class = "secret"
                    targets = ["api"]
                    section = "Security"
                    example = "safe-example"
                    values = { local = "safe-value" }
                '''
            },
            False,
            "bad.toml",
            "values",
            id="secret-class-with-values",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "CONFIG_WITH_SECRET_REF"
                    class = "config"
                    targets = ["api"]
                    section = "Security"
                    example = "safe-example"
                    secret = { local = "env:SOURCE" }
                '''
            },
            False,
            "bad.toml",
            "secret",
            id="non-secret-class-with-secret-ref",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "BROKEN_DERIVE"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                    derive = "${MISSING_VAR}"
                '''
            },
            False,
            "bad.toml",
            "MISSING_VAR",
            id="derive-unknown-var",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "CYCLE_A"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe-a"
                    derive = "${CYCLE_B}"

                    [[var]]
                    name = "CYCLE_B"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe-b"
                    derive = "${CYCLE_A}"
                '''
            },
            False,
            "bad.toml",
            "CYCLE_A",
            id="derive-cycle",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "PRIVATE_SOURCE"
                    class = "secret"
                    targets = ["api"]
                    section = "Security"
                    example = "private-example"
                    secret = { local = "env:PRIVATE_INPUT" }

                    [[var]]
                    name = "PUBLIC_DERIVED_CONFIG"
                    class = "config"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                    derive = "${PRIVATE_SOURCE}"
                '''
            },
            False,
            "bad.toml",
            "PUBLIC_DERIVED_CONFIG",
            id="config-derive-references-secret",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "BAD_ENV_MAPPING"
                    class = "public"
                    targets = ["api"]
                    section = "Runtime"
                    example = "safe"
                    values = { prod = "safe" }
                '''
            },
            False,
            "bad.toml",
            ("BAD_ENV_MAPPING", "prod"),
            id="env-not-in-target",
        ),
        pytest.param(
            BACKEND_TARGETS,
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "BAD_SECRET_SCHEME"
                    class = "secret"
                    targets = ["api"]
                    section = "Security"
                    example = "safe-example"
                    secret = { local = "file:private-item" }
                '''
            },
            False,
            "bad.toml",
            ("BAD_SECRET_SCHEME", "file"),
            id="unsupported-secret-scheme",
        ),
    ],
)
def test_load_manifest_rejects_invalid_inputs(
    write_manifest, targets, fragments, remove_targets, filename, needle
):
    root = write_manifest(targets, **fragments)
    if remove_targets:
        (root / "manifest.d" / "targets.toml").unlink()

    module = _manifest_module()
    with pytest.raises(module.ManifestError) as raised:
        module.load_manifest(root)

    message = str(raised.value)
    assert filename in message
    for expected in needle if isinstance(needle, tuple) else (needle,):
        assert expected in message
    assert "private-example" not in message


def test_load_manifest_returns_ordered_typed_manifest_and_default_required(write_manifest):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "10-base": '''
                version = 1
                [[var]]
                name = "ZETA"
                class = "config"
                targets = ["api"]
                section = "Runtime"
                doc = "First declaration in the first file."
                example = "local-zeta"
                values = { local = "zeta-local", ci = "zeta-ci" }

                [[var]]
                name = "ALPHA"
                class = "public"
                targets = ["worker"]
                section = "Database"
                example = "local-alpha"
                required = false
                values = { local = "alpha-local" }
            ''',
            "20-extra": '''
                version = 1
                [[var]]
                name = "MIDDLE"
                class = "public"
                targets = ["api"]
                section = "Security"
                example = "local-middle"
                values = { local = "middle-local", ci = "middle-ci" }
            ''',
        },
    )
    module = _manifest_module()
    manifest = module.load_manifest(root)

    assert manifest.targets["api"] == module.Target(
        name="api",
        audience="backend",
        envs=("local", "ci"),
        path="apps/api/.env",
        example="apps/api/.env.example",
        sections=("Runtime", "Database", "Security"),
    )
    assert manifest.targets["worker"] == module.Target(
        name="worker",
        audience="backend",
        envs=("local",),
        path="apps/worker/.env",
        example="apps/worker/.env.example",
        sections=("Database", "Security"),
    )
    assert [var.name for var in manifest.vars] == ["ZETA", "ALPHA", "MIDDLE"]
    assert manifest.vars[0] == module.Var(
        name="ZETA",
        cls="config",
        targets=("api",),
        section="Runtime",
        doc="First declaration in the first file.",
        example="local-zeta",
        required=True,
        values={"local": "zeta-local", "ci": "zeta-ci"},
        secret={},
        derive=None,
        source="10-base.toml",
    )
    assert manifest.vars[1].required is False
    assert manifest.vars[1].source == "10-base.toml"
    assert manifest.vars[2].source == "20-extra.toml"


def test_manifest_dataclasses_are_frozen(write_manifest):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "vars": '''
                version = 1
                [[var]]
                name = "FROZEN_VAR"
                class = "public"
                targets = ["api"]
                section = "Runtime"
                example = "safe"
                values = { local = "safe" }
            '''
        },
    )
    module = _manifest_module()
    manifest = module.load_manifest(root)

    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.targets["api"].name = "changed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.vars[0].name = "changed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.vars = ()


@pytest.mark.parametrize(
    ("fragments", "bad_var"),
    [
        pytest.param(
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "VITE_SERVER_VALUE"
                    class = "secret"
                    targets = ["client"]
                    section = "Security"
                    example = "private-example-never-echo"
                    secret = { local = "env:PRIVATE_INPUT" }
                '''
            },
            "VITE_SERVER_VALUE",
            id="secret-class",
        ),
        pytest.param(
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "PRIVATE_SOURCE"
                    class = "secret"
                    targets = ["api"]
                    section = "Security"
                    example = "private-example-never-echo"
                    secret = { local = "env:PRIVATE_INPUT" }

                    [[var]]
                    name = "VITE_PUBLIC_URL"
                    class = "config"
                    targets = ["client"]
                    section = "Runtime"
                    example = "safe"
                    derive = "${PRIVATE_SOURCE}"
                '''
            },
            "VITE_PUBLIC_URL",
            id="derive-reaches-secret",
        ),
        pytest.param(
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "PRIVATE_SOURCE"
                    class = "secret"
                    targets = ["api"]
                    section = "Security"
                    example = "private-example-never-echo"
                    secret = { local = "env:PRIVATE_INPUT" }

                    [[var]]
                    name = "INTERNAL_SECRET_ALIAS"
                    class = "secret"
                    targets = ["api"]
                    section = "Security"
                    example = "private-alias-never-echo"
                    derive = "${PRIVATE_SOURCE}"

                    [[var]]
                    name = "VITE_PUBLIC_RESULT"
                    class = "config"
                    targets = ["client"]
                    section = "Runtime"
                    example = "safe"
                    derive = "${INTERNAL_SECRET_ALIAS}"
                '''
            },
            "VITE_PUBLIC_RESULT",
            id="transitive-derive-reaches-secret",
        ),
        pytest.param(
            {
                "bad": '''
                    version = 1
                    [[var]]
                    name = "API_ENDPOINT"
                    class = "public"
                    targets = ["client"]
                    section = "Runtime"
                    example = "safe"
                    values = { local = "safe" }
                '''
            },
            "API_ENDPOINT",
            id="missing-vite-prefix",
        ),
        *[
            pytest.param(
                {
                    "bad": f'''
                        version = 1
                        [[var]]
                        name = "{name}"
                        class = "public"
                        targets = ["client"]
                        section = "Runtime"
                        example = "safe"
                        values = {{ local = "safe" }}
                    '''
                },
                name,
                id=f"sensitive-name-{name.lower()}",
            )
            for name in (
                "VITE_API_TOKEN",
                "VITE_DB_PASSWORD",
                "VITE_SIGNING_KEY",
                "VITE_CLIENT_SECRET",
            )
        ],
    ],
)
def test_public_build_guard_refuses_secret_material(write_manifest, fragments, bad_var):
    root = write_manifest(PUBLIC_TARGETS, **fragments)
    module = _manifest_module()

    with pytest.raises(module.ManifestError) as raised:
        module.load_manifest(root)

    message = str(raised.value)
    assert "bad.toml" in message
    assert bad_var in message
    assert "private-example-never-echo" not in message
    assert "private-alias-never-echo" not in message


@pytest.mark.parametrize("name", ["VITE_CLERK_PUBLISHABLE_KEY", "VITE_PORTAL_ENABLED"])
def test_public_build_guard_accepts_safe_public_names(write_manifest, name):
    root = write_manifest(
        PUBLIC_TARGETS,
        **{
            "safe": f'''
                version = 1
                [[var]]
                name = "{name}"
                class = "public"
                targets = ["client"]
                section = "Runtime"
                example = "safe-example"
                values = {{ local = "safe-value" }}
            '''
        },
    )
    module = _manifest_module()
    manifest = module.load_manifest(root)

    assert manifest.vars[0].name == name


@pytest.mark.parametrize(
    ("field", "offending"),
    [
        pytest.param("example", "sk_" + "test_" + "sensitive", id="test-key-in-example"),
        pytest.param("values", "sk_" + "test_" + "sensitive", id="test-key-in-values"),
        pytest.param("example", "sk_" + "live_" + "sensitive", id="live-key-in-example"),
        pytest.param("values", "sk_" + "live_" + "sensitive", id="live-key-in-values"),
        pytest.param("example", "rk_" + "test_" + "sensitive", id="test-refresh-key-in-example"),
        pytest.param("values", "rk_" + "test_" + "sensitive", id="test-refresh-key-in-values"),
        pytest.param("example", "rk_" + "live_" + "sensitive", id="refresh-key-in-example"),
        pytest.param("values", "rk_" + "live_" + "sensitive", id="refresh-key-in-values"),
        pytest.param("example", "wh" + "sec_" + "sensitive", id="webhook-key-in-example"),
        pytest.param("values", "wh" + "sec_" + "sensitive", id="webhook-key-in-values"),
        pytest.param(
            "example",
            "-----" + "BEGIN PRIVATE KEY-----",
            id="pem-line-in-example",
        ),
        pytest.param(
            "values",
            "-----" + "BEGIN PRIVATE KEY-----",
            id="pem-line-in-values",
        ),
    ],
)
@pytest.mark.parametrize(
    ("targets", "target_name", "var_name"),
    [
        pytest.param(BACKEND_TARGETS, "api", "LITERAL_GUARD_INPUT", id="backend"),
        pytest.param(PUBLIC_TARGETS, "client", "VITE_LITERAL_INPUT", id="public-build"),
    ],
)
def test_literal_guard_rejects_known_secret_shapes(
    write_manifest, field, offending, targets, target_name, var_name
):
    example = f'example = "{offending}"' if field == "example" else 'example = "safe"'
    values = (
        f'values = {{ local = "{offending}" }}'
        if field == "values"
        else 'values = { local = "safe" }'
    )
    root = write_manifest(
        targets,
        **{
            "literal": f'''
                version = 1
                [[var]]
                name = "{var_name}"
                class = "public"
                targets = ["{target_name}"]
                section = "Runtime"
                {example}
                {values}
            '''
        },
    )
    module = _manifest_module()

    with pytest.raises(module.ManifestError) as raised:
        module.load_manifest(root)

    message = str(raised.value)
    assert "literal.toml" in message
    assert var_name in message
    assert offending not in message


@pytest.mark.parametrize("example", ["pk_test_abc", "work"])
def test_literal_guard_accepts_nonsecret_examples(write_manifest, example):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "safe": f'''
                version = 1
                [[var]]
                name = "SAFE_LITERAL"
                class = "public"
                targets = ["api"]
                section = "Runtime"
                example = "{example}"
                values = {{ local = "safe" }}
            '''
        },
    )
    module = _manifest_module()
    manifest = module.load_manifest(root)

    assert manifest.vars[0].example == example


def test_target_digest_is_64_lowercase_hex(write_manifest):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "vars": '''
                version = 1
                [[var]]
                name = "DIGEST_VAR"
                class = "public"
                targets = ["api"]
                section = "Runtime"
                example = "safe"
                values = { local = "safe" }
            '''
        },
    )
    module = _manifest_module()
    manifest = module.load_manifest(root)

    assert re.fullmatch(r"[0-9a-f]{64}", module.target_digest(manifest, "api"))


def test_target_digest_ignores_fragment_assignment_and_source(write_manifest):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "a-first": '''
                version = 1
                [[var]]
                name = "ALPHA"
                class = "public"
                targets = ["api"]
                section = "Runtime"
                example = "alpha"
                values = { local = "alpha" }
            ''',
            "z-second": '''
                version = 1
                [[var]]
                name = "BETA"
                class = "config"
                targets = ["api"]
                section = "Database"
                example = "beta"
                values = { local = "beta" }
            ''',
        },
    )
    module = _manifest_module()
    first = module.target_digest(module.load_manifest(root), "api")

    manifest_dir = root / "manifest.d"
    for fragment in manifest_dir.glob("*.toml"):
        if fragment.name != "targets.toml":
            fragment.unlink()
    write_manifest(
        BACKEND_TARGETS,
        **{
            "10-renamed": '''
                version = 1
                [[var]]
                name = "BETA"
                class = "config"
                targets = ["api"]
                section = "Database"
                example = "beta"
                values = { local = "beta" }
            ''',
            "20-renamed": '''
                version = 1
                [[var]]
                name = "ALPHA"
                class = "public"
                targets = ["api"]
                section = "Runtime"
                example = "alpha"
                values = { local = "alpha" }
            ''',
        },
    )
    second = module.target_digest(module.load_manifest(root), "api")

    assert second == first


def test_target_digest_changes_when_var_example_changes(write_manifest):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "vars": '''
                version = 1
                [[var]]
                name = "CHANGING_VAR"
                class = "public"
                targets = ["api"]
                section = "Runtime"
                example = "before"
                values = { local = "same-value" }
            '''
        },
    )
    module = _manifest_module()
    before = module.target_digest(module.load_manifest(root), "api")
    (root / "manifest.d" / "vars.toml").write_text(
        '''
            version = 1
            [[var]]
            name = "CHANGING_VAR"
            class = "public"
            targets = ["api"]
            section = "Runtime"
            example = "after"
            values = { local = "same-value" }
        ''',
        encoding="utf-8",
    )
    after = module.target_digest(module.load_manifest(root), "api")

    assert after != before


def test_target_digest_ignores_changes_to_vars_for_other_targets(write_manifest):
    targets = '''
        version = 1
        [targets.api]
        audience = "backend"
        envs = ["local"]
        sections = ["Runtime"]
        [targets.worker]
        audience = "backend"
        envs = ["local"]
        sections = ["Runtime"]
    '''
    root = write_manifest(
        targets,
        **{
            "vars": '''
                version = 1
                [[var]]
                name = "API_VAR"
                class = "public"
                targets = ["api"]
                section = "Runtime"
                example = "api-example"
                values = { local = "api-value" }

                [[var]]
                name = "WORKER_VAR"
                class = "public"
                targets = ["worker"]
                section = "Runtime"
                example = "worker-before"
                values = { local = "worker-value" }
            '''
        },
    )
    module = _manifest_module()
    before = module.target_digest(module.load_manifest(root), "api")
    (root / "manifest.d" / "vars.toml").write_text(
        '''
            version = 1
            [[var]]
            name = "API_VAR"
            class = "public"
            targets = ["api"]
            section = "Runtime"
            example = "api-example"
            values = { local = "api-value" }

            [[var]]
            name = "WORKER_VAR"
            class = "public"
            targets = ["worker"]
            section = "Runtime"
            example = "worker-after"
            values = { local = "worker-value" }
        ''',
        encoding="utf-8",
    )
    after = module.target_digest(module.load_manifest(root), "api")

    assert after == before


def test_literal_guard_rejects_secret_shaped_derive(write_manifest):
    offending = "sk_" + "live_" + "x"
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "literal": f'''
                version = 1
                [[var]]
                name = "DERIVED_LITERAL"
                class = "config"
                targets = ["api"]
                section = "Runtime"
                example = "safe"
                derive = "prefix-{offending}"
            '''
        },
    )
    module = _manifest_module()

    with pytest.raises(module.ManifestError) as raised:
        module.load_manifest(root)

    message = str(raised.value)
    assert "literal.toml" in message
    assert "DERIVED_LITERAL" in message
    assert "derive" in message
    assert offending not in message


def test_derive_rejects_reference_missing_a_target(write_manifest):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "scope": '''
                version = 1
                [[var]]
                name = "R"
                class = "config"
                targets = ["api"]
                section = "Database"
                example = "safe"
                values = { local = "safe" }

                [[var]]
                name = "D"
                class = "config"
                targets = ["api", "worker"]
                section = "Database"
                example = "safe"
                derive = "${R}"
            '''
        },
    )
    module = _manifest_module()

    with pytest.raises(module.ManifestError) as raised:
        module.load_manifest(root)

    message = str(raised.value)
    assert "R" in message
    assert "D" in message
    assert "worker" in message


def test_derive_accepts_reference_covering_every_target(write_manifest):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "scope": '''
                version = 1
                [[var]]
                name = "R"
                class = "config"
                targets = ["api", "worker"]
                section = "Database"
                example = "safe"
                values = { local = "safe" }

                [[var]]
                name = "D"
                class = "config"
                targets = ["api", "worker"]
                section = "Database"
                example = "safe"
                derive = "${R}"
            '''
        },
    )
    module = _manifest_module()

    manifest = module.load_manifest(root)

    assert [var.name for var in manifest.vars] == ["R", "D"]


@pytest.mark.parametrize("derive", ["${PGHOST", "$PGHOST", "${}", "${lower}"])
def test_derive_rejects_malformed_interpolation(write_manifest, derive):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "malformed": f'''
                version = 1
                [[var]]
                name = "MALFORMED_DERIVE"
                class = "config"
                targets = ["api"]
                section = "Runtime"
                example = "safe"
                derive = "{derive}"
            '''
        },
    )
    module = _manifest_module()

    with pytest.raises(module.ManifestError) as raised:
        module.load_manifest(root)

    message = str(raised.value)
    assert "malformed.toml" in message
    assert "MALFORMED_DERIVE.derive" in message


@pytest.mark.parametrize(
    ("cls", "source"),
    [("config", "values"), ("secret", "secret")],
)
def test_empty_value_source_tables_are_present(write_manifest, cls, source):
    root = write_manifest(
        BACKEND_TARGETS,
        **{
            "empty": f'''
                version = 1
                [[var]]
                name = "EMPTY_SOURCE"
                class = "{cls}"
                targets = ["api"]
                section = "Database"
                example = "safe"
                {source} = {{}}
            '''
        },
    )
    module = _manifest_module()

    manifest = module.load_manifest(root)

    assert getattr(manifest.vars[0], source) == {}


# Contract v2: kept separate from the original contract tests.
V2_TARGETS = '''version = 1
[targets.a]
audience = "backend"
envs = ["local"]
sections = ["Database", "Other"]
[targets.b]
audience = "backend"
envs = ["dev"]
sections = ["Database", "Other"]
'''
V2_VAR = '''[[var]]
name = "VALUE"
class = "config"
targets = ["a", "b"]
section = "Database"
doc = "base doc"
example = "base"
values = {}
'''


def _v2_load(write_manifest, *, targets=V2_TARGETS, var=V2_VAR, override=''):
    return _manifest_module().load_manifest(write_manifest(
        targets, **{"10-overrides": "version = 1\nvar = []\n" + override,
                    "20-vars": "version = 1\n" + var}))


def test_v2_target_doc_loads(write_manifest):
    manifest = _v2_load(write_manifest, targets=V2_TARGETS + 'doc = "instructions"\n')
    assert manifest.targets['b'].doc == 'instructions'
    assert manifest.targets['a'].doc is None


def test_v2_target_doc_requires_string(write_manifest):
    # Check the accepted type first, so unknown-key rejection cannot satisfy this test.
    _v2_load(write_manifest, targets=V2_TARGETS + 'doc = "instructions"\n')
    module = _manifest_module()
    with pytest.raises(module.ManifestError) as caught:
        _v2_load(write_manifest, targets=V2_TARGETS + 'doc = 42\n')
    assert type(caught.value) is module.ManifestError
    assert 'targets.toml' in str(caught.value)
    assert 'doc' in str(caught.value)


def test_v2_target_doc_changes_digest(write_manifest):
    module = _manifest_module()
    first = _v2_load(write_manifest, targets=V2_TARGETS + 'doc = "first"\n')
    second = _v2_load(write_manifest, targets=V2_TARGETS + 'doc = "second"\n')
    assert module.target_digest(first, 'b') != module.target_digest(second, 'b')


@pytest.mark.parametrize(('field', 'literal', 'expected'), [
    ('example', '"custom"', 'custom'), ('required', 'false', False),
    ('doc', '"custom doc"', 'custom doc'), ('section', '"Other"', 'Other'),
])
def test_v2_effective_var_applies_override(write_manifest, field, literal, expected):
    module = _manifest_module()
    manifest = _v2_load(write_manifest, override=(
        '[[override]]\nname = "VALUE"\ntarget = "a"\n' + field + ' = ' + literal))
    base = manifest.vars[0]
    override = manifest.overrides[('VALUE', 'a')]
    assert isinstance(override, module.Override)
    assert override.name == 'VALUE' and override.target == 'a'
    assert override.source.endswith('10-overrides.toml')
    for key in ('example', 'required', 'doc', 'section'):
        assert getattr(override, key) == (expected if key == field else None)
    assert module.effective_var(manifest, base, 'a') == dataclasses.replace(base, **{field: expected})
    assert module.effective_var(manifest, base, 'b') == base
    with pytest.raises(dataclasses.FrozenInstanceError):
        override.name = 'CHANGED'


@pytest.mark.parametrize(('body', 'needle'), [
    ('name="VALUE"\ntarget="a"\nexample="x"\nsurprise=true', 'surprise'),
    ('target="a"\nexample="x"', 'name'),
    ('name="VALUE"\nexample="x"', 'target'),
    ('name="VALUE"\ntarget="a"', 'VALUE'),
    ('name="MISSING"\ntarget="a"\nexample="x"', 'MISSING'),
    ('name="VALUE"\ntarget="outside"\nexample="x"', 'outside'),
    ('name="VALUE"\ntarget="a"\nsection="Missing"', 'section'),
    *[(f'name="VALUE"\ntarget="a"\n{key}={value}', key)
      for key, value in [('example', '42'), ('required', '"yes"'), ('doc', '42'), ('section', '42')]],
    ('name=42\ntarget="a"\nexample="x"', 'name'),
    ('name="VALUE"\ntarget=42\nexample="x"', 'target'),
], ids=['unknown-key', 'missing-name', 'missing-target', 'no-fields', 'unknown-var',
        'wrong-target', 'unknown-section', 'example-type', 'required-type', 'doc-type',
        'section-type', 'name-type', 'target-type'])
def test_v2_override_refusal(write_manifest, body, needle):
    module = _manifest_module()
    with pytest.raises(module.ManifestError) as caught:
        _v2_load(write_manifest, override='[[override]]\n' + body)
    assert type(caught.value) is module.ManifestError
    assert '10-overrides.toml' in str(caught.value)
    assert needle in str(caught.value)


def test_v2_duplicate_override_across_fragments_refused(write_manifest):
    module = _manifest_module()
    body = '[[override]]\nname="VALUE"\ntarget="a"\nexample="x"\n'
    root = write_manifest(V2_TARGETS, **{
        '10-first': 'version=1\n' + V2_VAR + body,
        '20-second': 'version=1\n' + body})
    with pytest.raises(module.ManifestError) as caught:
        module.load_manifest(root)
    assert type(caught.value) is module.ManifestError
    for needle in ('20-second.toml', 'VALUE', 'a'):
        assert needle in str(caught.value)


@pytest.mark.parametrize('value', ['sk_' + 'live_x', 'sk_' + 'test_x',
                                  'rk_' + 'live_x', 'rk_' + 'test_x',
                                  'wh' + 'sec_x', '-----' + 'BEGIN KEY'])
def test_v2_override_example_literal_refused(write_manifest, value):
    module = _manifest_module()
    with pytest.raises(module.ManifestError) as caught:
        _v2_load(write_manifest, override=(
            '[[override]]\nname="VALUE"\ntarget="a"\nexample="' + value + '"'))
    assert type(caught.value) is module.ManifestError
    assert '10-overrides.toml' in str(caught.value)
    assert 'example' in str(caught.value)
    assert value not in str(caught.value)


def test_v2_section_override_relaxes_base_section_membership(write_manifest):
    manifest = _v2_load(write_manifest,
        targets=V2_TARGETS.replace('sections = ["Database", "Other"]',
                                  'sections = ["Other"]', 1),
        override='[[override]]\nname="VALUE"\ntarget="a"\nsection="Other"')
    assert _manifest_module().effective_var(manifest, manifest.vars[0], 'a').section == 'Other'


@pytest.mark.parametrize('changed_target', ['a', 'b'])
def test_v2_override_digest_is_target_specific(write_manifest, changed_target):
    module = _manifest_module()
    body = f'[[override]]\nname="VALUE"\ntarget="{changed_target}"\nexample='
    first = _v2_load(write_manifest, override=body + '"first"')
    second = _v2_load(write_manifest, override=body + '"second"')
    assert (module.target_digest(first, 'a') != module.target_digest(second, 'a')) == (changed_target == 'a')


@pytest.mark.parametrize('source', ['values', 'secret'])
def test_v2_env_keys_use_target_union(write_manifest, source):
    var = V2_VAR.replace('values = {}', source + ' = {local="' +
        ('env:LOCAL", dev="env:DEV' if source == 'secret' else 'x", dev="y') + '"}')
    if source == 'secret':
        var = var.replace('class = "config"', 'class = "secret"')
    manifest = _v2_load(write_manifest, var=var)
    assert set(getattr(manifest.vars[0], source)) == {'local', 'dev'}


@pytest.mark.parametrize('source', ['values', 'secret'])
def test_v2_env_outside_union_is_refused(write_manifest, source):
    module = _manifest_module()
    var = V2_VAR.replace('values = {}', source + ' = {local="' +
        ('env:LOCAL", dev="env:DEV' if source == 'secret' else 'x", dev="y') + '"}')
    if source == 'secret':
        var = var.replace('class = "config"', 'class = "secret"')
    _v2_load(write_manifest, var=var)
    with pytest.raises(module.ManifestError) as caught:
        _v2_load(write_manifest, var=var.replace('dev=', 'stage='))
    assert type(caught.value) is module.ManifestError
    for needle in ('20-vars.toml', 'VALUE', 'stage'):
        assert needle in str(caught.value)
