# Chapter 79 — Docker for AI Services: drilldown

## Source scope

This document rebuilds the live Chapter 79 path under **Part 7: Deploying Agent Factories in the Cloud** and compresses it into one working summary. It covers the chapter overview, Lesson 0 through the capstone page, and the live end-state of the navigation.

## Chapter thesis

Chapter 79 teaches Docker as a production packaging method for AI services, not as a generic dev tool. The chapter's through-line is simple: first make container behavior legible, then make the image correct, then make it small, then make it safe, then encode the decision process as a reusable skill, and finally prove the result against a written specification. The stated outcome is a hardened image for the earlier Task API and a reusable Docker skill that can be applied to later services.

## Live chapter shape

The live overview exposes this sequence:

0. Build Your Docker Skill  
1. Docker Installation & Setup  
2. Container Fundamentals: Images, Containers, and Layers  
3. Writing Your First Dockerfile  
4. Container Lifecycle and Debugging  
5. Multi-Stage Builds & Optimization  
6. Production Hardening  
7. Docker Image Builder Skill  
8. Capstone: Containerize Your API  

In the current live navigation, the capstone page links straight to Chapter 80. I did not find a separately exposed Chapter 79 quiz page in the authored next-page sequence.

## What the overview page establishes

The overview frames the chapter around four target abilities: understanding container fundamentals, writing production Dockerfiles, debugging container runtime issues, and hardening images with environment configuration, health checks, and non-root execution. It also states the method clearly: foundations, then optimization, then skill design, then a spec-driven capstone. That sequencing matters because the chapter is really about operational judgment, not just Docker syntax.

## Lesson 0 — Build Your Docker Skill

The chapter begins by having the reader create a Docker skill before learning the tool in detail. The lesson tells the student to clone the Panaversity skills lab, open Claude in that repo, and use the skill creator plus Context7 to generate a Docker skill grounded in official docs. The point is not convenience. The point is to start the chapter with an explicit externalized reasoning scaffold. The rest of the chapter then becomes a test harness for that skill.

Operationally, this lesson establishes three ideas that recur later:
- the skill should be built from documentation rather than from the model's unstated priors
- the skill should ask clarifying questions instead of generating a one-size-fits-all Dockerfile
- the skill should live as a reusable artifact under `.claude/skills/docker-deployment/`

## Lesson 1 — Docker Installation & Setup

This lesson argues that containers solve the classic deployment drift problem: different Python versions, different operating systems, missing environment variables, misplaced model files, and inconsistent dependency states. It contrasts three deployment models:

- manual setup, which is fragile and non-reproducible
- virtual machines, which package a full guest OS and are heavier
- containers, which share the host kernel and therefore start faster and use fewer resources

For AI services, the lesson treats containers as especially useful because AI workloads often depend on large packages, version-sensitive libraries, environment-based configuration, and sometimes GPU access.

The lesson also establishes the base mental model:
- **Docker Engine** runs and manages containers
- **Docker Desktop** packages that engine for macOS and Windows inside a lightweight Linux VM
- **containerd** is the lower-level runtime that actually pulls images, unpacks them, and starts isolated processes

Later sections handle installation by OS, validation, a first `docker run`, and Docker Desktop resource sizing. The chapter is explicit that desktop resource allocation matters for AI workloads, and it flags a safety boundary: containers provide process isolation, not strong security isolation.

## Lesson 2 — Container Fundamentals: Images, Containers, and Layers

This lesson builds the vocabulary the rest of the chapter needs. It separates:

- **image**: the frozen, reusable artifact
- **container**: a running instance of that artifact
- **layer**: a cached filesystem delta that makes builds and pulls efficient

The chapter leans hard on immutability. Once an image is built, it does not change. That supports reproducibility, rollback, and integrity verification via digests. The practical payoff is that you can run multiple containers from the same image without sharing mutable state between them.

The hands-on sections turn this into command-line behavior:
- `docker run -it python:3.12-slim python` demonstrates an interactive container session
- `docker exec` shows how to inspect a running container without rebuilding it
- stopping and removing a container proves that the running instance is disposable, while the image remains intact

The layer section is the bridge to Dockerfile design. The lesson explains that each Dockerfile instruction produces a layer, and that the cache only helps if the high-churn steps are late and the stable steps are early. That concept becomes central in Lesson 3 and Lesson 5.

## Lesson 3 — Writing Your First Dockerfile

This lesson converts the image/container model into an authored build recipe. The Dockerfile is presented as a build specification, not a shell script. The chapter emphasizes the distinction between:

- `RUN`, which executes during build and creates a layer
- `CMD`, which executes at container start and does not create a build layer

The Task API example uses a Python slim base, copies `uv` from a published image, sets `WORKDIR`, copies dependency metadata first, installs packages, then copies source code. The ordering is the important part. Dependency files are copied before application code so that dependency installation can stay cached when only the source changes.

The lesson also shows the mechanical mapping between Dockerfile instructions and build output. Each step in the `docker build` log corresponds to a line in the Dockerfile. That makes the file debuggable. It is not a black box.

The runtime section then introduces useful run-time options:
- port mapping changes like `-p 9000:8000`
- environment injection with `-e LOG_LEVEL=debug`
- detached mode with `-d`
- named containers with `--name`

The lesson ends by covering common build errors, which fits the chapter's overall pattern: write the artifact, then learn how to read failure.

## Lesson 4 — Container Lifecycle and Debugging

This lesson is about reading container state instead of guessing. It treats debugging as a sequence of inspection layers:

1. check whether the container is running
2. read logs
3. inspect the container's internal state
4. verify ports and process behavior
5. reason about restart behavior

The logs section demonstrates the difference between a clean startup and an actual request record. The `docker exec` section adds a second layer of diagnosis by running commands inside a live container. That is the move you need when logs are not enough.

A later section handles host-port conflicts directly. The fix is concrete: if host port `8000` is already taken, map the next container to a different host port such as `8001:8000`. The container still listens on its internal port; only the host binding changes.

The restart-policy section closes the loop by moving from debugging into operations. The chapter recommends `--restart=unless-stopped` for production services so a container restarts after crashes and host reboots but still remains manually stoppable. That is a small but consequential operational default.

## Lesson 5 — Multi-Stage Builds & Optimization

This lesson asks a stricter question: now that the image works, why is it larger than it needs to be?

The lesson begins with a naive single-stage Python image at roughly **1.2 GB**. It then refactors the build into stages so compilation and package installation happen in a builder stage while the final runtime image carries only the runtime assets it actually needs. By the later optimized example, the image size is reduced to about **115 MB**.

This lesson contributes several concrete principles:

- use a dedicated builder stage for tools and compilers
- copy only the installed packages and binaries you need into the runtime stage
- inspect image history to find oversized layers
- choose a base image with explicit tradeoffs in mind

The base-image comparison is useful because it resists simplistic advice:
- `python:3.12-slim` is larger but more compatible
- `python:3.12-alpine` is smaller but can fail on packages that need C-extension compatibility
- distroless images improve security but make interactive debugging harder

For AI services, the lesson adds one domain-specific rule: do not bake large model files into the image. Mount them at runtime instead. The chapter treats this as non-negotiable because embedded model assets inflate images, slow pulls, and entangle deployment with artifact distribution.

## Lesson 6 — Production Hardening

This lesson adds the production controls that the earlier Dockerfiles omitted. Its core themes are runtime configuration, health signaling, and privilege reduction.

The lesson distinguishes two variable mechanisms:
- `ARG` for build-time configuration
- `ENV` for runtime configuration

That split matters because build-time variables disappear after the image is built, while runtime environment variables remain available to the process. The chapter uses this distinction to push the reader away from hardcoded configuration.

The security section then focuses on non-root execution. By default, containers run as root. The lesson treats that as an avoidable risk and instructs the reader to create an application user, switch to it, and keep ownership aligned with that user. The hardening checklist also includes:
- a `HEALTHCHECK` so orchestrators can assess service status
- environment defaults such as `LOG_LEVEL` and `PYTHONUNBUFFERED`
- no hardcoded secrets in the image or its history
- validation commands that confirm health status, user identity, and secret absence

The chapter's point here is that a container that merely runs is still incomplete. Production readiness requires proof that the image is observable, configurable, and constrained.

## Lesson 7 — Docker Image Builder Skill

This lesson abstracts the previous six lessons into a reusable agent skill. It argues that skill design should encode a reasoning pattern, not just a list of tips. The chapter's preferred structure is:

- **persona**: the operational stance and tradeoff priorities
- **analysis questions**: the context-gathering prompts that prevent generic output
- **principles**: the non-negotiable rules the agent must follow

The example persona is intentionally specific: think like a DevOps engineer optimizing for production Kubernetes, balancing size, speed, security, and simplicity, and preferring smaller runtime artifacts over build-time convenience.

The analysis-question section gathers the constraints a Dockerfile actually depends on, including health monitoring needs, build context, file exclusions, and private-registry access. The principles then convert the lessons into stable defaults: multi-stage builds, careful layer order, explicit image tags, non-root execution, no secrets in the image, health checks, environment-based configuration, and runtime volume mounts for very large files.

The lesson also defines deliverables for a good generation pass:
- a commented Dockerfile
- a `.dockerignore`
- optionally a `docker-compose.yaml` if the service shape requires it
- a size estimate relative to a naive build

At the end, the chapter names the larger purpose: intelligence accumulation. Personal know-how becomes shared, repeatable organizational capability.

## Lesson 8 — Capstone: Containerize Your API

The capstone re-runs the whole chapter as a spec-driven deployment exercise. The goal is a production image for the Task API, including a SQL-backed variant, with evidence that it works locally and across machines.

The capstone defines success criteria before the build:
- image builds without error
- image size stays under **200 MB**
- CRUD endpoints work
- `/health` responds
- the service can connect to the Neon database through `DATABASE_URL`
- the image can be pushed to a registry
- the image can be pulled and run on another machine
- the container runs as a non-root user

The example Dockerfile uses a two-stage Alpine-based build, installs dependencies with `uv`, creates a minimal runtime image, and validates runtime behavior with HTTP requests and an explicit `whoami` check that returns `appuser`.

The registry section treats publication as part of completion, not as an optional extra. The image is tagged for Docker Hub or GHCR, pushed, then pulled and run elsewhere. The chapter treats that cross-machine validation as the real end of the "works on my machine" problem.

The final checklist then ties the build back to the original specification. Each criterion is marked with evidence: build logs, image size, endpoint tests, health response, persistence against Neon, registry publication, cross-machine run, and non-root confirmation.

## What the chapter is really teaching

Under the Docker topic, the chapter is teaching a wider deployment discipline:

1. Make the artifact reproducible.
2. Make the running behavior inspectable.
3. Make the image small enough to move cheaply.
4. Make the container safe enough to operate.
5. Turn the resulting judgment into a reusable skill.
6. Prove the result against an explicit specification.

That is why the skill lesson belongs in the same chapter as Dockerfile syntax. The curriculum treats operational competence as something you should encode and reuse, not re-derive every time.

## Reusable patterns extracted from the chapter

### 1. Stable-first build order
Copy dependency manifests before high-churn source files so the expensive install layer stays cacheable.

### 2. Builder/runtime separation
Use multi-stage builds to keep compilers and other build-only tools out of the final image.

### 3. Disposable container mindset
Treat containers as replaceable runtime instances. Debug them through logs, inspect, and exec; rebuild the image rather than patching the container by hand.

### 4. Runtime configuration only
Keep secrets and environment-specific settings out of the image. Inject them at runtime.

### 5. Explicit health and privilege controls
Expose health endpoints, define `HEALTHCHECK`, and run as a non-root user.

### 6. Specification before publication
Before pushing to a registry, define success criteria and gather evidence that each one is met.

## Practical output of the chapter

If a reader completes the chapter as written, they should end with:
- a working Docker skill for future services
- a production Dockerfile for the Task API
- a small runtime image produced through a multi-stage build
- a health-checkable, non-root container
- a published image in a registry
- a validation trail that ties the build back to a written specification

## Source pages

- [Chapter 79 overview](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services)
- [Build Your Docker Skill](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/build-your-docker-skill)
- [Docker Installation & Setup](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/docker-installation-and-setup)
- [Container Fundamentals: Images, Containers, and Layers](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/container-fundamentals)
- [Writing Your First Dockerfile](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/writing-your-first-dockerfile)
- [Container Lifecycle and Debugging](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/container-lifecycle-and-debugging)
- [Multi-Stage Builds & Optimization](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/multi-stage-builds-and-optimization)
- [Production Hardening](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/production-hardening)
- [Docker Image Builder Skill](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/docker-image-builder-skill)
- [Capstone: Containerize Your API](https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/docker-for-ai-services/capstone-containerize-your-api)
