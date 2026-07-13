#!/usr/bin/env bash
# ACX OCI orchestration helpers. Source this: `source infra/oci/oci-lib.sh`.
# It sources acx-oci.env (single source of truth for OCIDs) and exposes the
# bake/monitor/stop/capture operations used by the VLM-3B GPU provisioning loop,
# so no OCID or command is duplicated across scripts.

_ACX_OCI_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$_ACX_OCI_LIB_DIR/acx-oci.env"

# Strip the OCI CLI's noisy SyntaxWarning banner from stdout.
acx_clean(){ grep -vE "SyntaxWarning|invalid escape|INSTANCE_CONSOLE_CONNECTION|Did you mean|raw string is also"; }

# Lifecycle state of an instance OCID.
acx_state(){ oci compute instance get --instance-id "$1" --query 'data."lifecycle-state"' --raw-output 2>/dev/null | acx_clean; }

# Capture + print the latest ACX_BAKE_* console markers for an instance.
acx_console_markers(){
  local inst="$1" ch
  ch=$(oci compute console-history capture --instance-id "$inst" --query 'data.id' --raw-output 2>/dev/null | acx_clean | grep ocid1 | head -1)
  [ -z "$ch" ] && return 0
  sleep 8
  oci compute console-history get-content --instance-console-history-id "$ch" --file - --length 140000 2>/dev/null \
    | acx_clean | grep -aoE 'ACX_BAKE_(STEP|SUCCESS|FAILED)[^\r]*' | tail -4
}

# Launch the GPU bake host from the env + cloud-init. Prints the new instance OCID.
# $1 = path to an ssh authorized_keys file to inject.
acx_launch_bake(){
  local authkeys="$1"
  oci compute instance launch \
    --compartment-id "$ACX_COMPARTMENT_OCID" --availability-domain "$ACX_GPU_AD" \
    --shape "$ACX_GPU_SHAPE" --image-id "$ACX_UBUNTU2404_IMAGE_OCID" \
    --subnet-id "$ACX_PUBLIC_SUBNET_OCID" --assign-public-ip true \
    --boot-volume-size-in-gbs "$ACX_GPU_BOOT_GB" --display-name acx-gpu-bake \
    --ssh-authorized-keys-file "$authkeys" \
    --user-data-file "$_ACX_OCI_LIB_DIR/gpu-bake-cloud-init.yaml" \
    --agent-config '{"pluginsConfig":[{"name":"Compute Instance Run Command","desiredState":"ENABLED"}]}' \
    --freeform-tags '{"project":"acx","role":"gpu-bake","task":"VLM-3B","ephemeral":"true"}' \
    --query 'data.id' --raw-output 2>/dev/null | acx_clean | grep ocid1 | head -1
}

# Control-plane STOP (billing safety — do not trust guest poweroff). Waits STOPPED.
acx_ensure_stopped(){
  local inst="$1" i s
  oci compute instance action --instance-id "$inst" --action STOP >/dev/null 2>&1
  for i in $(seq 1 30); do s=$(acx_state "$inst"); [ "$s" = "STOPPED" ] && return 0; sleep 15; done
  return 1
}

# Terminate an instance and its boot volume.
acx_terminate(){ oci compute instance terminate --instance-id "$1" --preserve-boot-volume false --force >/dev/null 2>&1; }

# Capture a custom image from a (stopped) instance. $1=instance $2=image display name. Prints image OCID.
acx_capture_image(){
  oci compute image create --compartment-id "$ACX_COMPARTMENT_OCID" --instance-id "$1" \
    --display-name "$2" --query 'data.id' --raw-output 2>/dev/null | acx_clean | grep ocid1 | head -1
}

# Persist a produced value back into acx-oci.env (e.g. acx_set_env ACX_GPU_IMAGE_OCID ocid1...).
acx_set_env(){
  local key="$1" val="$2" f="$_ACX_OCI_LIB_DIR/acx-oci.env"
  if grep -q "^export ${key}=" "$f"; then
    sed -i.bak "s|^export ${key}=.*|export ${key}=\"${val}\"|" "$f" && rm -f "$f.bak"
  else
    echo "export ${key}=\"${val}\"" >> "$f"
  fi
}
