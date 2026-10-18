# Chapter 86 — Traffic Engineering: drilldown

Source chapter: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering>

## What this chapter is doing

Chapter 86 moves the course from "the service runs inside Kubernetes" to "the service is reachable, protected, encrypted, and scalable at the edge." The core problem is external traffic: how requests enter the cluster, how they are routed, how abuse is controlled, how certificates are managed, how rollouts stay safe, and how capacity follows demand.

The chapter's practical output is a reusable `traffic-engineer` skill. That skill is meant to generate Gateway API resources, Envoy Gateway policy, TLS setup, traffic-splitting rules, and autoscaling patterns for future deployments. The chapter follows the usual skill-first pattern: build the skill, learn the concepts, compose them in a capstone, then finalize the skill for reuse.

## Chapter thesis in one paragraph

A production traffic layer for AI services needs more than exposure on port 80. It needs a standard routing model, a controller that turns that model into running proxies, rules for matching and splitting traffic, protection against overload and cost blowups, automatic certificate renewal, autoscaling, and failure-handling patterns. For LLM-backed systems, ordinary request counting is not enough, so the chapter extends the model into token-aware traffic control with Envoy AI Gateway.

## Authored page sequence

1. Overview
2. Build Your Traffic Engineering Skill
3. Ingress Fundamentals
4. Traefik Ingress Controller
5. Gateway API - The New Standard
6. Envoy Gateway Setup
7. Traffic Routing with HTTPRoute
8. Rate Limiting & Circuit Breaking
9. TLS Termination with CertManager
10. Traffic Splitting Patterns
11. Autoscaling with HPA, VPA & KEDA
12. Resilience Patterns
13. Envoy AI Gateway for LLM Traffic
14. Capstone: Production Traffic for Task API

## Drilldown by page

### Overview

The overview frames traffic engineering as the edge layer for Kubernetes-based agents. Its goal set is explicit: learn Gateway API, deploy Envoy Gateway, route with `HTTPRoute`, apply rate limiting and resilience controls, terminate TLS with cert-manager, perform canary and blue-green delivery, autoscale with KEDA, and handle LLM traffic through AI-gateway patterns.

Two things matter here. First, the chapter treats Gateway API as the preferred long-term standard rather than another controller-specific trick. Second, it treats traffic engineering as a reusable professional skill, not a one-off configuration exercise.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering>

### L00 — Build Your Traffic Engineering Skill

The opening lesson is operational, not conceptual. It tells the reader to create a `LEARNING-SPEC.md`, fetch official Envoy Gateway documentation, use a skill-creator workflow, and validate the generated YAML with `kubectl apply --dry-run=client`.

That matters because the chapter is training the student to work from authoritative docs and measurable success criteria. The lesson is not just "make a skill folder." It establishes a workflow: define scope, gather official references, generate assets, then test them against Kubernetes before trusting them.

The skill is expected to produce at least:
- `Gateway` and `HTTPRoute` YAML
- rate-limiting patterns
- references back to official Envoy Gateway docs
- templates that can be reused across deployments

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/build-your-traffic-engineering-skill>

### L01 — Ingress Fundamentals

This lesson starts with the simplest failure case: a `ClusterIP` service is reachable inside the cluster but meaningless from a laptop browser. From there it walks the reader through the progression of Kubernetes exposure models:
- `ClusterIP` for internal-only access
- `NodePort` for exposing a port on every node
- `LoadBalancer` for cloud-managed public entry
- `Ingress` for centralizing routing rules behind a shared entry point

The useful part of the lesson is not the definitions. It is the comparison. `NodePort` is awkward and fragile, `LoadBalancer` solves exposure but not consolidation, and `Ingress` reduces cost and lets one entry point route to many services. The lesson also shows why classic Ingress aged badly: useful features such as rate limiting, timeouts, TLS behavior, and regex matching often spill into controller-specific annotations, which makes the resource hard to read and hard to port.

That annotation problem is the hinge into the rest of the chapter. It sets up Gateway API as a cleaner successor.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/ingress-fundamentals>

### L02 — Traefik Ingress Controller

This is the chapter's fast on-ramp. Instead of starting with the full Gateway API object model, it uses Traefik to get traffic flowing quickly. Traefik is presented as easier to grasp because its CRDs such as `IngressRoute` and `Middleware` expose routing and policy in structured YAML instead of burying behavior in annotations.

The lesson has two jobs:
1. install a working ingress controller with Helm
2. make the Task API externally reachable with basic protection

The deeper teaching point is transitional. Traefik helps the learner see routing fundamentals clearly, but its CRDs are still Traefik-specific. The chapter is using Traefik as a teaching bridge, not as the final standard. Once the reader understands match rules and middleware, Gateway API's model becomes easier to absorb.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/traefik-ingress-controller>

### L03 — Gateway API: the new standard

This lesson shifts from "how to get it working quickly" to "what resource model should you bet on." Gateway API is presented as the official Kubernetes replacement for Ingress, with GA status reached in October 2023 and implementation support across Envoy Gateway, Istio, Traefik, and Kong.

The chapter emphasizes the three-tier structure:
- `GatewayClass` chooses the controller implementation
- `Gateway` defines the entry point and listeners
- `HTTPRoute` defines matching and backend forwarding

That split is not cosmetic. It encodes role separation. Cluster operators choose infrastructure. Platform or namespace owners define gateways. Application teams attach routes. Compared with legacy Ingress, this gives a cleaner contract between infrastructure and app routing.

The key conceptual gain in this lesson is that Gateway API is portable. The student is no longer learning "the Traefik way" or "the NGINX way." They are learning the standard object model that multiple controllers implement.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/gateway-api-new-standard>

### L04 — Envoy Gateway Setup

Once the standard is understood, the next problem is execution. Gateway API resources do nothing by themselves. A controller must watch them and translate them into a real proxy configuration. This lesson installs Envoy Gateway as that controller.

The page explains the two-plane design clearly:
- control plane: watches Kubernetes resources, translates them, and manages infrastructure
- data plane: Envoy proxies that actually process requests

It also introduces the xDS update model, which is the reason configuration changes can propagate without restarting proxies. That distinction matters in production. The user is not editing "the proxy" directly. They are editing Kubernetes resources that a controller reconciles into Envoy state.

The practical output is a working `GatewayClass`, a deployed Envoy Gateway control plane, and a first `Gateway` resource.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/envoy-gateway-setup>

### L05 — Traffic Routing with HTTPRoute

This lesson is where the chapter becomes genuinely expressive. `HTTPRoute` is the routing brain. The chapter explains that once the entry point exists, the real work is matching requests and steering them by path, headers, query parameters, and method.

It teaches:
- path matching modes such as `PathPrefix`
- header and query matching
- method-based routing
- weighted backend references for rollout control

The value here is precision. Instead of sending all traffic to one service, the reader learns to send versioned requests, beta traffic, or partial rollout traffic to specific backends. The chapter is effectively moving from "ingress exists" to "traffic is programmable."

That makes `HTTPRoute` the central object for later lessons on rate limiting, TLS attachment, progressive delivery, and AI-gateway routing.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/traffic-routing-httproute>

### L06 — Rate Limiting and circuit breaking

This lesson introduces `BackendTrafficPolicy` as Envoy Gateway's main control surface for backend protection. The chapter's framing is correct: open APIs are not only vulnerable to performance collapse but, in AI systems, to runaway cost.

The lesson covers:
- local and global rate limiting
- per-user quotas using a distinct selector such as `x-user-id`
- HTTP 429 behavior when quotas are exceeded
- circuit breaking and retry logic

The strongest move in the lesson is that it keeps the limits attached to traffic policy rather than teaching them as random app-level hacks. That keeps edge protection declarative and visible. For multi-user systems, the per-user header model is especially important because it prevents one user from consuming the entire shared budget.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/rate-limiting-circuit-breaking>

### L07 — TLS termination with cert-manager

This page handles the certificate lifecycle. The core argument is straightforward: HTTPS is mandatory, and manual certificate handling does not survive real operations because renewal deadlines eventually get missed.

The lesson explains:
- cert-manager installation via Helm
- `ClusterIssuer` configuration
- ACME HTTP-01 solving through Gateway-attached routes
- certificate material landing in Kubernetes TLS secrets
- automatic certificate rotation without proxy restarts

The operational point is important: Envoy Gateway watches the TLS secrets, so renewed certificates can be picked up quickly. That turns TLS from a manual recurring task into a controller-managed workflow.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/tls-termination-certmanager>

### L08 — Traffic splitting patterns

This lesson covers progressive delivery. It argues that staging success is not enough and that new versions should earn production traffic gradually.

The three patterns are:
- canary rollout through weighted backends
- blue-green switching for cutover
- A/B testing through routing rules and headers

The canary example is the most important because it teaches a sequence of traffic weights rather than a binary switch. That is the core production habit the chapter wants the learner to adopt: expose a new version slowly, watch metrics, then continue or roll back.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/traffic-splitting-patterns>

### L09 — Autoscaling with HPA, VPA, and KEDA

This lesson broadens traffic engineering into capacity management. The chapter treats fixed replica counts as both wasteful and brittle, which is correct.

It draws a clean division of labor:
- HPA for scaling replica count from metrics such as CPU
- VPA for adjusting resource requests and limits
- KEDA for event-driven scaling and scale-to-zero behavior

The use of KEDA is the most relevant piece for AI services because many agent workloads are queue-driven or bursty rather than steady HTTP traffic. The lesson also keeps VPA in a cautious mode at first by using recommendations before automatic mutation. That is good operational advice.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/autoscaling-hpa-vpa-keda>

### L10 — Resilience patterns

This page shifts from routing and scaling into failure behavior. The lesson's premise is that healthy-looking systems still fail on transient network issues, slow dependencies, and planned disruptions.

The chapter teaches:
- retry policy for transient failures
- timeout policy to stop slow dependencies from consuming resources indefinitely
- PodDisruptionBudget to preserve availability during voluntary disruption
- graceful shutdown behavior so in-flight work completes during termination

This is one of the stronger lessons because it keeps resilience concrete. The retry examples show a measurable improvement in successful responses, and the timeout section explains why retry time budgets must be coordinated with total request timeouts. That is the kind of detail that separates a demo setup from a production one.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/resilience-patterns>

### L11 — Envoy AI Gateway for LLM traffic

This lesson is the chapter's AI-specific extension. Its central claim is right: request-count rate limiting is a poor fit for LLM systems because two requests can differ by orders of magnitude in token cost.

The lesson introduces Envoy AI Gateway as a way to:
- present a unified endpoint across LLM providers
- translate provider-specific request and response formats
- extract token usage from responses through `LLMRequestCost`
- enforce per-user or per-model token budgets
- configure provider fallback chains

This is the point where "traffic engineering" turns into "cost-aware traffic engineering." The chapter makes the budget unit explicit: tokens, not requests. It also connects routing to resilience by showing provider fallback rather than treating provider choice as static.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/envoy-ai-gateway-llm-traffic>

### L12 — Capstone: production traffic for the Task API

The capstone returns to a specification-first workflow. Rather than asking the learner to throw YAML together from memory, it asks them to define what "production-ready" means and then generate, validate, and finalize the stack accordingly.

The success criteria focus on four practical outcomes:
- external reachability
- protection against abuse
- encrypted transport
- automatic scaling

The capstone also closes the loop on the skill-building pattern. The final deliverable is not only a working Task API traffic stack but a production-tested `traffic-engineer` skill with templates, references, and decision logic that can be reused on future deployments.

Source: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/capstone-production-traffic-task-api>

## What the chapter adds, structurally

This chapter adds four big things to the curriculum.

### 1) It upgrades service exposure into policy-driven edge management
Earlier chapters got workloads running and observable. This one turns them into externally consumable services with explicit traffic contracts.

### 2) It treats Gateway API as the long-term abstraction
The chapter uses Traefik as a stepping stone, but the target abstraction is portable Gateway API plus a chosen implementation such as Envoy Gateway.

### 3) It expands traffic engineering into cost engineering
Rate limiting is first taught as abuse control, then extended into token-aware control for LLM systems. That is one of the chapter's strongest moves.

### 4) It turns configuration patterns into a reusable sellable skill
Like many chapters in this curriculum, the capstone is not merely a lab. It is framed as portfolio-grade skill packaging.

## Practical takeaways

- `ClusterIP` solves internal service discovery, not external access.
- `LoadBalancer` exposes a service, but does not give you a flexible shared routing layer.
- Legacy `Ingress` worked, but controller-specific annotations turned advanced behavior into a maintenance problem.
- Gateway API gives a better resource split: implementation (`GatewayClass`), edge listener (`Gateway`), and routing logic (`HTTPRoute`).
- Envoy Gateway supplies the control plane and Envoy data plane that make Gateway API resources real.
- `BackendTrafficPolicy` centralizes rate limits, retries, and circuit breaking at the edge.
- cert-manager converts TLS from recurring manual work into a controller-managed lifecycle.
- Traffic splitting should be gradual and observable.
- KEDA matters for AI systems because many workloads are event-driven and can benefit from scale-to-zero.
- AI traffic must often be governed by token usage and provider fallback, not by request count alone.

## Current live-navigation note

In the live site sequence available on 2026-03-26, the chapter ends at the capstone page and then links straight to Chapter 87. I did not find a separately exposed Chapter 86 quiz page in the authored next-page flow, so this drilldown treats the capstone as the chapter terminus.

## Source links

- Overview: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering>
- Build Your Traffic Engineering Skill: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/build-your-traffic-engineering-skill>
- Ingress Fundamentals: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/ingress-fundamentals>
- Traefik Ingress Controller: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/traefik-ingress-controller>
- Gateway API - The New Standard: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/gateway-api-new-standard>
- Envoy Gateway Setup: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/envoy-gateway-setup>
- Traffic Routing with HTTPRoute: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/traffic-routing-httproute>
- Rate Limiting & Circuit Breaking: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/rate-limiting-circuit-breaking>
- TLS Termination with CertManager: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/tls-termination-certmanager>
- Traffic Splitting Patterns: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/traffic-splitting-patterns>
- Autoscaling with HPA, VPA & KEDA: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/autoscaling-hpa-vpa-keda>
- Resilience Patterns: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/resilience-patterns>
- Envoy AI Gateway for LLM Traffic: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/envoy-ai-gateway-llm-traffic>
- Capstone: Production Traffic for Task API: <https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/traffic-engineering/capstone-production-traffic-task-api>
