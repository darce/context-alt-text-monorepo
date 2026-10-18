# Chapter 88: Production Security & Compliance — Drilldown Summary

## Source record
- **Source type:** Panaversity curriculum chapter with lesson pages, capstone, assessment, and asset page
- **Title:** Chapter 88: Production Security & Compliance
- **Part:** Part 7 — Deploying Agent Factories in the Cloud
- **Site:** Agent Factory / Panaversity
- **URL:** https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/production-security
- **Accessed:** 2026-03-26

## Main idea
This chapter teaches production security for Kubernetes-deployed agent services as a layered operating discipline: build a reusable cloud-security skill first, then apply identity controls, network isolation, workload hardening, secret handling, supply-chain checks, Dapr-specific controls, and compliance evidence to a single hardened Task API deployment.

## Chapter overview
The chapter begins with the usual skill-first setup, then uses the 4C model to organize the rest of the work. The middle lessons cover the main control families: RBAC for identity and authorization, NetworkPolicies for traffic boundaries, secrets patterns for credential handling, Pod Security Standards for workload restrictions, and image scanning plus signing for supply-chain hygiene. The final lessons extend the security model into Dapr and audit language, then consolidate everything into a capstone deployment, a chapter assessment, and a reusable verification checklist.

## Lesson-by-lesson drilldown

### L00 — Build Your Cloud Security Skill
The opening lesson treats security knowledge as something to package and test, not just read. The learner writes a `LEARNING-SPEC.md`, fetches official Kubernetes security documentation, generates a `cloud-security` skill from those sources, and validates it by producing least-privilege RBAC YAML and checking it with `kubectl apply --dry-run=client`. The lesson establishes the chapter’s method: use the skill as a living operational artifact that can be exercised, audited, and improved as each later control is learned.

### L01 — Cloud Native Security Model
This lesson introduces the 4C model — Cloud, Cluster, Container, Code — as the organizing map for production security. Its key claim is that controls should be understood as layered defenses with dependency ordering: outer layers fail first, so teams should secure infrastructure and cluster boundaries before focusing only on application code. The Task API is used as the running example, and the lesson asks the learner to classify controls by layer so the rest of the chapter can be placed inside one threat model instead of treated as unrelated checklists.

### L02 — RBAC Deep Dive
The RBAC lesson narrows security down to identity and authorization inside Kubernetes. It explains the four RBAC building blocks — ServiceAccounts, Roles, ClusterRoles, and bindings — and pushes a least-privilege workflow: create a dedicated ServiceAccount, disable token automounting unless API access is required, define the narrowest possible Role, bind it explicitly, and then test both allowed and denied actions with `kubectl auth can-i`. The lesson also makes the Role versus ClusterRole choice explicit so namespace-scoped access is the default rather than a convenience that silently turns into cluster-wide privilege.

### L03 — NetworkPolicies for Zero-Trust Traffic Control
This lesson frames Kubernetes networking as open by default and therefore unsafe by default. The operational pattern is simple and strict: start with a default-deny policy, then add only the ingress and egress rules the workload truly needs. DNS is treated as the first practical exception, and the lesson emphasizes that cross-namespace traffic often requires `namespaceSelector` rather than a pod-only selector. The broader point is that NetworkPolicy is how a cluster stops being a flat network and becomes an explicit traffic matrix with limited lateral movement.

### L04 — Secrets Management
The secrets lesson distinguishes storage formats from actual protection. It states plainly that Kubernetes Secrets are base64-encoded, not encrypted, and therefore only acceptable for simpler cases unless stronger controls are added. The lesson then builds a hierarchy of use cases: plain Kubernetes Secrets for local development, Sealed Secrets for single-cluster GitOps workflows, and External Secrets Operator for multi-cluster production, rotation, auditability, and compliance-heavy environments. It also prefers mounting secrets as files over exposing them as environment variables, since logs and process listings can leak the latter too easily.

### L05 — Pod Security Standards: Hardening Container Workloads
This lesson moves from cluster permissions to what the workload itself can do at runtime. It uses Pod Security Standards, especially the Restricted profile, to enforce a hardened baseline through namespace labels and explicit `securityContext` fields. The required pattern includes non-root execution, seccomp, dropping capabilities, disabling privilege escalation, and handling writable directories deliberately when `readOnlyRootFilesystem` is enabled. The lesson also distinguishes development and production by recommending stricter enforcement in production and warning-only or baseline variants in development where needed.

### L06 — Image Scanning and Supply Chain Security
This lesson treats image security as both vulnerability management and provenance control. Trivy is the primary scanning tool, and the recommended pattern is to run it in CI with failing exit codes for severe findings, generate SBOM output for audit purposes, and use the result as a deployment gate instead of an ignored report. The chapter then extends supply-chain discipline with Cosign signing, digest pinning, and admission-control enforcement so teams verify not just whether an image is vulnerable, but also whether it is the exact artifact the trusted pipeline produced.

### L07 — Dapr Security: mTLS, API Tokens, and Component Scopes
The Dapr lesson starts from an important distinction: automatic mTLS is useful, but encryption alone does not settle the full security question. The learner verifies that sidecars actually hold certificates, then adds Dapr-specific restrictions such as component scopes so one compromised app cannot freely reach all state stores or pub/sub components through Dapr APIs. API tokens are presented as conditional rather than universal; the lesson argues they add little value in a simple single-container pod model with localhost isolation, but become relevant when pods are more complex or Dapr APIs are exposed more broadly. The central control here is least privilege at the Dapr layer, not just at the Kubernetes layer.

### L08 — Compliance Fundamentals: SOC2 and HIPAA Awareness
This lesson translates the technical controls into audit language. For SOC2, it maps RBAC, NetworkPolicy, ServiceAccount lifecycle, PSS, and audit logging to the security-related trust service criteria. For HIPAA, it ties Kubernetes controls to access control, audit controls, encryption in transit, encryption at rest, and integrity, while also correcting a common mistake: base64-encoded Kubernetes Secrets do not satisfy encryption requirements. The lesson keeps the scope narrow and useful by focusing on what these Kubernetes controls can prove to auditors, and by separating technical evidence from the broader compliance program the organization still has to maintain.

### L09 — Capstone: Secure Task API
The capstone combines the chapter into one audited deployment. The learner writes a security specification first, then composes namespace labels, RBAC, NetworkPolicies, secret handling, Dapr component scopes, workload security settings, and image-security checks into one Task API deployment. The capstone then runs a 10-point audit covering identity, permissions, network isolation, DNS, secrets mounting, PSS compliance, vulnerability status, Dapr mTLS, component scopes, and audit logging. It also includes penetration-test-style validation and a short compliance mapping so the final output is not just “secure YAML” but evidence-backed operational posture.

## Assessment and asset pages

### Chapter 88 Assessment
The assessment page tests the chapter at an intermediate application level. It covers the 4C model, least-privilege RBAC, NetworkPolicy troubleshooting, PSS-compliant security contexts, Trivy scan interpretation, execution of the 10-point audit, and compliance mapping. The question mix matters: it expects both implementation skill and diagnosis skill, so the learner must not only write correct configurations but also explain why a configuration is wrong or why an audit result changes the decision.

### Production Security Checklist for Kubernetes
The asset page distills the chapter into a reusable 10-point audit checklist and a shell script that checks the core signals quickly. That page turns the chapter into an operational routine: verify dedicated ServiceAccounts, review RBAC permissions, confirm default-deny policy presence, test DNS, check that secrets are mounted correctly, validate PSS compatibility, scan the image, confirm Dapr security state, inspect component scopes, and verify audit logging. Its real function is drift control. The chapter does not stop at one hardened deployment; it leaves behind a repeatable inspection pattern for future workloads.

## What the chapter concludes
The chapter concludes that production security for cloud-deployed agents is a layered control system backed by verification. Security is not defined by one tool, one YAML object, or one clean scan. It is defined by how identity, network boundaries, runtime restrictions, secret flows, supply-chain checks, service-mesh controls, and compliance evidence fit together into a deployment that can be tested and defended over time.

## Structural notes
- The accessible chapter navigation exposed the landing page plus lessons L00-L09.
- The capstone links to an assessment page under `assets/chapter-assessment`.
- The assets section also includes a reusable page titled **Production Security Checklist for Kubernetes**.
