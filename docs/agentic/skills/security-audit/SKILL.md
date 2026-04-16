---
name: security-audit
description: Run a structured security audit over the monorepo and record actionable findings with credible exploit paths.
mode: execution
context_budget: 220
makefile_target: null
mcp_tools:
  - review_findings
  - review_runs
  - record_event
  - get_handoff_state
  - generate_dashboard_md
tdd_gate: false
disable-model-invocation: false
---

# Security Audit

## Overview

Use this skill for systematic security auditing of the monorepo's packages, MCP servers, configuration, and dependencies.

## Trigger

Use this skill when the request matches any of:

- "security audit", "security review", "vulnerability scan"
- "check for secrets", "check for leaks"
- "dependency audit", "supply chain check"
- "OWASP", "threat model"

## Goal

Produce a structured, MCP-recorded security assessment with actionable findings. Think like an attacker (find the actually unlocked doors), report like a defender (with exploit scenarios and fix recommendations).

## Canonical Policy

- Use [../../instructions.md](../../instructions.md) for startup, handoff, and evidence-logging policy.
- Use [../../rules/development-workflow.md](../../rules/development-workflow.md) for security pass conventions (slice checklist step 8).
- Use [../../contracts/](../../contracts/) for MCP trust boundary definitions.
- Use this skill for security audit phasing and methodology only; broader process policy lives in the linked canonical docs.

## Scope

This audit covers the monorepo content within the plugin boundary rule:

- `packages/agent-handoff-mcp/` — MCP server handling task state, review findings, decisions
- `packages/agent-orchestrator-mcp/` — MCP server handling orchestration, lane management, worker daemons
- `packages/codex-subagent-bridge/` — Bridge for external agent integration
- `apps/prototype-description-service/` — Python backend service
- `apps/prototype-wp-alt-context/` — WordPress plugin (PHP + React/TS)
- `scripts/` — Utility and MCP launcher scripts
- `mk/` — Makefile includes
- Configuration files: `.mcp.json`, `.vscode/mcp.json`, `pyproject.toml`, `composer.json`, `package.json`
- CI/CD: `.github/workflows/`

Out of scope: WordPress core, LocalWP config, `~/Local Sites/`, system config, `docs/literature/`.

## Confidence Mode

**Standard mode** (default): 8/10 confidence gate. Only report findings with a clear exploit path or vulnerability pattern. Zero noise.

**Comprehensive mode** (when user requests "thorough" or "comprehensive"): 2/10 confidence gate. Surface anything that _might_ be real, marked `TENTATIVE`.

## Core Process

1. Build the trust-boundary model before hunting for individual issues.
2. Run the audit phases below from highest-leverage exposure paths to narrower checks.
3. Filter aggressively for real exploitability before recording findings.
4. Record findings, verdict, and closure evidence durably before reporting out.

## Phase 0 — Architecture Mental Model

Before auditing, build understanding of the attack surface.

1. Read the tech stack map: `docs/agentic/maps/tech-stack.md`.
2. Read MCP contracts: `docs/agentic/contracts/agent-handoff-mcp.md` and `docs/agentic/contracts/agent-orchestrator-mcp.md`.
3. Identify trust boundaries:
   - Agent ↔ MCP server (tool calls over stdio/HTTP)
   - MCP server ↔ SQLite database (local filesystem)
   - Orchestrator ↔ worker daemons (subprocess + filesystem)
   - Plugin ↔ Python backend (REST API)
   - Plugin ↔ WordPress core (hooks, options, meta)

Record a brief architecture summary as context — this is understanding, not findings.

## Phase 1 — Secrets Archaeology

Scan for secrets that should not be in the repository.

```bash
# Check tracked files for known secret prefixes
git grep -n -E '(AKIA[A-Z0-9]{16}|sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|xox[bpas]-[a-zA-Z0-9-]+|glpat-[a-zA-Z0-9-]+)' -- ':!docs/literature/' ':!*.md'

# Check for tracked .env files
git ls-files '*.env' '.env*' '*/.env*'

# Check git history for secrets (recent commits only)
git log --oneline -50 --diff-filter=A -- '*.env' '*.key' '*.pem' '*credentials*' '*secret*'
```

**Severity**:
- CRITICAL: active secrets or API keys in tracked files
- HIGH: `.env` files tracked, inline credentials in CI configs
- MEDIUM: suspicious placeholder values, hardcoded test tokens

## Phase 2 — Dependency Supply Chain

Audit dependencies for known vulnerabilities and supply chain risks.

For Python packages:

```bash
# Check for lockfile presence
ls packages/*/requirements*.txt packages/*/poetry.lock packages/*/uv.lock 2>/dev/null

# Review direct dependencies
cat packages/agent-handoff-mcp/pyproject.toml | grep -A 30 '\[project\]'
cat packages/agent-orchestrator-mcp/pyproject.toml | grep -A 30 '\[project\]'
```

For Node.js:

```bash
ls apps/prototype-wp-alt-context/js/package-lock.json 2>/dev/null
```

For PHP:

```bash
ls apps/prototype-wp-alt-context/composer.lock 2>/dev/null
```

Check for:
- Missing lockfiles (HIGH)
- Known CVEs in pinned versions (severity matches CVE severity)
- Abandoned or unmaintained dependencies (MEDIUM)
- Dependencies with install scripts in production (HIGH)

## Phase 3 — MCP Trust Boundary Audit

This is the most critical phase for this monorepo. MCP servers handle cross-agent state.

1. **Input validation**: verify that MCP tool handlers validate all parameters before database operations. Check for:
   - SQL injection via unsanitized string interpolation in queries
   - Path traversal in `file_path` parameters
   - Unbounded input sizes (description, rationale fields)

2. **Authorization model**: MCP servers in this repo are local-only (stdio/localhost). Verify:
   - No network-accessible endpoints without authentication
   - HTTP mode (if enabled) binds to localhost only
   - No ambient authority — tools should not access filesystem outside workspace root

3. **Data integrity**: verify SQLite operations are safe:
   - Parameterized queries (no f-string SQL)
   - Transaction boundaries around multi-step mutations
   - Schema migrations are idempotent

4. **Tool surface**: verify MCP tools do not:
   - Execute arbitrary shell commands from tool parameters
   - Write files outside the workspace root
   - Expose internal state (database paths, config) in error messages

Read and audit these files:

```
packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py
packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py
packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_db_utils.py
packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py
packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py
```

## Phase 4 — CI/CD Pipeline Security

If `.github/workflows/` exists, audit for:

- Unpinned GitHub Actions (use SHA, not tag)
- `pull_request_target` with PR checkout (CRITICAL)
- Script injection via `${{ github.event.*.body }}` in `run:` blocks
- Secrets exposed as environment variables to untrusted steps
- Missing `CODEOWNERS` file

## Phase 5 — OWASP Top 10 (Scoped)

Apply relevant OWASP categories to the monorepo's tech stack:

| Category | Applicable surfaces |
|---|---|
| A01 Broken Access Control | MCP tool handlers, REST API endpoints, WordPress capability checks |
| A02 Cryptographic Failures | Token storage, data at rest in SQLite, credentials in config |
| A03 Injection | SQL queries in MCP core, shell commands in Makefile targets, PHP database queries |
| A04 Insecure Design | Rate limits on MCP tools, server-side validation, input length bounds |
| A05 Security Misconfiguration | CORS settings, debug mode flags, default credentials |
| A06 Vulnerable Components | See Phase 2 |
| A07 Authentication | WordPress nonce validation, REST API auth, MCP session handling |
| A09 Logging & Monitoring | Sensitive data in logs, error messages exposing internals |
| A10 SSRF | Any URL-fetching from user input (recognition service, external API calls) |

## Phase 6 — False Positive Filtering

Before recording, verify each finding:

- **Prove it**: trace the exploit path from input to impact. If the path is broken by existing controls, downgrade or discard.
- **Check context**: a "vulnerability" in a local-only development tool has different severity than in a production service.
- **Variant analysis**: if one instance is confirmed, search for the same pattern across the codebase.

Discard findings that are:
- Theoretical DoS on local-only tools
- Input validation on non-security-critical fields
- Style or convention issues (those belong in a branch review)

## Recording Findings

**Finding ID prefix**: `SEC-<n>` (e.g., `SEC-01`, `SEC-02`).

For each confirmed finding, record:

```
record_review_finding(
  session="<session-id>",
  finding_id="SEC-<n>",
  severity="high|medium|low",
  file_path="<monorepo-relative-path>",
  description="<vulnerability-description>. Exploit path: <step-by-step>. Impact: <what-an-attacker-gains>.",
  task_ref="__repo__",
  review_mode="release_audit",
  details={ "line_start": N, "line_end": N, "fix": "<recommended-remediation>" }
)
```

Use `task_ref="__repo__"` for repo-scoped security findings not owned by any single task.

When recording 3 or more findings, use `batch_record_review_findings`.

In comprehensive mode, mark uncertain findings with `TENTATIVE` prefix in description.

## Verdict and Closure

1. Summarize findings: `list_review_findings(task_ref="__repo__", review_mode="release_audit")`.

2. Record the audit decision:

```
record_decision(
  session="<session-id>",
  decision="security_audit_<date>",
  rationale="Security audit complete. <severity-counts>. <critical-summary-if-any>."
)
```

3. Record the review run:

```
record_review_run(
  review_run_id="security-audit-<date>",
  session="<session-id>",
  subject_path=".",
  subject_kind="other",
  review_mode="release_audit",
  verdict="<pass|pass_with_findings|fail>",
  verdict_decision="security_audit_<date>"
)
```

4. Regenerate task context if an active task exists.

## Response Format

Present findings grouped by phase, then by severity within each phase:

1. Attack surface summary (brief)
2. Findings table: `| ID | Severity | Phase | File | Description |`
3. For each HIGH/CRITICAL finding: exploit scenario, impact, and recommended fix
4. Verdict with severity counts

End with `Handoff updated: yes`.

## Common Rationalizations

- "It is internal tooling, so the attack surface is tiny." Local tooling still handles credentials, shell execution, filesystems, and persistence.
- "This looks suspicious, so it must be a finding." Security reviews become noisy fast; report only what has a credible exploit path or clearly marked tentative risk.
- "Dependency audit output is enough." Package advisories are one input, not the full audit.

## Red Flags

- The audit is reporting findings without a clear affected trust boundary.
- Secrets scanning or dependency review was skipped because the code "looked safe."
- A suspected issue depends on behavior you have not verified in code or config.

## Recovery

- If MCP is unavailable, record findings in a structured comment and transfer to MCP when access returns.
- If a phase produces no findings, note it as clean and move on — do not fabricate findings to fill the report.
- If access to a file is denied, note the gap and continue with available files.

## Convergence Criteria

- Every finding is recorded in MCP before being mentioned in chat.
- Every finding includes an exploit path (not just a pattern match).
- A `record_review_run` entry exists for this audit.
- A `record_decision` entry exists with the audit verdict.
- Response includes `Handoff updated: yes`.

## See Also

- [../review/SKILL.md](../review/SKILL.md)
- [../../contracts/](../../contracts/)
- [../../rules/development-workflow.md](../../rules/development-workflow.md)
