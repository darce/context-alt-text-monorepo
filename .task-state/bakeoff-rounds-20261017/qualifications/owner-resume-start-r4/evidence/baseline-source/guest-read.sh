#!/usr/bin/env bash
set -euo pipefail
# Run by ubuntu on backend only after start receipts bind the primary.
# Existing host trust is mandatory; never accept-new or ssh-keyscan.
ssh -n -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 \
 -o ConnectionAttempts=1 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 \
 -o UserKnownHostsFile=/home/ubuntu/.ssh/known_hosts ubuntu@10.0.1.9 \
 'set -eu
 timeout 10s hostname
 timeout 10s cat /proc/sys/kernel/random/boot_id
 instance_id="$(timeout 15s curl --fail --silent --show-error --connect-timeout 5 --max-time 10 -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/id)"
 test "$instance_id" = ocid1.instance.oc1.iad.anuwcljt2mcagaqcoop3g4euuthldjy6wbrhmh5yfjgznxdg353urol27bfa
 printf "%s\n" "$instance_id"
 timeout 10s df -B1 --output=source,size,avail,target /opt/acx-gpu/models /tmp
 timeout 10s findmnt -T /opt/acx-gpu/models -n -o SOURCE,MAJ:MIN,FSTYPE,TARGET
 timeout 10s cat /proc/meminfo
 timeout 10s nvidia-smi --query-gpu=uuid,index,name,memory.total,memory.free,memory.used --format=csv,noheader,nounits
 timeout 10s nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader,nounits
 timeout 10s systemctl show acx-gpu-vlm.service -p ActiveState -p SubState -p MainPID -p ControlGroup
 timeout 10s stat --printf="%s %n\n" /opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-q4.gguf /opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-mmproj.gguf
 '
