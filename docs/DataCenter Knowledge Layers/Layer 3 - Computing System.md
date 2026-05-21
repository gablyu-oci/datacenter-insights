# Main Takeaways

Related layers: [[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Four demand types for AI:|demand workloads]], [[Layer 2 - Computing product#Computing Product|compute products]], [[Layer 4 - Physical#Module 6: Physical Metrics / Unit Economics Bridge|physical constraints]], [[Layer 5 - Capital and timeline#Module 2: Revenue & Utilization|utilization economics]]

AI compute 不是单个 GPU，而是一个 **cluster-level system**。有效算力由 accelerator、HBM、server/rack、network、storage、software stack 共同决定
```
Useful compute
= theoretical compute
× memory efficiency
× network efficiency
× storage throughput
× software/runtime efficiency
× system stability
```

## Model FLOPs Utilization
Model FLOPs Utilization (MFU) measures how much of the theoretical accelerator compute is converted into useful model computation. It is a practical bridge between chip specs and delivered training throughput: low MFU means GPUs are waiting on memory, communication, storage, software overhead, or instability.

## 1. Training 和 inference 是两种不同 workload
> **Training 把数据和算力转成模型；inference 把模型转成 [[Layer 2 - Computing product#2.1 Token-based API|token / API revenue]]**

| Workload  | 目标                  | 核心瓶颈                                                                       | 商业含义                           |
| --------- | ------------------- | -------------------------------------------------------------------------- | ------------------------------ |
| Training  | 更新模型参数              | GPU compute、[[Layer 3 - Computing System#High Bandwidth Memory|HBM]]、GPU-GPU communication、checkpoint、storage、cluster stability | 拉动大规模 GPU cluster [[Layer 5 - Capital and timeline#Module 1: Capex & Financing|Capex]]        |
| Inference | 生成 token / response | memory capacity、memory bandwidth、[[Layer 3 - Computing System#11. KV cache 是推理系统的关键资源|KV cache]]、batching、latency、availability    | 决定 token/API 收入、[[Layer 5 - Capital and timeline#Cost/token|成本/token]]、长期[[Layer 5 - Capital and timeline#2. Utilization is the core of the economics|利用率]] |
## 2. AI 芯片价值不只是 FLOPS

AI accelerator 的价值来自：

```
FLOPS
+ HBM capacity
+ HBM bandwidth
+ interconnect
+ power efficiency
+ software ecosystem
```

HBM 是核心变量：

```
HBM capacity:
决定能跑多大模型、多长上下文、多大 batch

HBM bandwidth:
决定 GPU 能否持续被数据喂饱
```

## 3. CPU / GPU / TPU 的差异

|Processor|核心特点|适合场景|
|---|---|---|
|CPU|通用、灵活、控制逻辑强|I/O、pre/post-processing、小模型、复杂控制流|
|GPU|大规模并行、生态成熟|训练、推理、通用 AI workloads|
|TPU / ASIC|专用矩阵计算、能效高|大规模稳定矩阵计算、特定 ML workload|

本质差异：
```
CPU = flexibility
GPU = parallel acceleration
TPU / ASIC = specialized efficiency
```

## 4. 基础设施正在从 server-level 走向 rack-scale

GB200 NVL72 代表的趋势：

```
GPU card / GPU server
→ rack-scale AI system
→ cluster-scale AI factory
```

[[Layer 3 - Computing System#Module 3：Server / Rack|Rack-scale system]] 把以下部分一起设计：

- GPU
- CPU
- [[Layer 3 - Computing System#High Bandwidth Memory|HBM]]
- NVLink / NVSwitch
- [[Layer 3 - Computing System#Power shelf|power shelf]]
- [[Layer 4 - Physical#Module 2: Cooling / Thermal System|liquid cooling]]
- management software

核心含义：
> AI infrastructure 不再只是服务器堆叠，而是整柜、整集群协同设计。
## 5. Network 是 AI cluster 的核心瓶颈
大模型训练需要 GPU 之间频繁通信。网络差会让昂贵 GPU 等待。
```
Scale-up:
GPU / server / rack 内部互联
Example: NVLink, NVSwitch

Scale-out:
server / rack 之间互联
Example: InfiniBand, RoCE Ethernet, Spectrum-X

Scale-across:
跨楼宇 / 跨园区 / 跨地域互联
Example: DCI / WAN
```

核心含义：
```
Scale-up 让多个 GPU 像一个更大的计算单元。
Scale-out 让多个 rack 组成大规模 AI cluster。
```

## 6. InfiniBand vs Ethernet

| Network         | 优势                         | 挑战                                            |
| --------------- | -------------------------- | --------------------------------------------- |
| InfiniBand      | 低延迟、高带宽、RDMA 原生强、HPC/AI 成熟 | 更专用，运维生态相对封闭                                  |
| Ethernet / RoCE | 数据中心默认网络、生态大、多租户和运维友好      | 需要解决拥塞、lossless tuning、collective performance |

产业判断：
```
InfiniBand 仍强在高性能 AI training
Ethernet 正因统一运维、多租户和数据中心生态而变得更重要
```

## 7. Distributed training 的效率取决于 communication
常见并行方式和通信模式：

|Parallelism|拆什么|常见通信|
|---|---|---|
|Data parallelism|batch|all-reduce|
|Tensor parallelism|tensor / matrix|all-gather、reduce-scatter、all-reduce|
|Pipeline parallelism|layers|send / recv|
|Expert parallelism|MoE experts / tokens|all-to-all|
|ZeRO / FSDP|parameters、gradients、optimizer states|all-gather、reduce-scatter|

核心含义：
> 模型越大，并行方式越复杂，communication 越可能成为系统瓶颈

## 8. Storage 是 data movement layer

> GPU 等数据就是浪费钱。AI cluster 不只是 compute cluster，也是 data movement system

|Workload|Storage 关注点|
|---|---|
|Training|dataset、dataloader、checkpoint、model weights、distributed FS、object storage、local NVMe|
|Inference|model weights、RAG documents、vector index、logs、agent state、model versioning|

核心含义：

```
Training storage = 喂饱 GPU + 保存训练进度
Inference storage = 快速加载模型 + 支持检索、状态、日志、回滚
```

See also: [[Layer 3 - Computing System#Training storage|Training storage]], [[Layer 3 - Computing System#Inference storage|Inference storage]].
## 9. Software stack 决定 useful compute

相同 GPU，在不同 software stack 下，实际产出可能差很多。
关键软件层：
```
CUDA / ROCm
PyTorch / TensorFlow / JAX
NCCL / RCCL
FSDP / ZeRO
Triton / TensorRT-LLM
vLLM / PagedAttention
Triton Inference Server
Kubernetes / Slurm
Ray
observability stack
```

核心含义：
> 软件栈决定硬件[[Layer 5 - Capital and timeline#Physical GPU utilization|利用率]]、通信效率、显存效率、推理吞吐和系统稳定性。
## 10. Inference 的核心是 latency、throughput、KV cache、batching
推理服务流程：
```
request
→ tokenization
→ queueing
→ prefill
→ KV cache allocation
→ decode token by token
→ streaming response
```

关键指标：
```
TTFT: time to first token
TPOT: time per output token
tokens/sec
cost/token
KV cache usage
batch utilization
latency p50/p95/p99
```

See also: [[Layer 5 - Capital and timeline#Cost/token|cost/token]], [[Layer 3 - Computing System#11. KV cache 是推理系统的关键资源|KV cache]].

核心含义：
> 推理经济性取决于如何在 latency 和 throughput 之间平衡

## 11. KV cache 是推理系统的关键资源

KV cache 会把推理瓶颈从纯计算问题变成显存和调度问题。
影响因素：

```
context length
batch size
concurrent users
model size
number of layers
precision
```

产业含义：

```
Long context、multi-turn chat、agent workload 会增加 KV cache pressure。
KV cache management 直接影响并发、显存利用率、latency 和 cost/token。
```
## 12. Scheduler 和 observability 是生产化基础
不同 scheduler 管不同层：
```
Kubernetes / Slurm:
job / pod 放在哪些机器

Ray:
Python task / actor 放在哪些 worker

Training scheduler:
microbatch、pipeline、communication overlap、checkpoint timing

Inference scheduler:
prefill / decode 排队、batching、KV cache 分配、priority
```

关键 observability 指标：

```
GPU utilization
GPU memory used
tokens/sec
requests/sec
TTFT / TPOT
latency p50/p95/p99
KV cache usage
queue length
network throughput
disk throughput
checkpoint duration
error rate
```

See also: [[Layer 5 - Capital and timeline#Physical GPU utilization|GPU utilization]].

核心含义：
> 没有 scheduler 和 observability，就无法优化利用率、成本/token、SLA 和大规模稳定性。



------
# Module 1: Workload
>Training 是把数据和算力转成模型；Inference 是把模型转成 token / API revenue

Training:
- 目标：更新模型参数
- 特点：大规模并行、长时间运行、通信密集、checkpoint 密集
- 关键瓶颈：GPU compute、HBM、GPU-GPU communication、storage throughput、cluster stability

Inference:
- 目标：用模型生成输出
- 特点：低延迟、高并发、成本/token、KV cache、batching、serving efficiency
- 关键瓶颈：memory capacity、memory bandwidth、decoding speed、batching、latency、availability

## CPU vs GPU vs TPU
CPU:
- von Neumann Architecture
- Flexibility: you can load any kind of software on a CPU for many different types of applications
- cpu loads values from memory, performs a calculation on the values and stores the result back in memory for every calculation
- von Neumann bottleneck: memory access is slow when compared ot the calculation speed and can limit the total throughput of CPUs

GPU:
- thousands of ALUs in a single processor, meaning you can execute thousands of multiplications and additions simultaneously
- works well on apps with massive parallelism such as matrix operations in neural network
- Still general purpose, so for every calculation, a GPU must access registers or shared memory to read operands and store the intermediate calculation results

TPU:
- Tensor Processing Units (TPUs) are Google's custom-developed, application-specific integrated circuits (ASICs) used to accelerate machine learning workloads
- TPUs can't run word processors etc, only specialized as a matrix processor for neural network workloads
	- Systolic array architecture: thousands of multiply-accumulators that are directly connected to each other to form a large physical matrix
	- Cloud TPU v3 contains 2 systolic arrays of 128x128 ALUs on a single processor
- Cloud TPU is a web service that makes TPUs available as scalable computing resources on Google Cloud
- How it works:
	- TPU host streams data into an infeed queue, and TPU loads data from the infeed queue and stores them in HBM. when computation is completed, the TPU loads the results into the outfeed queue. The TPU host then reads the results from the outfeed queue and stores them in the host's memory
	- TPU loads parameters from HBM into the Matrix Multiplication Unit (MXU) to perform matrix operations
	- multiplication result is passed to the next multiply-accumulator
	- The output is the summation of all multiplication results between the data and parameters. No memory access is required during the matrix multiplication process.
- TPU VM architecture![[Pasted image 20260516222308.png]]
 CPUs
- Quick prototyping that requires maximum flexibility
- Simple models that don't take long to train
- Small models with small, effective batch sizes
- Models that contain many [custom TensorFlow operations written in C++](https://www.tensorflow.org/guide/create_op)
- Models that are limited by available I/O or the networking bandwidth of the host system
GPUs
- Models with a significant number of custom PyTorch/JAX operations that must run at least partially on CPUs
- Models with TensorFlow ops that are not available on Cloud TPU (see the list of [available TensorFlow ops](https://docs.cloud.google.com/tpu/docs/tensorflow-ops))
- Medium-to-large models with larger effective batch sizes
TPUs
- Models dominated by matrix computations
- Models with no custom PyTorch/JAX operations inside the main training loop
- Models that train for weeks or months
- Large models with large effective batch sizes
- Models with ultra-large embeddings common in advanced ranking and recommendation workloads

## NVIDIA - AI inference platform / Triton Inference Server overview
Run inference on trained machine learning or deep learning models from any framework on any processor—GPU, CPU, or other—with NVIDIA Triton™ Inference Server
```
Application
   ↓ HTTP/gRPC request
Triton Inference Server
   ↓
Model: PyTorch / TensorRT / ONNX / TensorFlow / Python / XGBoost / etc.
   ↓
GPU or CPU execution
   ↓
Response back to application
```

Important Triton features

|Feature|Meaning|
|---|---|
|**HTTP/gRPC APIs**|Apps can call models over network APIs|
|**Multiple frameworks**|Can serve models from PyTorch, ONNX, TensorRT, etc.|
|**Dynamic batching**|Combines small requests into bigger batches to use the GPU better|
|**Concurrent model execution**|Runs multiple models at the same time|
|**Ensemble models**|Chains models together into a pipeline|
|**Metrics/tracing**|Helps monitor latency, throughput, and errors|
|**CPU/GPU support**|Can run on NVIDIA GPUs, CPUs, and some other accelerators|

# Module 2: Chip/Accelerator
>AI 芯片的价值不是单纯 FLOPS，而是 FLOPS + HBM + interconnect + software ecosystem

## NVIDIA Blackwell Architecture
Features:
- 208 billion transistors
- 10TB/s chip to chip interconnect in a unified single GPU
- 2nd generation transformer engine
- NVIDIA Confidential Computing with hardware-based security
- 5th generation NVLink: up to 576 GPUs for multi-trillion parameter AI models; NVLink Switch Chip enables 130TB/s of GPU bandwidth in one 72 GPU NVLink domain
- Decompression Engine: DB including Apache Spark access massive amounts of memory in the NVIDIA Grace™ CPU over a high-speed link—900 gigabytes per second (GB/s) of bidirectional bandwidth

## Nvidia H100 Tensor Core GPU
Features:
- 4th generation Tensor Cores
- Transformer Engine with FP8 precision
- 4th generation NVLink (900 gb/s of gpu to gpu interconnect)
	- NVLink connects GPU - GPU, very fast direct GPU communication
- NDR Quantum-2 InfiniBand networking
	- InfiniBand connects server - server, GPU cluster - GPU cluster
- PCIe Gen5
	- PCIE connects CPU - GPU, SSDs, NICs, accelerators
	- GPU is plugged into the system through PCIe
- Nvidia Magnum IO software

## High Bandwidth Memory
HBM
- the GPU chip does the computation, and the HBM stores data close to it
memory capacity vs memory bandwidth
- capacity determines whether the GPU can hold:
	- model weights
	- KV cache
	- activations
	- input batch data
	- intermediate results
	> More memory capacity = can run larger models, longer context, or bigger batches.
- Memory bandwidth means how quickly the GPU can read from and write to its memory

## TDP / power efficiency
Thermal Design Power
- the amount of heat/power a system is designed to handle under sustained workload
- affects:
	- [[Layer 4 - Physical#kW per rack|rack power]]
	- [[Layer 4 - Physical#Module 2: Cooling / Thermal System|cooling]]
	- [[Layer 4 - Physical#Electricity cost|electricity cost]]
	- server density
	- power supply design
	- thermal limits
Power efficiency
- how much useful work you get per watt
	- tokens per second per watt
	- TFLOPS per watt
	- images per second per watt
	- queries per second per watt

# Module 3：Server / Rack
>AI infrastructure 正在从 server-level design 走向 rack-scale / cluster-scale design



Big picture:
```
Rack-scale AI system
├─ Compute: GPUs, CPUs, HBM
├─ Interconnect: NVLink / NVSwitch inside rack
├─ Networking: NICs or DPUs to talk outside rack
├─ Power: power shelves, bus bars, PSUs
├─ Cooling: liquid cooling interface, manifolds, CDU/facility water
└─ Management: switches, controllers, monitoring software
```

```
                    External cluster network
                             │
                       NICs / DPUs
                             │
┌──────────────────── AI rack-scale system ────────────────────┐
│                                                              │
│  Management switches                                         │
│  Power shelves ── bus bars ── compute trays                  │
│                                                              │
│  Compute trays:                                              │
│    Grace CPUs + Blackwell GPUs + HBM                         │
│                                                              │
│  NVLink / NVSwitch fabric:                                   │
│    fast GPU-to-GPU communication inside the rack              │
│                                                              │
│  Liquid cooling:                                             │
│    cold plates → manifolds → liquid cooling interface         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                             │
                     Facility cooling / CDU
```
## NVIDIA GB200 NVL72
the **rack-scale hardware architecture/configuration**
- connects in a rack-scale, liquid-cooled design:
	- 36 grace cpus
	- 72 Blackwell GPUs
	- 72 GPU NVLink 
- GB200 Grace Blackwell Superchip: 1 Grace CPU + 2 Blackwell Tensor Core GPUs interconnected via 5th gen NVLink
	- Grace CPU = coordinator + general-purpose work (prepares work, manages memory, networking, scheduling, handles orchestration, postprocessing, I/O)
	- Blackwell GPUs = heavy AI math (run matrix multiplications, attention, neural network layers)
- All 72 GPUs are interconnected through an NVLink switch fabric, functioning as a single, unified accelerator.
- A massive shared memory pool of up to 1.44 TB per node

Performance:
- Scale and Speed: 30x speedup for AI inference and is 4x faster at training massive foundation models compared to the previous-generation NVIDIA H100
- Bandwidth: Features a total NVLink switch fabric bandwidth of 130 TB/s, boasting 1.8 TB/s bidirectional bandwidth per GPU
- Advanced Networking: Integrates with NVIDIA Quantum-X800 InfiniBand and Spectrum-X Ethernet for scalable cluster communication

Design: 
- **Direct Liquid Cooling:** Replaces traditional air cooling with [[Layer 4 - Physical#Module 2: Cooling / Thermal System|direct liquid cooling]] (DLC) technology for exceptional energy density.
- **Data Center Scale:** A fully configured rack weighs nearly two tons, contains over 1.2 million components, and typically requires about [[Layer 4 - Physical#kW per rack|120 kW of power]].
- **Software Ecosystem:** Fully supports NVIDIA AI Enterprise and Mission Control software suites for seamless orchestration.

## NVIDIA DGX GB200
NVIDIA’s **DGX-branded system/product** built from that GB200 NVL72-style rack-scale architecture, with NVIDIA’s DGX software, management, networking, support, and data-center integration around it.

DGX GB200 rack
= 36 GB200 Grace Blackwell Superchips
= 36 Grace CPUs
= 72 Blackwell GPUs
= connected together with NVLink
= liquid-cooled rack-scale AI system

## DPU
Data Processing Unit
offload work from the CPU, such as:
```
network packet processing
storage virtualization
security / encryption
firewalling
telemetry
isolation between tenants
RDMA / data movement support
```

## GPU Servers, HGX


HGX: NVIDIA’s **baseboard/platform design** for GPU servers.
includes: 
- multiple GPUs
- NVLink/NVSwitch connectivity
- GPU baseboard
- high-speed GPU-to-GPU fabric
Then vendors such as Dell, HPE, Supermicro, Lenovo, etc. build complete servers around it.

## Power shelf
Rack-level power module
```
Facility power
   ↓
Rack power shelf
   ↓
Bus bar / power distribution
   ↓
Compute trays, switch trays, management hardware
```

## Liquid cooling interface
A **liquid cooling interface** is where the rack’s internal cooling loop connects to the [[Layer 4 - Physical#Module 2: Cooling / Thermal System|facility cooling system]].


# Module 4：Network
>AI training 不是 embarrassingly parallel。GPU 之间需要频繁通信，网络差会让昂贵 GPU 等待

|Term|Meaning|Example|
|---|---|---|
|**Scale-up**|Make one system bigger/tighter|More GPUs inside one server/rack, more HBM, faster NVLink|
|**Scale-out**|Add more systems and connect them|More GPU servers/racks connected by InfiniBand/Ethernet|

connection:
```
Inside GPU:
  Tensor Cores do math
  HBM stores hot model data

Inside one server / NVL rack:
  NVLink / NVSwitch connects GPUs tightly

Between servers / racks:
  InfiniBand or Spectrum-X Ethernet connects systems
```
## NVIDIA Spectrum-X
an advanced, **Ethernet-based networking platform** purpose-built to accelerate hyperscale generative AI workloads and data center AI clouds
Spectrum-X overcomes the traditional latency and congestion limitations of standard Ethernet in massively parallel computing environments. It brings together several integrated technologies:
- Spectrum Ethernet Switches (SN5000/Spectrum-4)
	- High-performance, purpose-built switches that ensure high effective bandwidth.
	- tuned specifically for scale-out to massive, AI-driven factories
- NVIDIA SuperNICs (BlueField-3 & ConnectX-8):
	- A new class of network accelerators that bypass host CPUs to optimize peak AI workload efficiency and network-intensive computations
- AI-Driven Telemetry
	- Utilizes the [NVIDIA NetQ Platform](https://developer.nvidia.com/blog/next-generation-ai-factory-telemetry-with-nvidia-spectrum-x-ethernet/) and specialized software to implement advanced congestion control and adaptive routing, keeping clusters predictable.

Connect things like:
```
GPU server ↔ Ethernet AI fabric ↔ GPU server
or
GB200 / DGX rack ↔ Ethernet AI fabric ↔ GB200 / DGX rack
or
AI compute rack ↔ storage / front-end / other AI racks
```

## Arista AI Networking whitepaper
Traditional solutions for building HPC clusters:
- relied upon InfiniBand
- introduces network silos as the traditional data center has historically been built around Ethernet
- Customers will need gateways to connect these network silos, which adds complexity
- disparate operational skill sets for back-end AI vs. front-end AI networks, and operational silos between AI accelerator processing units (XPUs), general compute (CPUs), networking, and storage
>Frontend network = users/apps coming in and responses going out
>Backend network  = internal machine-to-machine traffic

The AI Center:
- Ethernet unifying all elements of the complete system with open standards at every layer
- unifies the entire front- and back-end ecosystem to deliver scale-out networking for AI with optimized performance and operations alike
- enables coordinated visibility, management, and control of AI workloads, compute, networks, and storage along with existing data center workloads and systems
![[Pasted image 20260518115937.png]]
```
Old world:
  AI training backend = InfiniBand silo
  Front-end data center = Ethernet silo

New world:
  AI backend + front-end data center both use Ethernet-based fabrics
  AI racks/servers connect through AI NICs to AI leaf/spine switches
  The data center uses compute/storage leaf switches and a universal spine
```

<u>InfiniBand vs Ethernet</u>
- InfiniBand = specialized high-performance AI/HPC network
- Ethernet   = universal data-center network, now being optimized for AI

|Feature|InfiniBand|Ethernet|
|---|---|---|
|Main use|HPC, AI training, supercomputing|General data center networking|
|Latency|Usually very low|Traditionally higher, but improving|
|RDMA|Native strength|Uses RoCE for RDMA over Ethernet|
|Congestion behavior|Designed for lossless/high-performance fabrics|Needs careful tuning for AI workloads|
|Operations|More specialized|More familiar to data center/network teams|
|Ecosystem|HPC/AI focused|Huge general-purpose ecosystem|
|AI scale-out|Very strong|Increasingly common with Spectrum-X / RoCE|
<u> leaf-spine network topology </u>
Servers connect to leaf switches.
Leaf switches connect to spine switches.
Spine switches connect the leaves together.

Leaf switch: the first network switch that servers connect to. It connects directly to GPU servers, AI racks, NICs/DPUs/SueprNICs
Spine switch: connects many leaf switches together. The high-level switching layer that lets GPU servers/racks attached to different leaves communicate

Traffic flow: 
- same leaf:
```
GPU server A
  ↓
AI leaf
  ↓
GPU server B
```
- Different leaves:
```
GPU server A
  ↓
AI leaf 1
  ↓
AI spine
  ↓
AI leaf 2
  ↓
GPU server B
```

<u>InfiniBand vs Ethernet</u>
- InfiniBand: specialized high-performance backend fabric
- Ethernet: universal data-center networking fabric

Why not use InfiniBand everywhere?
1. Ethernet is already the default language of data centers. If you made everything InfiniBand, you would still need gateways or separate Ethernet networks to connect to the outside world
	1. load balancers, databases, kubernetes clusters...
2. InfiniBand is more specialized
	1. great for GPU-GPU scale-out training, RDMA, low latency, high bandwidth, HPC collectives
	2. requires more specialized NICs, switches, cabling, drivers, fabric management, operations knowledge, debugging tools
3. Not all traffic needs InfiniBand level performance like web/api traffic, auth, logging...
4. Ethernet is easier to integrate with storage and services
5. Multi-tenant cloud operations are easier with Ethernet
	1. tenant isolation, routing, firewalls, VPC...
6. Cost and supply-chain flexibility

### Scale-out AI Networking
Problem: large-scale Ethernet AI clusters might have 16k servers, each configured with 8XPU accelerators = 131k XPUs interconnected with a network,
Impossible with one single physical rack
So the deployment needs to extend out over a large number of physical racks with a large network radix interconnecting all of the XPUs

Has very high power consumption:
- reduce optic power: linear-drive pluggable optics (LPO)
- shift to liquid cooling for networking infrastructure products

the datasets for training may not fit within the memory of a single XPU
- datasets need to be shared across memory banks spanning multiple XPUs via computational parallelism

### Scale-up Networking
designed to enable shared memory access across multiple XPUs in the same data center rack
- need for massive bandwidth for the XPU interconnects
- ultra low latency, lossless transport, reliable communication between all of the XPUs

![[Pasted image 20260518143822.png]]

Inter-XPU connectivity:
- NVLink
- more open standards-based approach to enable high-speed, shared memory access via inter-XPU communication
	- UALink Consortium
	- Scale Up Ethernet from Broadcom

RoCE = RDMA over Converged Ethernet
- RDMA is associated with InfiniBand
- RoCE lets Ethernet networks support RDMA-like behavior
- 

### Scale Across AI Networking
clusters need to scale across multiple buildings and sites for data center interconnect (DCI) over a WAN, and network design assumptions and requirements need to change

# all-reduce, all-gather, all-to-all

| Operation      | What it does                                                          | Simple meaning                                       |
| -------------- | --------------------------------------------------------------------- | ---------------------------------------------------- |
| **All-reduce** | Combine values from all GPUs, then give final result to all GPUs      | “Everyone contributes, everyone gets the sum/result” |
| **All-gather** | Gather pieces from all GPUs, then give full combined data to all GPUs | “Everyone has one piece, everyone gets all pieces”   |
| **All-to-all** | Every GPU sends different pieces to every other GPU                   | “Everyone sends customized data to everyone else”    |

| 并行方式                       | 拆什么                    | 常见 collective                            |
| -------------------------- | ---------------------- | ---------------------------------------- |
| **Data Parallelism**       | 拆 input batch          | all-reduce                               |
| **Tensor Parallelism**     | 拆模型里的 tensor/矩阵计算      | all-gather / reduce-scatter / all-reduce |
| **Pipeline Parallelism**   | 按 layer 拆模型            | point-to-point send/recv                 |
| **MoE Expert Parallelism** | 按 expert/token 路由拆     | all-to-all                               |
| **ZeRO/FSDP**              | 拆参数、梯度、optimizer state | all-gather / reduce-scatter              |
## optical module and switch ASIC
Switch ASIC vs NIC ASIC

| Chip             | Lives in            | Main job                                             |
| ---------------- | ------------------- | ---------------------------------------------------- |
| **NIC ASIC**     | Server network card | Send/receive network traffic for the server          |
| **Switch ASIC**  | Network switch      | Forward traffic between many ports                   |
| **DPU ASIC/SoC** | SmartNIC/DPU card   | Networking + security/storage/virtualization offload |
Switch ASIC vs NVSwitch

|Term|Connects|Used for|
|---|---|---|
|**Ethernet / InfiniBand switch ASIC**|Servers/racks over network cables|Scale-out networking|
|**NVSwitch**|NVIDIA GPUs over NVLink|Local GPU-to-GPU fabric inside server/rack|
```
Inside rack GPU fabric:
  GPU ↔ NVLink ↔ NVSwitch ↔ NVLink ↔ GPU

Between servers/racks:
  NIC ↔ Ethernet/InfiniBand switch ASIC ↔ NIC
```

# Module 5：Storage / Data Pipeline
>GPU 等数据就是浪费钱。AI cluster 不只是 compute cluster，也是 data movement system

## CoreWeave storage product page / AI storage docs
CoreWeave AI Object Storage
- Serves: large training datasets, model weights, checkpoints
- through an S3-compatible API
- Provides: auth, security policies, read-after-write consistency, versioning, bucket lifecycles
- directly to cpu and gpu nodes or via model serializers such as CoreWeave Tensorizer
- LOTA (Local Object Transport Accelerator): intelligent proxy for CoreWeave AI Object Storage. Installed on every GPU and CPU node to provide a highly efficient, local gateway to CoreWeave AI Object Storage that caches fetched data to reduce load times

Distributed File Storage
- POSIX-compliant shared filesystem that allows multiple GPU Nodes to access the same data simultaneously
- high throughput, low latency, auto data snapshots, async file deletion features
- ideal for apps that require synchronization between pods, such as distributed training

Dedicated VAST Storage
- single-tenant VAST cluster
- Each cluster is physically isolated to a single tenant, with direct access to the VAST Management System (VMS), multi-protocol support (NFS, S3, NVMe/TCP, and SQL), and advanced data services including VAST Catalog, DataBase, DataEngine, and cross-cluster replication
- designed for workloads that need petabyte-scale capacity, full cluster management control, and features such as custom QoS policies, configurable snapshots, and per-tenant encryption keys
>VAST: VAST Data, a company/storage platform that builds high-performance data storage systems.
>A **VAST cluster** is a storage system made of multiple servers working together to provide one big, fast pool of storage
>NVMe: Non-Volatile Memory Express
>- It is a protocol for accessing very fast storage, especially SSDs. 
>- NVMe was designed to take better advantage of flash storage than older protocols like SATA or SAS.

Local Storage
- high-performance temporary storage, caching, and logs
- This **non-persistent local storage** is not intended for long-term data retention.

| Storage type                                                                                           | Persistence | Access pattern                                                                                              | Best for                                                               |
| ------------------------------------------------------------------------------------------------------ | ----------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| [Object Storage](https://docs.coreweave.com/products/storage/object-storage/about)                     | Persistent  | [S3-compatible API](https://docs.coreweave.com/products/storage/object-storage/reference/object-storage-s3) | Datasets, checkpoints, model weights                                   |
| [Distributed File Storage](https://docs.coreweave.com/products/storage/distributed-file-storage/about) | Persistent  | POSIX filesystem                                                                                            | Shared data between Pods, training synchronization                     |
| [Dedicated VAST Storage](https://docs.coreweave.com/products/storage/dedicated-vast)                   | Persistent  | NFS, S3, NVMe/TCP, SQL                                                                                      | Petabyte-scale storage, multi-protocol access, full cluster management |
| [Local Storage](https://docs.coreweave.com/products/storage/local-storage)                             | Ephemeral   | Node-local filesystem                                                                                       | Scratch space, caching, temporary files                                |

## NVIDIA Magnum IO / GPUDirect Storage
[GPUDirect Storage Overview](https://docs.nvidia.com/gpudirect-storage/overview-guide/index.html)
enables a direct data path for direct memory access (DMA) transfers between GPU memory and storage, which avoids a bounce buffer through the CPU.
Using this direct path can relieve system bandwidth bottlenecks and decrease the latency and utilization load on the CPU.

## Training storage
- dataset  
- dataloader 
	- Read, clean, tokenization, image resize/crop/augmentation, shuffle, batching, prefetch, sharding
- checkpoint
	- model weights, optimizer state, learning rate scheduler, step, epoch, random seed/RNG, distributed training, mixed precision scaler
- model weights  
- distributed file system
	- 高吞吐量，适合存储checkpoint
- object storage
	- 容量几乎可以无限扩展，成本低，适合存放大规模数据
	- 不像本地文件那样天然支持低延迟随机读写、文件锁、原子 rename 等操作
- local NVMe
	- 每台训练服务器本地的高速 SSD
	- 比传统SATA SSD快很多，本地 NVMe 直接挂在机器上，延迟低、吞吐高，非常适合做缓存和临时数据
	- 适合缓存dataset shard，临时解压数据，加速dataloader，存放tokenizer cache
	- 每台机器的数据不共享

数据流
```
Object Storage / Distributed FS
          |
          | 读取 dataset shards
          v
Local NVMe cache on each GPU node
          |
          | dataloader 读取、解码、tokenize、batch
          v
GPU memory
          |
          | 训练更新参数
          v
Checkpoint 写回 Distributed FS
          |
          | 归档/复制
          v
Object Storage
```
  
## Inference storage
训练关心大规模持续读写；推理更关心：
- 模型能不能快速加载
- 请求延迟是否稳定
- RAG 检索是否快
- 用户会话状态是否可恢复
- 日志是否完整
- 多副本服务是否一致

**Model weights**: 已经训练好的模型参数。推理服务启动流程：
- 从存储加载模型权重
- 放到 GPU 显存
- 开始接收请求
推理阶段对 model weights 的要求：
- 启动加载要快
- 多个推理副本能并发读取
- 版本管理清晰
- 支持灰度发布和回滚
- 权重文件不能损坏
- 权限控制严格


**RAG documents**: 模型不完全依赖自己记住的知识，而是在回答前先去检索相关文档，再基于文档生成回答。处理流程：
- 原始文档
- 解析文本
- 切 chunk
- 生成 embedding
- 存入 vector index

vector index: 快速做语义检索的索引
- 模型会把文本 chunk 转成 embedding，也就是一个高维向量
	- 比如一段文档可能变成一个 768 维、1536 维或更高维的数字向量。
- 当用户提问时：
1. 把用户问题也转成 embedding
2. 在 vector index 里查找最相似的文档 chunk
3. 把这些 chunk 放进 prompt
4. LLM 基于这些内容回答

logs  

agent state: agent 在多轮任务执行过程中的状态信息
Agent state 需要存储，是因为 agent 可能要：
- 多轮对话
- 任务恢复
- 异步工作流
- 工具调用追踪
- 审计
- 跨服务协调
它常存放在：
- Redis：短期状态、低延迟
- PostgreSQL/MySQL：持久状态
- DynamoDB/Cassandra：高规模 key-value 状态
- 对象存储：长期任务记录
- 专门的 workflow engine：Temporal、Airflow、Step Functions 等

Agent state 和 logs 不一样：

| 概念          | 用途        |
| ----------- | --------- |
| Logs        | 记录发生了什么   |
| Agent state | 决定下一步该做什么 |
## Training vs Inference

|维度|Training storage|Inference storage|
|---|---|---|
|核心目标|喂饱 GPU，保存训练进度|快速响应用户请求|
|数据规模|极大，TB/PB 级|权重大，文档和索引视应用而定|
|主要读写模式|大批量顺序读，周期性大写入|低延迟读取，高并发查询|
|关键数据|dataset、checkpoint、weights|weights、RAG docs、vector index、logs、state|
|性能瓶颈|dataloader、checkpoint 写入、共享 FS 元数据|模型加载、向量检索、状态读写、日志吞吐|
|常用存储|分布式 FS、对象存储、本地 NVMe|对象存储、向量库、数据库、日志系统、本地缓存|
|失败恢复|从 checkpoint 恢复训练|服务重启、状态恢复、模型版本回滚|
# Module 6: Software Stack

>软件栈决定硬件利用率。相同 GPU，在不同 software stack 下，产出的 useful compute 可能差很多

## Training
### PyTorch FSDP: FullyShardedDataParallel
In [DistributedDataParallel](https://pytorch.org/docs/stable/generated/torch.nn.parallel.DistributedDataParallel.html) (DDP) training, each rank owns a model replica and processes a batch of data, finally it uses all-reduce to sync gradients across ranks.
Comparing with DDP, FSDP reduces GPU memory footprint by sharding model parameters, gradients, and optimizer states. It makes it feasible to train models that cannot fit on a single GPU. As shown below in the picture,
- Outside of forward and backward computation, parameters are fully sharded
- Before forward and backward, sharded parameters are all-gathered into unsharded parameters
- Inside backward, local unsharded gradients are reduce-scatterred into sharded gradients
- Optimizer updates sharded parameters with sharded gradients, resulting in sharded optimizer states
![[Pasted image 20260518160923.png]]
FSDP can be considered a decomposition of DDP’s all-reduce into reduce-scatter and all-gather operations
![[Pasted image 20260518161037.png]]


> **What is Optimizer?**
> 1.根型根据当前 weights 做预测
   2.计算 loss：预测错了多少
   3.反向传播 backward：算出每个参数该往哪个方向改，也就是 gradient
   4.optimizer 根据 gradient 更新 model weights
   5.重复很多次
 loss -> gradients -> optimizer -> new model weights 
### DeepSpeed ZeRO: Zero Redundancy Optimizer
不要让每张 GPU 都重复保存同样的训练状态
ZeRO reduces the memory consumption of each GPU by partitioning the various model training states (weights, gradients, and optimizer states) across the available devices (GPUs and CPUs) in the distributed training hardware.
Concretely, ZeRO is being implemented as incremental stages of optimizations, where optimizations in earlier stages are available in the later stages.
- Stage 1 partition optimizer states
- Stage 2 进一步 partition gradients
- Stage 3 进一步 partition model parameters
### Nvidia NCCL: Collective Communications Library
a software library that provides highly optimized, multi-GPU and multi-node communication primitives, such as all-reduce, all-gather, and broadcast
多 GPU 训练时，GPU 之间必须频繁交换数据。
例如：
- DDP 需要同步 gradients
- FSDP 需要 all-gather parameters
- ZeRO 需要 reduce-scatter gradients
- Tensor Parallel 需要在 layer 内交换 activation/partial result
- Pipeline Parallel 需要在 stage 之间传 activation
这些通信如果慢，GPU 就会等待。

## Inference
### vLLM
一个高吞吐、内存高效的 LLM inference / serving engine，解决LLM 推理时 KV cache 太大，batch 做不大（**KV cache memory management**）

#### PagedAttention
传统 serving 系统容易给每个请求预留一大块连续 KV cache memory。问题是 LLM 请求长度不固定
- 如果每个请求都按最大长度预留，就会浪费很多显存
- 如果请求增长时需要重新搬迁连续内存，又会产生 fragmentation 和 copy 开销
PagedAttention 的想法借鉴了操作系统的 **virtual memory / paging**，把 KV cache 分成 block/page，而不是要求每个请求占一整段连续显存

传统方式：
```
Request A KV cache: [---------------- continuous block ----------------]
Request B KV cache: [---------------- continuous block ----------------]
```

PagedAttention：
```
Request A KV cache:
page 7 -> page 12 -> page 3 -> page 45
Request B KV cache:
page 9 -> page 10 -> page 20
```

逻辑上每个请求还是一串 token 的 KV cache；  
物理上可以分散在不同 GPU memory blocks 里。

这就像操作系统里，一个进程看到的是连续虚拟内存，但真实物理页可以散落在不同地方。

### Nvidia Triton Inference Server
生产级 inference serving 平台，解决模型怎么作为生产服务部署、管理、扩缩容
- 模型如何加载
- 请求如何进入
- 如何 batch
- 如何暴露 HTTP/gRPC endpoint
- 如何监控 latency / throughput
- 如何同时部署多个模型
- 如何管理模型版本
- 如何支持不同框架
- 如何做 ensemble pipeline
Triton 通常有一个 model repository，每个模型有模型文件，config，version directory，backend配置。Triton 启动后，会从 repository 里加载模型，然后对外提供服务
```
Client
  |
  | HTTP/gRPC request
  v
Triton Inference Server
  |
  | batching / routing / backend
  v
Model backend
  |
  v
GPU / CPU / accelerator
```

### TensorRT-LLM
把 LLM 转成 NVIDIA GPU 上更高效的执行形式，并用专门优化的 runtime 跑起来
- 构建 TensorRT engine
- 使用 fused kernels
- 优化 attention
- 支持 quantization
- 支持 tensor parallel / pipeline parallel
- 支持 paged KV cache / inflight batching 等 serving 优化
- 提供 runtime 执行生成过程
- 和 Triton / NVIDIA Dynamo 等生态集成

## Other Softwares
### GPU：CUDA, ROCm
CUDA:
- CUDA runtime
- CUDA driver
- CUDA compiler
- CUDA kernels
- CUDA libraries
AI Frameworks like PyTorch, TensorFlow call CUDA libraries:
- cuBLAS矩阵乘法
- cuDNN 深度学习算子
- NCCL多 GPU 通信
- CUDA Graphs 减少 kernel launch overhead
- TensorRT 推理优化

ROCm 包括：
- HIP  
- rocBLAS  
- MIOpen  
- RCCL  
- ROCm runtime

### Cluster Resources：Kubernetes, Slurm
Slurm: Slurm 是 HPC 集群的作业调度系统

| 维度   | Kubernetes           | Slurm                    |
| ---- | -------------------- | ------------------------ |
| 主要场景 | 长期在线服务               | 批处理 / HPC / training job |
| 工作单位 | Pod / Service        | Job / Allocation         |
| 典型任务 | inference server、微服务 | 多节点训练、科学计算               |
| 调度风格 | 服务编排                 | 队列式资源分配                  |
| 生命周期 | 长期运行                 | 任务跑完退出                   |
| 常见用户 | 平台/应用团队              | 研究员/HPC/训练团队             |

### Distributed Computing: Ray / PyTorch Distributed / DeepSpeed / MPI

Ray 是一个分布式 Python 计算框架，解决有很多 Python 任务/actor，要分布到多台机器上跑
- Kubernetes / Slurm负责给你机器和 GPU
- Ray负责在这些机器内部调度 Python tasks / actors

### Parallelism: data parallel / tensor parallel / pipeline parallel / expert parallel

### scheduler
谁可以什么时候用哪些资源？
- Cluster scheduler: Kubernetes, slurm
- Training scheduler: microbatch怎么排，pipeline stage怎么交错，activation checkpointing怎么安排，communication overlap怎么做，checkpoint什么时候写
- Inference scheduler: vLLM scheduler (这一轮哪些请求做 prefill，哪些请求做 decode，最多处理多少 tokens，KV cache 是否够，谁优先，哪些请求要暂停/抢占，batch 怎么组成)
```
Kubernetes / Slurm scheduler:
  这个 LLM server pod / training job 放哪台机器？

Ray scheduler:
  这个 Python task / actor 放在哪个 worker？

vLLM scheduler:
  这一轮哪些请求进入模型 forward？

GPU hardware scheduler:
  CUDA kernels 在 GPU SM 上怎么执行？
```

### observability: metrics / logs / traces / GPU utilization
Metrics:
	GPU utilization
	GPU memory used
	tokens/sec
	requests/sec
	latency p50/p95/p99
	TTFT
	time per output token
	KV cache usage
	batch size
	queue length
	error rate
	network throughput
	disk throughput
	checkpoint duration
对于 LLM serving，特别重要的是：

```
TTFT: time to first token
TPOT: time per output token
tokens/sec
request latency
KV cache hit / usage
batch utilization
GPU memory fragmentation
```
Trace 追踪一个请求经过哪些步骤：

```
API gateway: 2ms
tokenization: 5ms
queue wait: 40ms
prefill: 180ms
decode: 1200ms
detokenization: 8ms
response streaming: ...
```

## Infrastructure Stack
1. GPU
2. Tensor Processing Units (TPUs)
3. High-bandwidth memory (HBM): supports moving large volumes of data in and out efficiently
	1. Leading manufacturer: SK Hynix (South Korea), Samsung (South Korea), Micron (USA)

### Compute and Infra
1. Nvidia AI chips currently account for over 60% of total compute, with Google and Amazon supplying much of the remainder and Huawei holding a small but growing share.
2. Total AI data center power capacity reached approximately 29.6 GW by Q4 2025
	1. AI chip power: 11.8 GW
	2. Remainder: cooling, networking, and other

## Steps
1. Nvidia and SK Hynix only design but do not manufacture chips. They provide designs to specialized semiconductor foundries: Taiwan Semiconductor Manufacturing Company (TSMC), Samsung FOundry
	1. **TSMC is a single point of dependency in the global ai supply chain**: NVDA Blackwell GPUs (Newest generation, B200, GB200) and AMD Mi300x
2. Fabricated chips are then packaged and tested by assembly companies: ASE Group (TW), Amkor Technology (US)

> Q: When Nvidia selling GPUs, is it per unit, or per node including the NVLink and stuff? 
> A: depends on product and buyer
> - 1. Individual GPU cards:
> 	- For PCIe GPUs, NVIDIA and partners sell individual accelerator cards like H100 PCIe GPU, L40S GPU, L4 GPU
> 	- Go into servers built by OEMs like Dell, HPE, Supermicro, Lenovo
> - 2. HGX platform/GPU baseboard
> 	- For high-end training nodes, NVIDIA often sells or supplies an **HGX platform** through server OEMs.
> 	- HGX: platform combines multiple GPUs with high-speed interconnect NVLink/NVSwitch, plus surrounding platform design. bringing together GPUs, NVLink, networking, optimized AI/HPC software stacks
> 	- e.g. HGX H100 8GPU platform contains 8x H100 SXM GPUs, NVLink/NVSwitch GPU-to-GPU fabric, designed to be integraded into a server by OEM
> 	- Then Dell, Supermicro, HPE, Lenovo, etc. build a complete server around it, including CPUs, RAM, storage, NICs, power/cooling...
> - 3. DGX complete systems
> 	- Nvidia's own complete server/system product
> - 4. Rack-scale systems
> 	- new blackwell-era systems
> 	- many GPUs, Grace CPUs, NVLink switches, networking, cooling, and software are designed as one large unit
