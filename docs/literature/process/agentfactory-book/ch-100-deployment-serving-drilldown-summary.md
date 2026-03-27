# Chapter 100: Deployment & Serving - drilldown summary

## Source record
- Source type: course chapter and lesson sequence
- Title: Chapter 100: Deployment & Serving
- Venue: Agent Factory
- URL: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/deployment-serving
- Traversed lessons:
  - Build Your Model Serving Skill
  - Model Export Formats
  - Quantization for Inference
  - Ollama Installation and Configuration
  - Serving Custom Models Locally
  - vLLM Production Architecture
  - Performance Optimization for Inference
  - Capstone: Deploy Task API Model

## Main idea
Chapter 100 explains how to turn a trained model into a usable service, with the central claim that deployment is not just a packaging step but a systems discipline that requires correct format choice, hardware-aware quantization, reliable serving infrastructure, performance measurement, and a reusable serving skill.

## Chapter thesis and structure
The chapter begins by defining the outcome: a reusable `model-serving` skill and a production-ready endpoint for the Task API model. It then moves through the deployment stack in order. First it decides how model artifacts should be packaged for different targets. Next it shows how quantization changes the hardware budget and deployment envelope. It then establishes Ollama as the local serving baseline, explains how to register and expose a custom model, and contrasts that local path with vLLM as the production engine for high-concurrency GPU workloads. The chapter closes by treating optimization as a measured workflow and by using a capstone to combine export, configuration, serving, wrapping, monitoring, documentation, and packaging into one deliverable.

## Lesson drilldown

### 1) Build Your Model Serving Skill
The opening lesson uses the same skill-first method seen in earlier parts of the curriculum. Instead of starting with ad hoc deployment experiments, it has the learner create a `LEARNING-SPEC.md` and a `model-serving` skill grounded in official documentation. The point is to convert deployment knowledge into a reusable operating asset rather than leave it as scattered commands and half-remembered setup steps.

The lesson defines the scope of the skill clearly. It is meant to answer later questions about export formats, quantization levels, Ollama configuration, REST integration, and latency tuning. That framing matters because model serving is presented as a moving target. Configuration values, supported formats, and serving backends change quickly, so the durable thing is not memorized syntax but a process for consulting authoritative sources and updating the skill.

It also establishes the chapter's method: each subsequent lesson should improve the skill. The result is that the chapter is not just teaching a deployment path once. It is building a reusable decision system for future deployments.

### 2) Model Export Formats
This lesson explains that deployment starts with packaging. A trained model may exist as tensors, but different serving environments require different artifact formats. The chapter distinguishes between GGUF as the local inference standard and safetensors as the cloud and research standard, while also noting that older GGML and PyTorch `.bin` formats still appear in older workflows and often need conversion.

The real lesson is that format choice is deployment-target choice. GGUF is positioned as the correct format for Ollama, llama.cpp, and consumer-hardware inference because it is self-contained, supports quantization, and is designed for efficient local loading. Safetensors is positioned as the right format for training checkpoints, Hugging Face workflows, and cloud serving stacks such as vLLM because it is safe, fast to load, and native to modern model tooling.

The chapter therefore rejects the idea of a universally best format. It instead gives a decision rule: keep safetensors for training and cloud-oriented storage, then convert to GGUF when the target is local inference. Conversion is treated as a routine part of deployment, not an exceptional migration step.

### 3) Quantization for Inference
After choosing a format, the chapter turns to quantization as the main way to make deployment fit real hardware. Quantization is presented as a direct trade between memory footprint, speed, and quality. The chapter's framing is practical: a full-precision model may simply not fit the target machine, so the real question is not whether quantization is elegant but which quality loss is acceptable for the use case.

The lesson organizes the decision around deployment context. Q4-class formats are presented as the default for constrained local inference, Q5 as the middle ground when quality matters more, and Q8 as the higher-quality option when memory allows it. The chapter repeatedly ties those choices back to specific hardware budgets, including GPU VRAM and Apple Silicon unified memory, so quantization is treated as hardware planning rather than a generic optimization trick.

It also emphasizes that quantization must be validated empirically. The learner is expected to compare model behavior after quantization rather than assume a smaller model remains acceptable. That keeps the chapter aligned with the earlier evaluation material: compression is only useful when the deployed behavior still meets the task requirements.

### 4) Ollama Installation and Configuration
This lesson establishes Ollama as the local-serving baseline. The chapter presents Ollama as the tool that simplifies model management, API exposure, and hardware acceleration for local deployments. Its importance in the chapter is not that it is the only serving backend, but that it offers a workable local default with a simple interface and fast iteration loop.

The lesson explains Ollama as a small serving stack rather than a single command. It exposes REST endpoints, manages model loading, and provides configuration points through environment variables and service settings. The chapter includes platform-specific installation paths and then focuses on the operational settings that matter in practice, such as model storage location, host binding, GPU memory limits, and service-level configuration.

This lesson therefore converts Ollama from a development convenience into an explicitly managed runtime. The chapter wants the learner to understand that serving begins with a dependable local process: correct installation, verifiable runtime state, and configuration that can be reasoned about and changed deliberately.

### 5) Serving Custom Models Locally
Once Ollama is in place, the chapter shows how to serve an actual model. The deployment path is explicit: place the GGUF file and Modelfile together, register the model with `ollama create`, verify the output interactively, then integrate it into Python code or direct REST calls. This makes deployment concrete rather than abstract.

The Modelfile is the key artifact in this lesson. It binds the exported weights to serving parameters, stop sequences, a system prompt, and a chat template that matches the training format. That makes the lesson important for more than mere registration. It shows that deployment quality depends on carrying forward the behavioral assumptions from training into the serving layer. If the template or parameters drift, the served model may behave differently even if the weights are unchanged.

The lesson then extends the local deployment into application-facing integration. It covers Python library calls, REST endpoints, streaming, and error handling. The point is that a served model is only useful once an application can invoke it reliably, parse its responses, and recover cleanly from failure modes.

### 6) vLLM Production Architecture
This lesson marks the boundary between local serving and production serving. Ollama remains the recommended local tool, but the chapter argues that it is not the right answer once concurrency, latency budgets, and GPU cost efficiency become central constraints. That is the role assigned to vLLM.

The chapter explains vLLM through its underlying serving mechanics rather than through branding. PagedAttention is presented as the core innovation because it reduces KV-cache waste by allocating memory in blocks instead of with large contiguous reservations. Continuous batching is then introduced as the scheduling strategy that keeps GPUs busy by letting requests enter and leave the batch dynamically. Prefix caching and speculative decoding are added as higher-level optimizations for repeated prompts and faster token generation.

The lesson's decision logic is explicit. Ollama is for development, low concurrency, and local machines. vLLM is for high-concurrency production, strict latency targets, cloud GPU deployments, and environments where throughput and cost matter enough to justify more infrastructure. The chapter even proposes a hybrid path: Ollama for local iteration, vLLM for staging and production.

### 7) Performance Optimization for Inference
With a serving system in place, the chapter shifts to optimization. The key claim is that performance work must be systematic. The learner is not supposed to tweak parameters at random. The workflow is measure first, identify the real bottleneck, apply the lowest-cost improvement that addresses it, then re-measure and validate that output quality remains acceptable.

The lesson distinguishes among several optimization layers. The quickest wins come from parameter tuning such as reducing context length, constraining output length, lowering temperature for structured tasks, and adjusting batch settings. Beyond that, the chapter adds exact-match and semantic caching, prompt compression, better example selection, streaming for perceived latency, and metric-based monitoring. This establishes that performance is not a single knob; it is the combined effect of request shape, model settings, caching, and runtime behavior.

Just as important, the lesson treats optimization as constrained by correctness. A deployment that is fast but serves stale cached responses, truncates necessary output, or quietly harms quality has not actually improved. The chapter therefore keeps performance tied to validation rather than treating latency reduction as success on its own.

### 8) Capstone: Deploy Task API Model
The capstone turns the chapter into a specification-driven integration exercise. The learner must deploy a fine-tuned Task API model that returns structured JSON, expose it through a FastAPI wrapper, provide health and readiness behavior, document the API, and package it for reuse or sale. The specification includes both functional and non-functional requirements, so deployment is judged as a productized service rather than as a working demo.

This lesson is where the chapter's parts converge. The learner must export and quantize the model, configure the Modelfile, register the model in Ollama, wrap it in FastAPI, add structured logging, expose health checks, support streaming, and verify latency targets. The capstone also extends deployment into packaging and commercial readiness by adding Docker, documentation, and a marketplace-style presentation layer.

The capstone's larger point is that serving is the final integration layer for the whole LLMOps sequence. A model is not finished when it scores well in training or evaluation. It is finished when it becomes a service with defined behavior, observable health, operational boundaries, and a form that applications or customers can actually consume.

## Major supporting points
- Deployment starts with a reusable `model-serving` skill built from documentation rather than memory.
- Model format is not neutral; GGUF and safetensors serve different deployment targets and should be selected accordingly.
- Quantization is the main mechanism for fitting models to hardware, but it must be balanced against quality loss and validated empirically.
- Ollama is the local-serving baseline because it simplifies model registration, API access, and configuration on consumer hardware.
- Local serving quality depends on correctly carrying forward templates, parameters, and system behavior through the Modelfile.
- vLLM is the production answer when concurrency, latency, and GPU cost efficiency become the dominant constraints.
- Performance optimization requires measurement, bottleneck analysis, staged interventions, and post-change validation.
- The capstone treats deployment as productization: a served model must also be wrapped, monitored, documented, and packaged.

## Major explanations
- The chapter prefers skill-first learning because serving knowledge changes quickly, while a documentation-grounded skill can be updated and reused.
- GGUF is favored for local inference because it is quantization-friendly and self-contained, whereas safetensors is favored for training and cloud-serving stacks because it integrates cleanly with those ecosystems.
- Quantization matters because consumer hardware often cannot load the full-precision model, so deployment feasibility depends on reducing the memory footprint enough to fit the target machine.
- vLLM outperforms simpler serving paths under load because PagedAttention reduces KV-cache waste and continuous batching keeps GPU utilization high.
- Optimization is framed as a workflow because latency problems can come from different phases of inference, and the wrong fix can waste effort or damage quality.
- The capstone includes health checks, logging, and packaging because a model endpoint is only production-ready when it is observable, debuggable, and easy to integrate.

## Ending move
The chapter ends by recasting deployment as the final translation layer between model work and usable software. The learner is expected to leave with a serving skill, a working Task API service, and a method for deciding how to package, run, optimize, and expose future models under real hardware and reliability constraints.

## Condensed summary
In Chapter 100: Deployment & Serving, Agent Factory explains how to turn a trained model into a dependable service by treating deployment as a full systems problem rather than a final export step. The chapter first has the learner build a reusable `model-serving` skill, then explains how to choose between GGUF for local inference and safetensors for cloud and training workflows. It next shows how quantization changes the practical hardware budget and why those tradeoffs have to be checked against real output quality. Ollama is presented as the default local-serving runtime, followed by a complete workflow for registering and integrating a custom model through a Modelfile, Python calls, and REST endpoints. The chapter then introduces vLLM as the production serving path for high-concurrency, latency-sensitive GPU workloads, focusing on PagedAttention, continuous batching, prefix caching, and speculative decoding. It closes by treating optimization as a measured loop and by using a capstone to combine export, serving, FastAPI wrapping, health checks, documentation, Docker packaging, and performance targets into a production-style deployment for the Task API model.

## Reference
Agent Factory. "Chapter 100: Deployment & Serving" and associated lesson pages in Part 8, Turing LLMOps - Proprietary Intelligence. https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/deployment-serving
