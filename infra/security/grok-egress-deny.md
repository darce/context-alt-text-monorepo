# Grok offload egress-deny (block the repo-bundle exfil channel)

**Threat.** The grok Build CLI uploads the full `.git` object database to
`gs://grok-code-session-traces` regardless of any opt-out
("xAI Grok CLI Uploads Full Repos and Secrets, Opt-Out Ignored"). This is the
robust *primary* control; the shallow-clone sandbox (`scripts/secure-offload-clone.sh`
/ workbay `ShallowSandbox`) is the complementary git-layer control.

## Channel separation (why a host-level deny works)

| Purpose | Hosts | Action |
| --- | --- | --- |
| **Exfil upload** | `storage.googleapis.com`, `www.googleapis.com`, `oauth2.googleapis.com`, `iamcredentials.googleapis.com` (bucket `grok-code-session-traces`, `/upload/storage`) | **DENY** |
| Inference / auth / models | `api.x.ai`, `cli-chat-proxy.grok.com`, `grok.com`, `accounts.x.ai` | ALLOW |

The upload goes **direct to Google** (GCS), inference goes to **xAI** — different
hosts, so denying `*.googleapis.com` stops the bundle without touching inference.

## WHERE to apply — confirmed: the operator laptop, not the OCI VM

Grok offload runs as a **local CLI driver on the operator laptop** (inference is the
only remote leg — `harness-protocol.yaml` §host: "operator laptop running GROK-ONLY
offload"). The OCI VM does **not** run grok today. So the deny that stops the *current*
exfil path is on the **laptop**. The OCI-VM variant below applies only if offload is
moved to run on a VM.

## Primary control — grok-scoped filtering+logging proxy (host-agnostic)

`scripts/grok-egress-proxy.py` is an allowlist HTTPS CONNECT proxy: only x.ai/grok.com
may be reached; googleapis (and anything else) is denied + logged. Only traffic that
uses the proxy is affected (not the whole box), and it works identically on the laptop
or an OCI VM.

```bash
python3 scripts/grok-egress-proxy.py --port 8899 --log egress.log &
HTTPS_PROXY=http://127.0.0.1:8899 HTTP_PROXY=http://127.0.0.1:8899 NO_PROXY= grok "task"
```

Validated 2026-07-13: `api.x.ai` → `ALLOW` (tunnel established); `storage.googleapis.com`
+ `oauth2.googleapis.com` → `EXFIL-BLOCKED` (refused). Wire this into the offload
lane launcher so grok always runs with `HTTPS_PROXY` set (belt with the sandbox's
suspenders).

## OCI-VM variant (only if offload moves to a VM) — iptables

Coarser (IP-based; GCS IPs rotate, so refresh on a timer or prefer the proxy above):

```bash
# allow x.ai implicitly (default OUTPUT ACCEPT); reject the Google upload hosts
for h in storage.googleapis.com www.googleapis.com oauth2.googleapis.com iamcredentials.googleapis.com; do
  for ip in $(getent ahosts "$h" | awk '{print $1}' | sort -u); do
    sudo iptables -A OUTPUT -d "$ip" -p tcp --dport 443 -j REJECT --reject-with tcp-reset
  done
done
```

macOS PF (laptop) can do the same by resolved IP, but the proxy is preferred — it is
hostname-based (no IP churn) and grok-scoped.

## Controlled test to LIFT the grok-offload security hold

1. Run grok in a `--depth=1` secure sandbox (`scripts/secure-offload-clone.sh`) behind
   this proxy (`HTTPS_PROXY=...:8899 --log egress.log`).
2. Confirm **(a)** grok still functions + self-verifies (full current tree present, tests
   run) and **(b)** `egress.log` shows the inference `ALLOW` lines and **zero** successful
   googleapis upload — any `EXFIL-BLOCKED storage.googleapis.com` line is the attempted
   bundle upload being stopped.
3. Only after both pass does the hold lift. Until then, grok offload stays OFF
   (`feedback_grok_offload_security_hold`).
