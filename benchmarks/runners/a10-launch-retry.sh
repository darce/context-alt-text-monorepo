#!/usr/bin/env bash
# Multi-AD A10 launch-retry loop (ALTQ-1 / VLM-6 bake-off).
# Rotates AD-2 -> AD-3 launching a fresh VM.GPU.A10.1 from the custom image on the
# public subnet until one AD has capacity. Failed launches (no capacity) are NOT
# billed — only a RUNNING instance costs money (~$2/hr). Ctrl-C to stop.
#
# After it lands: reach the box by its public IP over SSH (ssh ubuntu@<ip> with
# ~/.ssh/id_rsa), rsync the corpus, run on-box, then TERMINATE (pair every launch
# with a terminate — the box lives outside terraform).
set -uo pipefail

COMP="ocid1.tenancy.oc1..aaaaaaaarnwywmplftprwcpsytd2g5wjxht45o4jgpidrjhulnzv24qp7q5q"
IMAGE="ocid1.image.oc1.iad.aaaaaaaaothcmrzxvkbys2cjlu7kl72pphorfvav7di4rzrsxemo4das2cka"
SUBNET="ocid1.subnet.oc1.iad.aaaaaaaaho2atrtzvvmki63isv76losmmq5aroap35vgzkdfjkkiaguhslhq"
SHAPE="VM.GPU.A10.1"
SSH_KEY="$HOME/.ssh/id_rsa.pub"
REGION="us-ashburn-1"
ADS=("saEG:US-ASHBURN-AD-2" "saEG:US-ASHBURN-AD-3")   # AD-1 has no free limit slot
NAME="acx-gpu-burst-$(date -u +%m%d)"
SLEEP=45

echo "Launch-retry: $SHAPE from custom image, rotating ${ADS[*]}"
attempt=0
while true; do
  for AD in "${ADS[@]}"; do
    attempt=$((attempt+1))
    printf '%s  attempt %d  %s ... ' "$(date -u +%H:%M:%S)" "$attempt" "${AD##*-}"
    OUT=$(oci compute instance launch \
      --compartment-id "$COMP" --availability-domain "$AD" \
      --shape "$SHAPE" --image-id "$IMAGE" --subnet-id "$SUBNET" \
      --display-name "$NAME" --assign-public-ip true \
      --metadata "{\"ssh_authorized_keys\": \"$(cat "$SSH_KEY")\"}" \
      --region "$REGION" 2>&1)
    IID=$(echo "$OUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])" 2>/dev/null)
    if [ -n "$IID" ]; then
      echo "accepted -> $IID ; waiting for RUNNING"
      for i in $(seq 1 40); do
        ST=$(oci compute instance get --instance-id "$IID" --region "$REGION" 2>/dev/null \
             | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['lifecycle-state'])" 2>/dev/null)
        [ "$ST" = "RUNNING" ] && break
        [ "$ST" = "TERMINATED" ] || [ "$ST" = "TERMINATING" ] && { echo "  launch died ($ST)"; IID=""; break; }
        sleep 10
      done
      if [ -n "$IID" ] && [ "$ST" = "RUNNING" ]; then
        PRIV=$(oci compute instance list-vnics --instance-id "$IID" --region "$REGION" 2>/dev/null \
             | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['private-ip'])" 2>/dev/null)
        echo "LANDED in ${AD##*-}"
        echo "  instance: $IID"
        echo "  private-ip: $PRIV   (reach via tailscale jump: ssh -J <gate> ubuntu@$PRIV)"
        echo "  REMEMBER: terminate when done -> oci compute instance terminate --instance-id $IID --force"
        exit 0
      fi
      continue
    fi
    if echo "$OUT" | grep -qi 'Out of host capacity\|OutOfCapacity\|InternalError'; then
      echo "no capacity"
    else
      echo "ERROR (non-capacity) — stopping:"; echo "$OUT" | head -5; exit 1
    fi
  done
  sleep "$SLEEP"
done
