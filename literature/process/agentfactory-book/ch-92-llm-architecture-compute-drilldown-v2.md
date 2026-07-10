# Chapter 92 Drilldown: LLM Architecture & Compute

## Source and scope

This document condenses the full published chapter sequence for **LLM Architecture & Compute** from Agent Factory. It follows the chapter overview and the six lesson pages currently exposed in the live chapter path, ending with the hands-on lab page.

**Current site note:** the live next-page sequence ends at **Lab: Inference on T4** and then links straight to **Chapter 93**. I did not find a separately exposed Chapter 92 quiz page in the authored next-page flow.

## Main idea

This chapter gives the reader the minimum architecture and hardware literacy needed to make later fine-tuning work. Its argument is practical: if you do not understand where parameters live, how tokenization expands data, how attention drives memory growth, and how quantization plus activation controls change the budget, you will mis-size hardware, mis-format training data, and hit avoidable out-of-memory failures.

## Chapter throughline

The chapter moves in a strict order.

1. build a mental model of a transformer layer
2. show how text becomes tokens and why chat formatting matters
3. count parameters instead of trusting model-card headlines
4. turn parameter counts into a VRAM budget
5. compress the model with quantization
6. control the remaining training memory with checkpointing and accumulation
7. prove the whole stack on a Colab T4 with a quantized Llama inference lab

The running operational target is modest and concrete: get an 8B-class model to run on constrained hardware without guessing.

## What this chapter changes

Chapter 91 framed the decision problem for LLMOps. Chapter 92 supplies the physical constraints behind those decisions. After this chapter, "8B model" is no longer a vague size label. It becomes a budget made of embeddings, attention projections, FFN matrices, activations, optimizer state, and context-length tradeoffs. The chapter keeps returning to the same point: architecture choices become compute costs.

## Lesson-by-lesson drilldown

### Overview: chapter contract

The overview frames the chapter as a build for an `llm-architecture` skill. The promised outcome is a reusable reference for tokenization, context windows, scaling laws, and hardware choices that later chapters can use when they move into data engineering and fine-tuning.

The overview is narrow in a good way. It does not promise broad theory. It promises operational judgment about architecture and compute.

### Lesson 1: Transformer Architecture Essentials

This lesson builds the internal map of a transformer. The chapter presents the model as:

`input tokens -> embedding layer -> transformer layers x N -> output projection -> predicted token`

The important move is not the diagram. It is the decomposition of each transformer layer into the parts that fine-tuning can actually touch: layer norm, multi-head attention, residual connection, layer norm again, FFN, and another residual path.

The lesson explains attention with query, key, and value projections, then shows why multi-head attention exists. A single head can learn one relationship. Multiple heads can split grammatical, semantic, positional, and reference-tracking patterns across parallel channels. For Llama-3-8B, the lesson uses 32 heads over a 4096-dimensional hidden state, which yields 128 dimensions per head.

The second half of the lesson shifts attention out of the spotlight and into proportion. The FFN is where a large share of the model capacity sits. The chapter gives a concrete Llama-3-8B count: each layer's gated FFN is about 176 million parameters, and the FFN stack dominates the total parameter budget. This matters because "fine-tuning the model" is mostly "adjusting very large projection matrices," not toggling a small set of symbolic rules.

The fine-tuning section closes the loop. Q, K, V, attention output projections, and FFN matrices are the primary trainable surfaces. LoRA is introduced only as a pointer: later chapters will avoid updating those full matrices directly by adding small adapters instead.

### Lesson 2: Tokenization and Context

This lesson argues that tokenization is part of model behavior, not a preprocessing footnote. The model never sees "words" in the human sense. It sees token IDs produced by a tokenizer with a fixed vocabulary and merge scheme. That affects dataset size, context efficiency, and how well specialized vocabulary survives intact.

The chapter walks through subword tokenization with Byte-Pair Encoding and compares character-level, word-level, and subword approaches. The operational conclusion is straightforward: subword tokenization gives a vocabulary that is large enough to keep common text efficient, but small enough to avoid an unmanageable out-of-vocabulary problem.

The lesson's useful detail is where it stops being abstract. Llama-3's larger vocabulary is presented as a practical efficiency gain because it tends to use fewer tokens for the same text than a 32K-vocabulary model. The chapter also states the hard limit behind every prompt format: attention cost grows quadratically with sequence length. Doubling context length does not merely add cost. It multiplies a major part of the memory and compute burden.

The section on chat templates is one of the chapter's most important operational warnings. Instruction-tuned models expect the exact delimiter structure they were trained on. If your fine-tuning data uses the wrong role markers or message framing, you are teaching the model on one protocol and evaluating it on another. The lesson treats that as a format bug, not a stylistic difference.

The domain-text examples are also useful. Technical terms can shatter into many weak subword pieces. The consequence is not only longer sequences. It is weaker semantic units during learning.

### Lesson 3: Parameter Counting and Model Sizes

This lesson turns model size from branding into arithmetic. The chapter defines the core formula:

`total parameters = embedding + (attention + FFN + layer norm) x layers + output head`

It then works through Llama-3-8B with actual dimensions. The embedding table is vocabulary size times hidden dimension. Attention is the sum of Q, K, V, and output projections, with Grouped Query Attention reducing the K and V cost. The FFN is shown as the largest block because Llama uses a gated FFN with three large projections rather than two.

The most useful result is the distribution. The chapter's own count puts roughly 70 percent of Llama-3-8B's parameters in the FFN, about 17 percent in attention, and the rest in embeddings and output projection. That reframes many later engineering choices. A model's headline size says less than its internal distribution.

This lesson also ties parameters directly to load-time memory. At FP16, each parameter takes 2 bytes, so an 8B model needs roughly 16 GB just to hold the weights. That is the floor before gradients, optimizer state, or activations enter the picture.

The practical value of the lesson is that it lets the reader verify model-card claims, estimate load costs from config values, and understand why two models with similar total size can still have different compute behavior.

### Lesson 4: VRAM Budget Planning

This is the chapter's decision lesson. Once parameter counts are clear, the chapter asks the real question: how much memory does training need, not just model loading?

The lesson breaks GPU memory into five buckets:

- model weights
- gradients
- optimizer state
- activations
- CUDA/kernel overhead

That decomposition matters because many first attempts at training fail by counting only the first bucket. The lesson gives a full-fine-tuning estimate for an 8B model at FP16 with sequence length 2048 and batch size 1. The result is about 97.5 GB. That is the chapter's blunt correction to the common "8B means 16GB" misunderstanding.

From there, the lesson pivots to QLoRA. By quantizing the frozen base weights and training only small LoRA adapters, the chapter drops the example budget to about 5.6 GB. That is the first place where the T4 becomes plausible.

The chapter is also careful about the remaining degree of freedom. Even after quantization, activations still scale with batch size and sequence length. The lesson treats those two variables as a trade, not as independent knobs you can keep turning upward.

The underlying claim is simple: VRAM planning should happen before the run starts. It is part of job design, not part of debugging after failure.

### Lesson 5: Quantization Deep Dive

This lesson moves from budgeting to compression mechanics. The chapter compares FP32, FP16, INT8, INT4, and NF4, then argues that NF4 matters because it matches the real weight distribution better than naive 4-bit schemes. Most weights cluster near zero, so a format that allocates more effective precision there loses less quality for the same storage cost.

The memory math section is deliberately plain. Halving bits halves raw weight storage. For an 8B model, FP16 is about 14.9 GB and INT4 is about 3.7 GB before overhead. That puts the earlier VRAM lesson on firmer ground.

The applied part of the lesson uses BitsAndBytes through Hugging Face Transformers. The chapter explains the role of `load_in_4bit`, `bnb_4bit_quant_type="nf4"`, compute dtype, and double quantization. Double quantization is presented as a small but material saving at tight margins because it compresses the quantization constants too.

The lesson does not pretend quantization is free. It gives a rough quality-loss estimate through perplexity and treats the penalty as measurable rather than mystical. The real standard is not "does 4-bit sound acceptable?" but "does the compressed model preserve enough behavior for the target task while fitting the available hardware?"

### Lesson 6: Memory Optimization Techniques

Quantization solves the base-model footprint. This lesson solves what remains during training. The chapter identifies activations as the dominant remaining problem once LoRA keeps gradient and optimizer state small.

The main tool is gradient checkpointing. Instead of saving every activation for the backward pass, the model saves a subset and recomputes the rest later. The chapter treats this as a clean time-memory trade: less VRAM, more compute time. The recommendation is explicit enough to be useful. On a 15 GB T4, gradient checkpointing is treated as effectively required for models above roughly 3B parameters.

The second tool is gradient accumulation. The lesson reframes batch size as two numbers: the micro-batch that fits in memory and the effective batch achieved by accumulating gradients across multiple steps. That keeps optimization behavior closer to a larger batch without requiring a larger simultaneous footprint.

The implementation examples are practical. The chapter shows a `TrainingArguments` configuration with small per-device batch size, checkpointing enabled, and gradient accumulation sized to reach an effective batch of 32. It also includes a batch-size search procedure that increases until out-of-memory and then backs off. That is the right habit: measure the ceiling on the actual hardware instead of relying on a generic recipe.

### Lesson 7: Lab: Inference on T4

The chapter ends with a direct proof. The lab walks through a Colab notebook that loads `Meta-Llama-3-8B-Instruct` on a T4 using 4-bit NF4 quantization with double quantization enabled. The notebook then formats a task-assistant prompt, runs generation, and verifies output quality on several sample prompts.

The lab is not a training run. It is a deployment sanity check for the chapter's earlier claims. If the architecture and memory lessons are right, the model should fit. The reported result is about 5 GB of reserved VRAM, which is close to the earlier estimate and leaves enough headroom for inference on the T4.

This matters for two reasons. First, it validates the previous calculations with a real hardware run. Second, it gives the reader a working baseline before later chapters add fine-tuning complexity. The chapter is careful about prerequisites here: the lab assumes the reader already understands VRAM budgeting, quantization, and memory optimization.

## What this chapter is really teaching

On the surface, this is a chapter about transformers, tokenizers, VRAM, and Colab.

At a deeper level, it teaches a discipline of constrained design:

- count before you run
- format before you train
- budget the full memory stack, not only the weights
- compress where precision is redundant
- trade time for memory when hardware is fixed
- verify the theory on a real device before moving to the next stage

That discipline matters more than any one number in the chapter. The numbers will change with new models and new hardware. The method will not.

## Reusable outputs from the chapter

By the end of the chapter, the reader should be able to produce:

- an `llm-architecture` reference skill
- a parameter-count worksheet for any transformer config
- a VRAM budget estimate for full fine-tuning vs QLoRA
- a tokenizer inspection routine for domain text
- a 4-bit loading configuration with BitsAndBytes
- a training configuration that combines checkpointing and gradient accumulation
- a Colab baseline notebook that proves an 8B instruct model can run on a T4

## Source links

- Overview: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute
- Lesson 1: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute/transformer-architecture
- Lesson 2: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute/tokenization-context
- Lesson 3: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute/parameter-counting
- Lesson 4: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute/vram-budget-planning
- Lesson 5: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute/quantization-deep-dive
- Lesson 6: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute/memory-optimization
- Lesson 7: https://agentfactory.panaversity.org/docs/Turing-LLMOps-Proprietary-Intelligence/llm-architecture-compute/lab-inference-t4
