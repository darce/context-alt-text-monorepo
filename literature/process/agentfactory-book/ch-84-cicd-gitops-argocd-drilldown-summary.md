# Chapter 84: CI/CD Pipelines & GitOps with ArgoCD — drilldown summary

## Source record
- Source type: chapter landing page plus lesson sequence
- Title: Chapter 84: CI/CD Pipelines & GitOps with ArgoCD
- Venue: Agent Factory
- URL: https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/cicd-gitops-argocd
- Scope used for this summary: chapter landing page plus Lesson 0 through Lesson 17

## Chapter thesis
Chapter 84 argues that deployment reliability comes from splitting the problem into two linked but distinct systems. CI is responsible for artifact discipline: triggered automation, repeatable builds, tests, registry publication, and quality gates. GitOps is responsible for control-plane discipline: Git as the declared source of truth, ArgoCD as the reconciler, automated sync with guardrails, ordered rollout behavior, team boundaries, secrets patterns, health signals, staged delivery, and cluster-wide scale. The chapter has the reader build a `gitops-deployment` skill first, then refine that skill lesson by lesson until it becomes a reusable reasoning framework for production pipelines rather than a pile of YAML snippets.

## Chapter-level structure
The landing page presents the chapter as an ordered progression. The first block covers CI/CD fundamentals: trigger flow, GitHub Actions, automated image builds, and test-driven quality gates. The second block shifts from CI to GitOps proper: Git as truth, ArgoCD architecture, Application CRDs, and sync strategy design. The third block expands into production operating patterns, including sync waves and hooks, ApplicationSets, Projects and RBAC, health and notifications, progressive delivery, secrets handling, and multi-cluster deployments. The fourth block adds AI-assisted authoring and review of GitOps artifacts. The chapter ends with a specification-first capstone and a final lesson that converts the chapter’s tacit decisions into a reusable deployment skill.

The chapter is internally consistent in numbering. The landing page, lesson chain, and chapter title all identify the material as Chapter 84.

## Lesson-by-lesson drilldown

### Lesson 0: Build Your GitOps Skill
The chapter opens by having the reader create a GitOps skill from official ArgoCD documentation before learning the chapter content in detail. The skill is built through the existing skill-creation workflow, stored under `.claude/skills/gitops-deployment/`, and explicitly grounded in official documentation rather than model guesswork. This reverses the normal order on purpose: the reader owns a first-pass skill before they know enough to audit it.

### Lesson 1: CI/CD Concepts: The Automated Pipeline
This lesson establishes the basic deployment assembly line: trigger, build, test, push, and deploy. Its main claim is that manual deployment scales poorly because it depends on human correctness at the exact point where mistakes are most expensive. CI/CD matters not because automation is fashionable, but because it moves validation, artifact creation, and release traceability into a repeatable system. The lesson treats the pipeline itself as a quality guarantee.

### Lesson 2: GitHub Actions Fundamentals
Here the chapter makes CI concrete. GitHub Actions is presented as the orchestrator that reacts to repository events and executes workflows described in version-controlled YAML files. The user learns the hierarchy of workflow, jobs, and steps so the earlier pipeline model becomes executable rather than abstract. The emphasis is on understanding the event-to-job mental model before memorizing syntax.

### Lesson 3: Building Docker Images in CI
This lesson connects CI to actual deployment artifacts. A pipeline should not stop at testing source code; it should automatically build container images, tag them coherently, and push them to a registry. The chapter highlights a genuinely practical constraint: architecture mismatch between developer machines and target infrastructure. Multi-platform builds, registry publishing, and caching are treated as operational necessities rather than optional polish.

### Lesson 4: Testing and Quality Gates
The pipeline becomes meaningful only when it is allowed to fail. This lesson teaches the test stage as an uncompromising gate: run automated tests, enforce linting and coverage rules, and stop the pipeline on any failure. The chapter’s stance is absolute. A broken build must not move downstream simply because someone is in a hurry. Quality gates are what make automation safer rather than merely faster.

### Lesson 5: GitOps Principles: Git as Truth
The chapter then pivots from CI to deployment control. If CI prepares deployable artifacts but a human still runs `kubectl apply`, deployment remains partly manual. GitOps replaces imperative deployment commands with declarative desired state stored in Git. A controller watches that source of truth and reconciles the cluster to match it. The lesson frames this as the answer to auditability, rollback clarity, collaboration, and drift correction.

### Lesson 6: ArgoCD Architecture & Installation
This lesson introduces ArgoCD as the controller that makes GitOps real. The reader learns the component view, installs ArgoCD into a local cluster, and validates both UI and CLI access. More importantly, the lesson explains the before-and-after difference in workflow. Without ArgoCD, deployment success and rollback remain manual chores. With ArgoCD, Git changes drive reconciliation, cluster drift is corrected, and rollback reduces to reverting a commit.

### Lesson 7: Your First ArgoCD Application
Once ArgoCD is installed, the reader creates the Application CRD that formalizes the contract between Git and the cluster. The lesson shows that an ArgoCD Application is not a loose convenience object; it is the unit that specifies source repository, destination cluster or namespace, and sync behavior. The user creates Applications through multiple paths, watches ArgoCD detect manifests, syncs them, and monitors sync and health state transitions.

### Lesson 8: Sync Strategies and Policies
Having created an Application, the reader now decides how automated deployment should be. The lesson distinguishes manual sync, auto-sync, auto-prune, self-heal, and replacement behavior for immutable resources. Its core claim is that true GitOps does not stop at watching Git. It requires well-chosen reconciliation policies that balance automation, safety, cleanup, and drift correction.

### Lesson 9: Sync Waves and Resource Hooks
This lesson addresses rollout sequencing. Some resources cannot be created or updated all at once without breaking the system. Database migrations may need to run before application startup, and cleanup or rollback logic may need to fire at specific stages. Sync waves impose deployment order. Resource hooks inject behavior at pre-sync, sync, post-sync, and failure points. The lesson treats ordering as a first-class production concern rather than an edge case.

### Lesson 10: ApplicationSets: Scaling Deployments
A single Application works for one environment, but the chapter then moves to the common enterprise case: multiple environments, multiple regions, or multiple clusters. ApplicationSets are presented as the DRY mechanism that generates many Applications from one template using parameterized generators. The lesson’s point is not just YAML reduction. It is scalable consistency across environments.

### Lesson 11: ArgoCD Projects and RBAC
At this point the material becomes organizational rather than purely technical. Projects constrain what repositories, clusters, and namespaces a team can target. RBAC then determines who can read, sync, approve, or administer those deployments. The chapter frames these controls as mandatory once more than one team or workload shares the platform. Without them, GitOps centralization becomes an organizational risk.

### Lesson 12: Health Status and Notifications
ArgoCD is not valuable if it can sync silently into failure. This lesson explains ArgoCD’s health states, how it evaluates whether resources are healthy or degraded, and how notifications can route those changes into Slack, webhooks, or similar channels. The important move is conceptual: deployment is not complete when manifests are applied. It is complete when health is observed and abnormal conditions are surfaced to operators.

### Lesson 13: Progressive Delivery Overview
The chapter then addresses the weakness of all-at-once rollouts. Progressive delivery is introduced as the safer operating model for production changes, with canary and blue-green patterns used to limit blast radius and enable observation before full traffic shift. Argo Rollouts is presented as the Kubernetes-native mechanism for automating those strategies. The lesson reframes deployment success from “pods updated” to “risk was introduced gradually and monitored.”

### Lesson 14: Secrets Management for GitOps
This lesson names the central GitOps tension directly: Git should hold declarative truth, but plaintext secrets must never be committed there. The chapter therefore surveys secure patterns such as Sealed Secrets, External Secrets Operator, and Vault-style integrations, while also stressing rotation and access control. The governing idea is that secrets remain part of deployment architecture without becoming normal version-controlled data.

### Lesson 15: Multi-Cluster Deployments
From there the chapter broadens the control plane. One ArgoCD instance can manage many clusters in a hub-and-spoke pattern, using a single Git repository as truth while applying environment-specific or cluster-specific variation. The lesson presents this as the route to redundancy, staged promotion, and fleet-wide management. The GitOps idea scales outward from one namespace to whole infrastructure estates.

### Lesson 16: AI-Assisted GitOps Workflows
Only after the chapter has built manual understanding does it introduce AI assistance. The point is not that AI replaces GitOps reasoning; it accelerates manifest generation, review, and debugging in a domain where small structural mistakes can have large consequences. The lesson explicitly emphasizes evaluation and refinement of AI-generated YAML. Human review remains the safety boundary.

### Lesson 17: Capstone: End-to-End Agent Pipeline
The capstone integrates the chapter into one commit-to-cluster path. The reader starts from a specification, not from ad hoc YAML, then implements CI with GitHub Actions and CD with ArgoCD. The demonstrated flow is complete: code push, tests, image build, registry push, Git-based deployment state, automated cluster sync, validation, and rollback. This is where the chapter proves that its pieces form one operating system for releases.

### Lesson 18: Building the GitOps Deployment Skill
The final lesson converts the chapter from a tutorial into portable organizational intelligence. The reader is asked to encode not just steps but decision frameworks: when to use auto-sync, when to isolate access with Projects, when to apply ApplicationSets, when to choose a secrets pattern, when progressive delivery is warranted, and how to reason about cluster topology. A real skill, in the chapter’s framing, preserves judgment rather than preserving instructions.

## What the chapter says the reader owns at the end
By the end of the chapter, the reader is expected to own a reusable `gitops-deployment` skill, understand the CI pipeline stages and how GitHub Actions executes them, know how to build portable container images in CI, enforce test and quality gates, treat Git as deployment truth, install and operate ArgoCD, create and manage Application CRDs, configure sync behavior and deployment ordering, scale deployments with ApplicationSets, enforce organizational boundaries with Projects and RBAC, monitor health and notifications, apply progressive delivery patterns, handle secrets without violating GitOps principles, manage multi-cluster topologies, and use AI assistance without surrendering review responsibility.

## Closing compression
The chapter’s central claim is that reliable deployment is not one tool. It is the composition of two disciplines. CI produces trustworthy artifacts through automated build and test pipelines. GitOps turns those artifacts into auditable, declarative, continuously reconciled cluster state. ArgoCD, in this framing, is not merely a UI for Kubernetes. It is the controller that turns Git into an operational control plane. The chapter’s closing move, building the reusable skill, makes clear that the real deliverable is not a working demo pipeline. It is deployment judgment that can be reapplied across future systems.
