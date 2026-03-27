# Chapter 90: Real Cloud Deployment: drilldown summary

## Source record
- Source type: chapter landing page plus lesson sequence
- Title: Chapter 90: Real Cloud Deployment
- Venue: Agent Factory
- URL: https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/real-cloud-deployment
- Scope used for this summary: chapter landing page plus lessons from Build Your Cloud Deployment Skill through Capstone: Full Production Deployment

## Chapter thesis
Chapter 90 argues that cloud deployment should be learned as a reusable operational skill, not as a one-off provider walkthrough. The chapter has the reader build a `multi-cloud-deployer` skill first, then apply it to the full path from account setup and managed-cluster provisioning to ingress, DNS, TLS, secrets, production verification, and cross-cloud transfer. Its central claim is that most of the work is portable once a cluster exists: the provider-specific part is provisioning and credential setup, while the deployment, verification, and refinement loop is mostly the same everywhere.

## Chapter-level structure
The landing page frames the chapter as a skill-first progression. The first block explains why local Docker Desktop is not production infrastructure and why managed Kubernetes exists. The next block moves into a concrete production path on DigitalOcean: account setup, `doctl`, DOKS provisioning, cloud load balancers, DNS, and deployment of the Task API stack. The following lessons add production configuration discipline, then contrast the managed path with a cheaper self-managed Hetzner plus K3s lab. The closing lessons formalize production verification, generalize the pattern across cloud providers, and end with a specification-first capstone that deploys the full stack and tears it down cleanly.

The chapter keeps the same reflection loop used elsewhere in the curriculum. The reader is not meant to memorize a DigitalOcean tutorial. Each lesson is supposed to improve the `multi-cloud-deployer` skill so that it can reason about DOKS, Hetzner, AKS, GKE, EKS, and similar providers through one stable model: provision, connect, deploy, verify.

## Lesson-by-lesson drilldown

### Lesson 0: Build Your Cloud Deployment Skill
The opening lesson has the reader create a `multi-cloud-deployer` skill from official documentation through the earlier skill-creation workflow. The skill is meant to cover DigitalOcean DOKS provisioning with `doctl`, Hetzner K3s provisioning through `hetzner-k3s`, multi-cloud portability, and cost comparison. The chapter begins with the skill scaffold on purpose. The reader owns an initial deployment asset before learning the operational details that will later test and refine it.

### Lesson 1: Beyond Docker Desktop
This lesson explains the difference between local success and production reality. Docker Desktop is presented as a development environment, not as infrastructure for a service that must stay available, survive failures, accept public traffic, and operate continuously. The chapter uses the gap between one laptop and a real multi-node cluster to introduce the requirements that production adds: redundancy, external networking, load balancing, DNS, TLS, backups, and cost.

The lesson then compares managed Kubernetes providers with self-managed clusters. Managed offerings remove control-plane work and let the team focus on workloads, while self-managed options trade operational simplicity for lower cost and more control. The key judgment the chapter wants the reader to develop is not brand loyalty to one provider. It is the ability to evaluate the cost, control, and operations tradeoff behind any provider choice.

### Lesson 2: DigitalOcean Account and doctl Setup
This lesson reduces the cloud transition to its actual new pieces: credentials, billing setup, and remote-cluster tooling. The chapter argues that the Kubernetes concepts are not new at this point. What changes is that the cluster lives in a provider account and must be reached through authenticated CLI flows.

The practical work covers creating a DigitalOcean account, attaching billing, claiming promotional credit when available, generating an API token, installing `doctl`, authenticating it, and confirming that the CLI can talk to the account. The broader point is that cloud work starts with identity and toolchain access. Without that layer, no later deployment command is meaningful.

### Lesson 3: Provisioning DOKS Cluster
This lesson turns the account and CLI setup into real infrastructure. The reader provisions a DOKS cluster and saves its kubeconfig locally, which makes the local `kubectl` tool point at worker nodes that now exist in a provider data center instead of on a laptop. The lesson treats this as the first real production step because it crosses from simulation into externally hosted infrastructure.

The chapter also explains the design choices that should not be left implicit. Region matters because proximity affects latency. Node count matters because two nodes leave little margin, while three nodes create a more believable production starting point for availability and rolling updates. Verification then becomes part of the habit: after cluster creation, the reader checks that nodes show `Ready` and that the cluster is actually usable before continuing.

### Lesson 4: Cloud Load Balancer and DNS
This lesson replaces local-cluster access patterns with cloud-facing networking. NodePort was good enough for local learning, but it does not solve public-facing traffic distribution or clean external addressing. In the cloud, a `LoadBalancer` service triggers the provider to provision a real external load balancer and assign a public IP.

The lesson then connects that IP to naming. The reader watches the external IP move from pending to assigned, then maps a domain or subdomain to that address with DNS. For quick testing, the chapter also uses wildcard DNS services such as `nip.io` or `sslip.io`. The governing idea is that production access is a chain: service exposure, external IP, name resolution, and then later TLS.

### Lesson 5: Deploying Task API to DOKS
This lesson assembles the production stack in dependency order. The chapter is explicit that a real deployment is not one manifest applied blindly. Dapr must exist before the application can rely on sidecars. The ingress layer must expose an address before certificate validation can succeed. Certificates must exist before HTTPS is actually live. The order is part of the deployment logic.

The reader installs Dapr, then Traefik, then cert-manager, creates a Let's Encrypt issuer, deploys the Task API with ingress and TLS configuration, and verifies the full stack end to end. The lesson treats deployment as orchestration rather than isolated commands. Its core point is that production success comes from correct sequencing plus verification, not from merely having the right individual components.

### Lesson 6: Production Secrets and Configuration
This lesson moves from a working deployment to a configurable one. A production service needs passwords, tokens, and environment-specific settings that should not be baked directly into images or hardcoded in manifests. The chapter splits these into Secrets for sensitive values and ConfigMaps for ordinary configuration.

The lesson also explains layering and precedence. Defaults can live in the image or direct environment variables, non-sensitive runtime settings come from ConfigMaps, and sensitive values come from Secrets. The reader then verifies that those values actually reach the container and that image-pull credentials are handled correctly when private registries are involved. The point is not merely to store configuration elsewhere. It is to treat configuration injection as something that must be designed, ordered, and checked.

### Lesson 7: Personal Cloud Lab: Hetzner plus K3s
This lesson introduces a budget lab path for experimentation. Managed Kubernetes is simpler, but even an inexpensive production cluster may cost more than a learner or solo operator wants to spend just to practice. Hetzner plus K3s is presented as the cheaper alternative: more operational responsibility, but better economics for a personal cluster.

The chapter uses K3s as the lightweight distribution that makes this feasible on small virtual machines. The reader creates a Hetzner account, handles SSH prerequisites, installs the `hetzner-k3s` tool, provisions a cluster, downloads kubeconfig, and confirms that nodes are healthy. The broader lesson is comparative judgment: managed clusters buy convenience and SLA-backed control-plane operations, while self-managed K3s buys a cheaper sandbox and more direct ownership of the stack.

### Lesson 8: Production Checklist and Verification
This lesson argues that a deployed service is not automatically a production-ready one. The chapter introduces a production-readiness checklist and treats verification as a distinct operational phase. Health endpoints, probes, certificate validity, DNS resolution, replica count, resource limits, disruption budgets, autoscaling, and image-pull behavior must all be checked explicitly.

The point is procedural discipline. Instead of saying a deployment is ready because it seems to work, the reader runs a repeatable sequence of checks and interprets failures through concrete symptoms. The chapter even turns that habit into a scriptable checklist, which reinforces the larger theme that cloud operations should become reusable process, not intuition.

### Lesson 9: Same Patterns, Different Clouds
This lesson extracts the provider-agnostic model hidden inside the earlier DigitalOcean and Hetzner exercises. The chapter argues that most of Kubernetes deployment work is portable across providers. What changes is cluster creation and kubeconfig acquisition. Once the reader is connected to a cluster, the same `kubectl`, Helm, Dapr, ingress, and verification patterns apply.

The lesson formalizes that claim into the three-step model the chapter wants the reader to internalize: provision, connect, deploy. It then shows how that model maps across DigitalOcean, Azure, Google Cloud, AWS, and Civo. The lesson exists to prevent the reader from mistaking one provider tutorial for the real skill. The real skill is understanding which parts vary and which parts stay stable.

### Lesson 10: Capstone: Full Production Deployment
The capstone consolidates the whole chapter into a specification-first deployment exercise. Before touching infrastructure, the reader writes a deployment spec that names the provider, region, cluster, domain, resource requirements, stack components, success criteria, and explicit non-goals. The chapter uses that step to reject improvisational cloud work and force budget, performance, and operational constraints into the open.

From there, the capstone executes a complete deployment path: choose a provider path, provision the cluster, install Dapr, Traefik, and cert-manager, deploy the Task API with probes and resource settings, configure ingress and TLS, and then enter a convergence loop that diagnoses and fixes real deployment failures such as image-pull errors, DNS lag, certificate stalls, or pending load balancers. It ends with production verification, clean teardown, and a rubric for judging whether the resulting `multi-cloud-deployer` skill is actually reusable and sellable.

## What the chapter says the reader owns at the end
By the end of the chapter, the reader is expected to own a reusable `multi-cloud-deployer` skill, understand why local Docker tooling is not production infrastructure, know how to authenticate cloud tooling and provision managed Kubernetes clusters, know how to expose services through cloud load balancers and DNS, know how to deploy a Dapr-enabled Task API stack with ingress and TLS, know how to separate secrets from ordinary configuration, know when a budget K3s lab is a better fit than a managed cluster, know how to run a production-readiness checklist, and know how to transfer the same deployment logic across providers through the universal pattern of provision, connect, deploy, verify.

## Closing compression
The chapter's core claim is that real cloud deployment is a portable operational skill built from the same disciplined loop each time: define the target, provision the cluster, connect tooling, deploy the stack in the right order, verify production behavior, and refine the deployment asset until it generalizes. DigitalOcean and Hetzner are teaching vehicles, but the chapter's actual subject is the reusable cloud-deployment judgment that survives changes in provider.
