# Chapter 94: Supervised Fine-Tuning (SFT): drilldown summary

## Source record
- Source type: chapter landing page plus lesson sequence
- Title: Chapter 94: Supervised Fine-Tuning (SFT)
- Venue: Agent Factory
- URL: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/supervised-fine-tuning
- Scope used for this summary: chapter landing page plus lessons from Build Your Fine-Tuning Skill through Capstone - Task API Model

## Chapter thesis
Chapter 94 explains supervised fine-tuning as a repeatable LLMOps skill for turning a general model into a domain-specific component. The chapter does not frame SFT as a one-off notebook exercise. It has the reader build a reusable `llmops-fine-tuner` skill first, then use that skill to reason through data preparation, adapter choice, quantized training, configuration, diagnostics, evaluation, and export. Its main claim is that proprietary model quality comes less from mystical training tricks than from a disciplined chain: clean task data, the right PEFT method for the hardware budget, stable training settings, careful monitoring, and objective success criteria.

## Chapter-level structure
The landing page defines the chapter as a practical sequence for training with LoRA and QLoRA through Unsloth on a Colab T4 GPU. The goals are narrow and operational: prepare SFT datasets, run LoRA or QLoRA training, evaluate checkpoints, manage artifacts, and capture the working knowledge inside a fine-tuning skill. The stated outcome is not just a trained model. It is a trained Task API model plus a reusable skill that can be applied to future datasets.

The lesson sequence moves from foundations to execution in a deliberate order. First the chapter establishes why SFT exists and where it sits relative to pre-training and prompting. Then it narrows to PEFT, with LoRA as the baseline, QLoRA as the memory-saving variant, and DoRA as the higher-fidelity alternative when quality pressure justifies extra complexity. After that, the chapter shifts into configuration and execution, then ends with troubleshooting, capstone evaluation, and GGUF export for local serving.

## Lesson-by-lesson drilldown

### Lesson 0: Build Your Fine-Tuning Skill
The opening lesson repeats the curriculum's skill-first rule. Before learning the mechanics in depth, the reader creates an `llmops-fine-tuner` skill backed by official Unsloth documentation rather than memory. The lesson treats this as the difference between temporary study and reusable capability. Notes decay, but a maintained skill can be queried, revised, and delegated.

The actual scaffold is concrete. The reader clones a fresh skills lab, writes a learning specification with success criteria and hardware constraints, fetches official fine-tuning documentation, and then drafts a skill file that encodes dataset preparation, model selection, LoRA and QLoRA configuration, monitoring, and export. The lesson's real subject is not just file creation. It is knowledge externalization: turn procedural know-how into an operational artifact before the details multiply.

### Lesson 1: SFT Fundamentals
This lesson defines what supervised fine-tuning changes. SFT does not merely feed more facts into a model. It changes the model's behavior patterns so that it responds in a particular domain, format, or voice. The chapter places SFT between pre-training and prompting in the customization stack: pre-training builds general language ability at enormous cost, SFT specializes a pretrained model at moderate cost, and prompting plus RAG gives per-request control with no weight updates.

The lesson also draws the decision boundary around when SFT is justified. The chapter treats SFT as the right tool when behavior needs to become stable and internal to the model, not merely injected through prompts. It also makes the alternative cases explicit: use RAG when the information must stay current, prompting when you are still experimenting with behavior, and few-shot prompting when you have too little data to support training. The data guidance is blunt: a few hundred examples is only a minimum, one thousand or more is a stronger production target, and data quality deserves far more attention than the training run itself.

### Lesson 2: PEFT and LoRA Deep Dive
This lesson introduces LoRA as the standard way to make SFT feasible on ordinary hardware. Full fine-tuning updates every parameter in the base model, which drives VRAM requirements and produces a full-size derived model. LoRA freezes the original matrices and learns a low-rank update through small adapter matrices. The chapter's point is that task adaptation usually lives in a much smaller subspace than the full parameter space, so the model does not need a full rewrite.

The lesson then turns that intuition into configuration judgment. It shows how the forward pass combines the frozen base weights with the adapter contribution, then explains rank as the central capacity dial. Lower ranks suit light formatting or stylistic shifts, middle ranks suit typical domain adaptation, and higher ranks are reserved for larger behavioral changes when the data volume can support them. The chapter treats rank selection as a function of two variables: how far the target behavior is from the base model, and how much training data is available without driving overfitting.

### Lesson 3: QLoRA: Quantized Training
This lesson extends LoRA by reducing the memory cost of the frozen base model. LoRA cuts trainable parameters, but the frozen weights still occupy memory. QLoRA stores those frozen weights in 4-bit form, which makes 7B to 8B models feasible on a free Colab T4 with 15GB of VRAM. The chapter's central claim here is practical: if the base model is frozen, it does not need full-precision storage during training.

The lesson emphasizes two implementation choices. First, it recommends NF4 because neural network weights follow an approximately normal distribution, so NF4 allocates its quantization levels where the weights actually cluster. Second, it recommends double quantization because even the scaling factors used by quantization consume memory, and quantizing those factors further reduces the overhead. The result is a decision framework for constrained hardware: use QLoRA when VRAM is the bottleneck, keep compute precision appropriate to the GPU, and treat the quantization settings as part of the training design rather than as incidental flags.

### Lesson 4: DoRA: The Next Evolution Beyond LoRA
This lesson presents DoRA as an answer to a limitation in LoRA rather than as a wholesale replacement. The chapter explains that LoRA couples magnitude and direction changes in its update, while full fine-tuning can adjust those dimensions more independently. DoRA separates them, which is why it can produce better behavior at the same inference cost after the weights are merged.

The chapter is especially interested in where that extra fidelity matters. It says DoRA helps most when low ranks are desirable, when the task requires subtle behavioral adaptation, and when identity or persona consistency matters. It also gives a practical rule instead of treating DoRA as mandatory. If VRAM is sufficient and model quality is the priority, DoRA is preferred. If memory is tighter, QDoRA is the alternative. If time is limited and an existing LoRA or QLoRA configuration already works, the chapter accepts staying with the simpler adapter path.

### Lesson 5: Training Configuration
This lesson treats configuration as the point where most fine-tuning attempts either stabilize or fail. The chapter gives the reader a symptom-based model rather than a bag of defaults. If loss stays flat, the learning rate may be too low or the data may be malformed. If loss explodes, the learning rate is probably too high. If memory runs out, batch size or sequence length is too large. If the model forgets base knowledge, the run is too aggressive or too long.

The core parameters are organized by effect. Learning rate is the main control, and the chapter explicitly notes that LoRA and QLoRA can tolerate much larger rates than full fine-tuning because only the adapters are being updated. For the small Task API example, it recommends `2e-4` as the QLoRA starting point. Warmup is framed as a stabilizer for randomly initialized adapters. Batch size and gradient accumulation are treated together because effective batch size depends on both, especially on small GPUs. The lesson's real goal is to replace guesswork with a framework that links each observed failure mode to the parameter most likely to cause it.

### Lesson 6: Lab - Your First Fine-Tune
This lab converts the previous lessons into a complete run. The reader sets up Colab on a T4 GPU, installs Unsloth, prepares the dataset, loads the base model in a quantized configuration, attaches the adapters, and instantiates `SFTTrainer` with the chapter's small-scale settings. The lab is not abstract. It is scoped to one hour and tuned to a constrained environment.

The training setup shows how the chapter expects the reader to reason numerically. The sample run uses three epochs, batch size four, gradient accumulation four, `2e-4` learning rate, `0.03` warmup ratio, and epoch-based checkpoint saving. The lesson then explains what those numbers imply in terms of effective batch size and total training steps. That matters because the chapter wants the reader to see a run as a controlled experiment with known resource and convergence behavior, not as a black-box command.

### Lesson 7: Troubleshooting and Monitoring
This lesson argues that training problems are inevitable, so the operative skill is diagnosis rather than optimism. The chapter gives a simple process: observe the exact symptom, form a causal hypothesis, change one thing, and document the result inside the skill. That last step is not decorative. It is the way one-off debugging becomes a reusable troubleshooting method.

The main diagnostic instrument is the loss curve. A healthy run starts high, drops quickly at first, slows as it learns finer distinctions, and then flattens as it converges. A flat high loss indicates underfitting or a broken setup. Divergence between falling training loss and rising validation loss indicates overfitting. The chapter pairs each pattern with likely causes and fixes, such as raising the learning rate, correcting prompt or EOS formatting, checking that adapters are actually trainable, or reducing epochs. The lesson treats monitoring as applied interpretation, not as passive logging.

### Lesson 8: Capstone - Task API Model
The capstone promotes the whole chapter from tutorial mode to specification-driven work. The first move is to write the Task API model specification before implementation: the model's intent, what it should do, what quality means, what is out of scope, and how it will later integrate with function calling. The chapter uses this step to separate professional LLMOps from improvised experimentation.

Training itself is still straightforward, but success is not defined by loss alone. The capstone evaluates four things: domain understanding accuracy, human-rated response quality, clear improvement over the base model on the domain tasks, and successful GGUF export for local deployment in Ollama. The sample evaluation target for domain understanding is at least 90 percent, and the worked example reports 95 percent. The export step matters because the chapter wants the reader to finish with a deployable artifact, not just a checkpoint folder. A successful capstone ends with a quantized GGUF model that loads locally and behaves like a task-management assistant rather than a generic Llama response surface.

## What the chapter says the reader owns at the end
By the end of the chapter, the reader is expected to own a reusable `llmops-fine-tuner` skill, understand where SFT fits relative to pre-training and prompting, know when to choose SFT over RAG or prompting, know how LoRA reduces trainable parameters through low-rank adapters, know how QLoRA makes 7B to 8B training feasible on a T4 by quantizing frozen weights, know when DoRA is worth the added complexity, know how to configure a small Unsloth training run with sensible defaults, know how to diagnose bad loss curves and common training failures, know how to evaluate a model against explicit success criteria, and know how to export a finished model to GGUF for Ollama.

## Closing compression
The chapter's central claim is that supervised fine-tuning becomes professionally useful only when it is turned into a reproducible method. Data quality, adapter selection, quantized loading, training configuration, monitoring, evaluation, and export are all part of one system. Chapter 94 uses the Task API example to show that a proprietary model is not produced by pressing a training button. It is produced by defining the target clearly, choosing the smallest viable adaptation method, fitting the run to the hardware budget, reading the training signals correctly, and proving the result against concrete deployment-ready criteria.
