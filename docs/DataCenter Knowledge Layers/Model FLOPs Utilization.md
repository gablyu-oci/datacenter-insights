# Model FLOPs Utilization

Actual model FLOPs performed / theoretical peak GPU FLOPs; 30% - 50% MFU is pretty good
		- FLOP = floating-point operation
		- PFLOP = petaFLOP = 1 quadrillion FLOP
			- H100 NVL: BF16/FP16: 1 dense, FP8: 3 sparse PFLOP
			- GB200 NVL72 Blackwell: BF16/FP16 5 sparse -20 FP8 sparse PFLOP
	- Decided by: 
		- model size: larger model = more efficiently bc matrix multiplications are bigger
		- Batch size/sequence length: bigger=more occupancy until memory becomes a bottleneck
		- precision: [[#FP8 / BF16 / FP16 / FP4]]
		- Kernel efficiency: [[#FlashAttention]], [[#Fused ops]], [[#Optimized GEMMs]], [[#Compiler / runtime choices]]
		- Memory bandwidth: workload is memory-bounded, gpu waits on HBM reads/writes instead of doing math
		- GPU-GPU communication: [[#Tensor parallelism]], [[#Pipeline parallelism]], [[#All-reduce]], [[#All-gather]], and [[#MoE / MoAE routing]] can reduce MFU
		- Networking: Multi-node training needs fast [[#InfiniBand / RoCE / NVLink fabric]]. Slow networks = lower MFU
		- CPU/data pipeline: CPUs, [[#Dataloaders]], tokenization, storage, networking
		- [[#Activation checkpointing / recomputation]]: saves memory but adds extra compute
		- parallelism strategy: [[#Data parallelism]], tensor parallel, pipeline parallel, sequence parallel, [[#Expert parallelism]], and [[#ZeRO / FSDP]] choices
	- **GPU utilization can be high while MFU is low**. The GPU might be “busy,” but busy on memory movement, communication, inefficient kernels, or non-model work rather than useful model FLOPs.

## A training step is not just matrix math. It is a pipeline

```
load data
move data to GPU
forward pass
attention
MLP/GEMMs
communication
backward pass
gradient sync
optimizer update
checkpointing/logging
```

MFU is high when most wall-clock time is spent here:

```
large efficient Tensor Core GEMMs
optimized attention
well-overlapped communication
well-fed GPUs
```

MFU is low when time leaks into:

```
waiting for dataloader
waiting for network
tiny inefficient kernels
memory reads/writes
pipeline bubbles
MoE token dispatch
imbalanced experts
gradient synchronization
CPU bottlenecks
```

A useful mental model:

```
Higher MFU:
GPU is doing big, dense, Tensor Core-friendly matrix math.

Lower MFU:
GPU is waiting, communicating, moving memory, launching tiny kernels, or handling imbalance.
```

For dense LLM training, the biggest MFU levers are usually **batch/sequence shape, optimized attention, GEMM efficiency, precision, and communication overlap**. For MoE training, add **routing balance, all-to-all efficiency, and expert batch size** as first-class MFU drivers.

## FP8 / BF16 / FP16 / FP4
**Number formats** used for neural network computation

|Format|Meaning|Common use|MFU effect|
|---|---|---|---|
|**FP32**|32-bit floating point|Older/default high precision|Accurate but slow and memory-heavy|
|**FP16**|16-bit float|Training/inference on older Tensor Core stacks|Faster than FP32, lower memory|
|**BF16**|16-bit “brain float”|Modern training default|Similar memory to FP16, usually more stable|
|**FP8**|8-bit float|H100/H200/B200-era training/inference|Much higher theoretical FLOP/s, less memory traffic|
|**FP4**|4-bit float|Blackwell-era inference / some training paths|Very high theoretical throughput, harder numerically|
Lower precision HELPS MFU because it lets Tensor Cores do more math per sec and reduces memory bandwidth pressure
But denominator is also higher, so it can still lead to lower MFU for FP8 peak than BF16 unless your software stack usually uses FP8 efficiently
```
Same workload:
- 500 TFLOP/s useful compute on BF16 peak of 1,000 TFLOP/s = 50% MFU
- 500 TFLOP/s useful compute on FP8 peak of 2,000 TFLOP/s = 25% MFU
```

## FlashAttention
optimized attention algorithm. Instead of materializing huge attention matrices in GPU memory, it tiles the computation and keeps more work in fast on-chip memory.
Attention normally has a lot of memory movement:
```
QK^T -> attention matrix -> softmax -> multiply by V
```
FlashAttention reduces expensive HBM memory reads/writes, so the GPU spends more time doing math and less time moving data. That usually improves MFU, especially for long sequence lengths.

**MFU effect:** increases MFU by making attention more compute-efficient and memory-efficient.

## Fused ops

A **fused op** combines several small operations into one GPU kernel.
Without fusion:
```
kernel 1: add bias
kernel 2: activation
kernel 3: dropout
kernel 4: residual add
kernel 5: layer norm
```
With fusion:
```
one larger kernel does several of those together
```

Every separate GPU kernel launch has overhead, and writing intermediate tensors to memory is expensive. Fusion reduces kernel launch overhead and memory traffic.

**MFU effect:** usually improves MFU, especially when the model has many small elementwise operations.

## Optimized GEMMs

**GEMM** means general matrix multiplication. Transformers are mostly GEMMs:
```
XWq, XWk, XWv
MLP up-projection
MLP down-projection
output projection
```

Optimized GEMMs use Tensor Cores well, choose good tiling, align dimensions, and avoid weird shapes that underutilize the GPU.

Bad GEMM shapes:
```
small batch
short sequence
awkward hidden size
small expert batch in MoE
```

Good GEMM shapes:
```
large enough matrices
aligned dimensions
batched operations
Tensor Core-friendly sizes
```

**MFU effect:** one of the biggest drivers. If GEMMs are large and well-shaped, MFU rises. If GEMMs are tiny or oddly shaped, MFU falls.

## Compiler / runtime choices

This includes systems like PyTorch eager mode, `torch.compile`, XLA, TensorRT, Triton kernels, CUDA graphs, NCCL settings, and vendor libraries.

The compiler/runtime decides things like:

```
Can ops be fused?
Are kernels optimized?
Are memory copies avoided?
Can communication overlap with compute?
Are Tensor Cores used?
Are graph launches captured efficiently?
```

A poor runtime may launch many small kernels and fail to overlap communication. A good one can fuse ops, schedule kernels better, and reduce overhead.

**MFU effect:** can significantly improve or hurt MFU, especially at scale.

## Tensor parallelism
**Tensor parallelism** splits a single layer’s tensors across multiple GPUs.
Example: a huge matrix multiply is split across GPUs:
```
GPU 0 handles part of W
GPU 1 handles part of W
GPU 2 handles part of W
GPU 3 handles part of W
```
This lets you train models that do not fit on one GPU. But GPUs must communicate partial results, often using collectives like all-reduce or all-gather.

**MFU effect:**
- Helps when it enables larger efficient GEMMs.
- Hurts when communication overhead is high.
- Works best with fast intra-node links like NVLink.

## Pipeline parallelism
**Pipeline parallelism** splits model layers across GPUs.
Example:
```
GPU 0: layers 1-10
GPU 1: layers 11-20
GPU 2: layers 21-30
GPU 3: layers 31-40
```

Microbatches flow through the pipeline. The problem is **pipeline bubbles**: at the start and end of each step, some GPUs are idle.

**MFU effect:**
- Helps fit very deep models.
- Hurts MFU if pipeline bubbles are large.
- Better with more microbatches and balanced layer partitioning.

## All-reduce

**All-reduce** is a distributed communication operation where all GPUs combine values and each GPU receives the final result.

Common use: gradient synchronization in data parallel training.

```
GPU 0 gradient \
GPU 1 gradient  -> summed/averaged gradient -> all GPUs receive same result
GPU 2 gradient /
GPU 3 gradient
```

**MFU effect:** lowers MFU if GPUs wait for gradient communication. Good systems overlap all-reduce with backprop compute to reduce the penalty.

## All-gather
**All-gather** collects pieces of a tensor from multiple GPUs and gives every GPU the full tensor.

Example:
```
GPU 0 has shard AGPU 1 has shard BGPU 2 has shard CGPU 3 has shard DAfter all-gather:Every GPU has A+B+C+D
```

Common in tensor parallelism, sequence parallelism, and sharded training.

**MFU effect:** can hurt MFU because it moves lots of data. It is less painful when overlapped with compute or kept within fast NVLink-connected GPUs.

## MoE / MoAE routing
MoE routing: Mixture of Experts routing
- Expert: a sub-network inside a larger model
- each expert is like a specialized mini-model inside the full model
MoE models use a router/gating network to send each token to one or a few expert subnetworks instead of running every token through the full dense model. PyTorch’s MoE training guide describes this as computing scores for token-expert pairs, routing tokens to top-scoring experts, then using all-to-all communication to dispatch tokens to the devices that host those experts.

Example:
```
Token A -> expert 3 and expert 7
Token B -> expert 1 and expert 3
Token C -> expert 12 and expert 4
```

MoE can reduce active FLOPs per token while increasing total model capacity. But routing creates overhead:

```
router computation
token sorting/dispatch
all-to-all communication
load imbalance
small per-expert batches
expert output combine
```

**MFU effect:**

- Can improve cost efficiency because fewer parameters are active per token.
- Can hurt raw MFU because routing and all-to-all communication are expensive.
- Load imbalance is a major issue: if many tokens route to the same expert, some GPUs are overloaded while others wait.
- Small expert batches create inefficient GEMMs.

For MoE, reported MFU can also be tricky because total parameters and active parameters differ; some work notes that naive MFU/MBU accounting can overestimate or misrepresent MoE efficiency if routing and active expert selection are not handled carefully.

## InfiniBand / RoCE / NVLink fabric
These are communication technologies that connect GPUs and nodes.

| Fabric         | Where used                        | Meaning                             |
| -------------- | --------------------------------- | ----------------------------------- |
| **NVLink**     | Usually within a node, GPU-to-GPU | Very fast direct GPU interconnect   |
| **InfiniBand** | Across nodes                      | High-performance cluster networking |
| **RoCE**       | Across nodes over Ethernet        | RDMA over Converged Ethernet        |
| **NVSwitch**   | Within large GPU systems          | Switch fabric connecting many GPUs  |

Training large models requires constant communication:
```
gradients
activations
tensor-parallel shards
expert-routed tokens
optimizer states
```

Fast fabric improves MFU because GPUs spend less time waiting for communication. NVIDIA’s recent MoE communication work specifically calls out NVLink, InfiniBand, Spectrum-X Ethernet/RDMA, and related technologies as key to optimizing all-to-all communication for hyperscale MoE models.

**MFU effect:** huge for multi-GPU and multi-node training. Weak networking can make expensive GPUs sit idle.

## Dataloaders

**Dataloaders** prepare and feed training data to the GPUs.
They may handle:
```
reading files
decompression
tokenization
packing sequences
shuffling
batching
prefetching
moving tensors to GPU
```

If the dataloader is slow, GPUs wait.

Bad situation:

```
GPU finishes step
GPU waits for next batch
GPU idle
MFU drops
```

Good situation:

```
CPU workers prepare next batch while GPU trains current batch
data is prefetched
GPU rarely waits
MFU improves
```

**MFU effect:** slow dataloaders can crush MFU even if the model code is perfect.

## Activation checkpointing / recomputation
During training, the model normally stores intermediate activations from the forward pass so backprop can use them later. Activations can consume huge memory.

**Activation checkpointing** saves memory by storing only some activations and recomputing the missing ones during backward pass.

Without checkpointing:

```
forward: compute and store many activations
backward: reuse stored activations
```

With checkpointing:
```
forward: store fewer activations
backward: recompute some forward activations
```

**MFU effect is nuanced:**
- It adds extra compute, so each step may take longer.
- But it allows larger batch sizes, longer sequences, or larger models.
- Larger batches and sequences may improve Tensor Core utilization.
- Depending on how MFU is calculated, recomputation may or may not count as “useful model FLOPs.”

Practical result: checkpointing can reduce per-step speed but enable a configuration with better overall throughput or better memory fit.

## Data parallelism
**Data parallelism** gives each GPU a copy of the model and a different slice of the batch.

```
GPU 0: batch samples 0-31
GPU 1: batch samples 32-63
GPU 2: batch samples 64-95
GPU 3: batch samples 96-127
```

After backprop, GPUs synchronize gradients using all-reduce.

**MFU effect:**
- Simple and efficient when the model fits on each GPU.
- MFU is high if batch size per GPU is large enough.
- MFU drops if gradient all-reduce dominates or per-GPU batch is too small.

## Expert parallelism

**Expert parallelism** is used for MoE models. Different experts live on different GPUs.

```
GPU 0: experts 0, 1
GPU 1: experts 2, 3
GPU 2: experts 4, 5
GPU 3: experts 6, 7
```

Tokens are routed to the GPUs that own their selected experts. This often requires all-to-all communication; PyTorch’s MoE guide describes the all-to-all dispatch step after token-to-expert assignment.

**MFU effect:**
- Enables huge sparse models.
- Can hurt MFU through all-to-all communication, token imbalance, and small expert GEMMs.
- Works best when routing is balanced and the network fabric is very fast.

## ZeRO / FSDP

**ZeRO** and **FSDP** are sharding strategies that reduce memory use by splitting model states across GPUs.

A normal data-parallel GPU may store:

```
full parameters
full gradients
full optimizer states
```

ZeRO/FSDP shard these across GPUs:

```
GPU 0: shard A
GPU 1: shard B
GPU 2: shard C
GPU 3: shard D
```

FSDP means **Fully Sharded Data Parallel**. ZeRO has stages:

|Method|What gets sharded|
|---|---|
|**ZeRO-1**|optimizer states|
|**ZeRO-2**|optimizer states + gradients|
|**ZeRO-3 / FSDP**|optimizer states + gradients + parameters|

**MFU effect:**
- Helps fit larger models and larger batches.
- Adds communication because parameters or gradients must be gathered/reduced at the right time.
- Can reduce MFU if communication is not overlapped well.
- Can improve overall training efficiency by avoiding CPU offload or tiny batch sizes.
