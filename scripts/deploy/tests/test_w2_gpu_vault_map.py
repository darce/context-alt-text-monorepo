from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_ROOT = REPO_ROOT / "config/env"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

PROD_VAULT_REFS = {
    "PGPASSWORD": "ocid1.vaultsecret.oc1.iad.amaaaaaa2mcagaqa5ka6inpwivjhrxm2ri4zdar46kdiijw32nzjly2uetzq",
    "POSTGRES_DSN": "ocid1.vaultsecret.oc1.iad.amaaaaaa2mcagaqaxwiwmhdx52g6obkujhq7ob4wxtp7n2xp5l2eu243wqqa",
    "POSTGRES_SYNC_DSN": "ocid1.vaultsecret.oc1.iad.amaaaaaa2mcagaqabr4qgl3jnrpfij72o4tv5ajujhwyyb4kd4ke7zwn73jq",
    "RECOGNITION_ADMIN_TOKEN": "ocid1.vaultsecret.oc1.iad.amaaaaaa2mcagaqaugzdmou5vnlaauvnyfct3qz36qenl72gxqhjkai7a2ea",
}


def test_prod_vault_map_is_derived_from_canonical_secret_refs():
    manifest_module = importlib.import_module("env.manifest")
    manifest = manifest_module.load_manifest(MANIFEST_ROOT)
    variables = {var.name: var for var in manifest.vars}
    mapping_var = variables["RECOGNITION_VAULT_SECRET_MAP"]
    password = variables["PGPASSWORD"]

    assert mapping_var.cls == "config"
    assert mapping_var.derive_vault_map is True
    assert not mapping_var.secret
    assert manifest_module.vault_secret_map(manifest, "svc-vm", "prod") == PROD_VAULT_REFS
    assert manifest_module.vault_secret_map(manifest, "svc-vm", "dev") == {}
    assert manifest_module.vault_secret_map(manifest, "svc-vm", "staging") == {}
    assert manifest_module.vault_secret_map(manifest, "svc-fir", "fir") == {}
    assert manifest_module.vault_secret_map(manifest, "svc-local", "local") == {}
    assert set(password.targets) == {"svc-local", "svc-vm"}
    assert password.secret == {
        "local": "keychain:acx-local/PGPASSWORD",
        "dev": "host:",
        "staging": "host:",
        "prod": f"vault:{PROD_VAULT_REFS['PGPASSWORD']}",
    }

    vm_password = manifest_module.effective_var(manifest, password, "svc-vm")
    assert vm_password.section == "Postgres"
    assert vm_password.example == ""
    assert vm_password.required is False
