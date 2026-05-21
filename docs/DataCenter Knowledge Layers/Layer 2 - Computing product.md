> [[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Demand|AI demand]] 不会直接变成 [[Layer 5 - Capital and timeline#Module 2: Revenue & Utilization|datacenter revenue]]。它会先被包装成 token、API、GPU-hour、provisioned throughput、managed platform、reserved capacity 或 cloud / hosting capacity。不同产品形态决定了谁有客户关系、谁有定价权、谁承担 [[Layer 5 - Capital and timeline#2. Utilization is the core of the economics|利用率风险]]，以及数据中心扩建的节奏。

# Computing Product

Related layers: [[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Demand|demand sources]], [[Layer 3 - Computing System#Main Takeaways|systems that produce compute]], [[Layer 5 - Capital and timeline#1. Revenue models|revenue models]]

## 1. Product Comparison

### 1.1 By customer & value

| Product type                  | Example          | Customer buys                                   | Pricing unit                                              | Main value                           |
| ----------------------------- | ---------------- | ----------------------------------------------- | --------------------------------------------------------- | ------------------------------------ |
| **Token API**                 | OpenAI API       | Model intelligence on demand                    | [[Layer 5 - Capital and timeline#A. Token revenue|Input / output / cached token]], tool call                  | Simple access to model capability    |
| **Cloud AI service**          | Amazon Bedrock   | Enterprise-ready managed model service          | Token, [[Layer 5 - Capital and timeline#E. Provisioned throughput|provisioned throughput]], batch, guardrails, RAG     | Cloud-native enterprise model access |
| **GPU cloud**                 | CoreWeave        | GPU capacity and AI infrastructure              | [[Layer 5 - Capital and timeline#C. GPU-hour|GPU-hour]], [[Layer 5 - Capital and timeline#D. Reserved capacity|reserved capacity]], storage, networking          | Access to scarce AI compute          |
| **Enterprise AI platform**    | Azure AI Foundry | Governed AI app / agent development environment | Token, endpoint, platform service, provisioned throughput | Enterprise control plane             |
| **Managed AI supercomputing** | NVIDIA DGX Cloud | Pre-integrated NVIDIA AI supercomputer          | Cluster access, subscription, enterprise contract         | Full-stack AI training environment   |

### 1.2 By risk allocation

| Product type                  | Provider bears                                                | Customer bears                                      |
| ----------------------------- | ------------------------------------------------------------- | --------------------------------------------------- |
| **Token API**                 | Capacity planning, GPU utilization, serving reliability       | Usage bill, latency tier choice                     |
| **Cloud AI service**          | Model hosting, platform integration, enterprise service layer | Usage volume, committed throughput if provisioned   |
| **GPU cloud**                 | Capex, depreciation, financing, idle capacity                 | Workload optimization, reserved contract commitment |
| **Enterprise AI platform**    | Platform, model catalog, compliance, integration              | App adoption, workflow transformation               |
| **Managed AI supercomputing** | Cluster operations, software stack, partner infrastructure    | Project demand, training workload duration          |
| **Colocation / hosting**      | [[Layer 4 - Physical#Module 6: Physical Metrics / Unit Economics Bridge|Facility, power / cooling reliability]]                         | IT equipment, application utilization               |

### 1.3 By revenue unit

| Product                       | Revenue unit                                                    |
| ----------------------------- | --------------------------------------------------------------- |
| Token API                     | input token, output token, cached token                         |
| Agent API                     | token + tool call + storage + container session                 |
| Cloud AI service              | token + provisioned throughput + RAG + guardrails               |
| GPU cloud                     | [[Layer 5 - Capital and timeline#C. GPU-hour|GPU-hour]] + [[Layer 3 - Computing System#Module 5：Storage / Data Pipeline|storage]] + [[Layer 3 - Computing System#Module 4：Network|networking]] + managed service               |
| Enterprise AI platform        | endpoint + model usage + governance / evaluation / safety tools |
| Managed AI supercomputing     | subscription / enterprise contract / cluster access             |
| Colocation                    | [[Layer 4 - Physical#kW per rack|rack / kW]] / [[Layer 5 - Capital and timeline#G. MW lease|MW]] / lease term                                     |

---

## 2. Product Types in Detail

### 2.1 Token-based API
- **Example:** OpenAI API
- **Customer buys:** model intelligence on demand
- **Pricing unit:** input token, output token, cached token, tool call, modality output

**Revenue formula**
```
Token API revenue = input tokens   × input token price
                  + output tokens  × output token price
                  + cached tokens  × cached token price
                  + tool calls
                  + modality outputs
```

**Why output token is more expensive:** [[Layer 3 - Computing System#10. Inference 的核心是 latency、throughput、KV cache、batching|sequential decoding]] — model generates token by token, causing higher inference costs.

**Key takeaways**
1. Output token 更贵：生成阶段是推理成本核心
2. Long context 更贵：长上下文增加 memory / [[Layer 3 - Computing System#11. KV cache 是推理系统的关键资源|KV cache]] / latency pressure
3. Cached input 更便宜：上下文复用可以提高系统效率
4. Tool pricing 独立收费：AI API 正从 model API 变成 agent runtime
5. Image / audio / video pricing：多模态会改变 compute intensity

#### Batch / Flex / Priority
用价格区分 latency、reliability 和 capacity priority。

| Mode         | What it is                       | Best for                                                              | Tradeoff                                                  | Datacenter meaning                                 |
| ------------ | -------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------- |
| **Batch**    | 异步提交大量请求                  | offline jobs, evaluations, classification, embeddings, bulk processing | 约 50% cheaper，但结果不即时，通常 24h 内完成              | provider 可以把任务放在低峰期运行，提高 [[Layer 5 - Capital and timeline#Physical GPU utilization|GPU 利用率]] |
| **Flex**     | 更便宜的同步请求，处理优先级更低 | low-priority / non-production work, evals, data enrichment            | 更便宜，但可能更慢，甚至遇到 429 resource unavailable     | provider 用低优先级流量填充空闲 [[Layer 5 - Capital and timeline#2. Utilization is the core of the economics|capacity]]           |
| **Priority** | 更快、更稳定的处理                | high-value user-facing apps where latency matters                     | 更贵，例如 2.5x                                            | 客户为低延迟和确定性付费，provider 预留更高质量 capacity |

### 2.2 Cloud AI service
- **Example:** Amazon Bedrock
- **Customer buys:** managed model access + enterprise AI services
- **Pricing unit:** token, provisioned throughput, batch inference, knowledge base, guardrails

### 2.3 GPU cloud infrastructure
- **Example:** CoreWeave
- **Customer buys:** [[Layer 5 - Capital and timeline#C. GPU-hour|GPU-hour]], GPU cluster, [[Layer 3 - Computing System#Module 5：Storage / Data Pipeline|storage]], [[Layer 3 - Computing System#Module 4：Network|networking]], Kubernetes, inference / training platform
- **Pricing unit:** GPU-hour, reserved capacity, storage, networking, managed services

### 2.4 Enterprise AI platform
- **Example:** Azure AI Foundry
- **Customer buys:** unified model catalog, agent / RAG environment, evaluation, governance, security, deployment workflow
- **Pricing unit:** token, model endpoint, provisioned throughput, platform services

### 2.5 Managed AI supercomputing platform
- **Example:** NVIDIA DGX Cloud
- **Customer buys:** pre-integrated NVIDIA GPU cluster + software + networking + support
- **Pricing unit:** cluster access, subscription, enterprise contract

---

# Reading Notes

## A. Token-based product — OpenAI API Pricing
Using GPT 5.5 as an example.

**Token pricing**
- Input token: $5 / 1M (short), $10 (long context, >272k tokens)
- Output token: $30 / 1M (short), $60 (long)
- Cached input: $0.5 / 1M (short), $1 (long)
  - Input tokens that match a previously processed prompt prefix, billed at a lower rate
  - Generally 1024+ tokens

**Batch / Flex / Priority** — tradeoffs between cost, latency, reliability
- **Batch:** submit many requests async in a batch file
  - Best for offline jobs, evaluations, classification, embeddings, bulk processing
  - 50% cheaper but results are not immediate; complete within 24 hrs
- **Flex:** cheaper synchronous requests with slower / less guaranteed processing
  - Best for low priority or non-production work, evals, data enrichment
  - Cheaper but possibly get 429 resource unavailable error
- **Priority:** faster, more consistent processing
  - Best for high-value user-facing apps where latency matters
  - 2.5x more expensive

**Tool pricing**
- Web search: $10 / 1k calls + search content token
- Containers: hosted shell and code interpreter, 1GB, $0.03 per 20-min session per container
- File search: storage $0.1 / GB / day, $2.5 / 1k calls
- Agent kit: $0.10 / GB-day after 1 GB free per account per month

**Image / audio / video pricing**
- Image: gpt-image-2 $8 / 1M input, $30 / 1M output. Based on quality and size, range $0.005 – $0.2 per image
- Audio: 4o-transcribe $2.5 / 1M input, $10 / 1M output → ~$0.006 / min

## B. Cloud AI service — Amazon Bedrock Cost Management
Amazon Bedrock: platform for building genAI apps and agents at production scale (powered by OpenAI?).
![[Pasted image 20260515132534.png]]

### B.1 On-demand inference
- **Model choice:** Claude Opus 4.7, Nemotron 3 Super, Claude Sonnet, GPT-5.5
- **Input / output / cache token:** based on provider, region, model, whether has cache write
- Supports cross-region routing

### B.2 Cost management features
- **Prompt caching** — reduce costs and latency
  - Use cache checkpoints: markers defining the contiguous subsection of prompt to cache (prompt prefix); prefix should be static between requests
  - Minimum token requirements (1024 / 4096 tokens usually), TTL (5 mins – 1 hr)
- **Prompt management**
  - Prompt optimization: auto-rewrites prompts to improve accuracy and produce more concise responses, $0.03 / 1000 tokens
- **Intelligent prompt routing** — uses a combination of foundation models from the same model family to optimize quality and cost
- **Model distillation**
  - Teacher model generates responses, data synthesis improves response generation, student model is fine-tuned
  - User identifies teacher and student model; Bedrock can either generate teacher responses from user prompts, or use responses from production data via invocation logs

### B.3 Provisioned throughput
Higher level of throughput for a model at a fixed cost.
- **Throughput:** number and rate of inputs and outputs a model processes and returns
- Billed hourly
- **Model Unit (MU):** delivers a specific throughput level for a specific model — total input + output tokens it can process and generate within one minute. Exact capacity of 1 MU depends on the model.

### B.4 Batch inference
(Async bulk inference at lower cost.)

### B.5 Knowledge base
- **Structured data retrieval (SQL generation):** $2 / 1000 queries
- **Rerank models:** improve relevance and accuracy of responses in RAG applications, $1 / 1000 queries

### B.6 Guardrails
- **Content filters** — $0.15 / 1000 text units (1 text unit = 1000 chars)
  - Check prompts and model responses for harmful or unsafe content (hate, insults, sexual, violence, misconduct, prompt attacks)
- **Sensitive information filters** — $0.1 / 1000 text units
  - Detect sensitive data in user prompts or model responses; configurable to block / mask
- **Contextual grounding check** — check if model's answer is grounded in the provided source / context
  - Best for RAG, summarization, paraphrasing, Q&A
  - Compares model response against reference source and user query to detect unsupported or irrelevant claims
- **Automated reasoning checks** — verify the model's answer obeys formal rules or policies
  - For policy-heavy domains (HR, finance, insurance, compliance)
  - Converts policy docs into formal logic rules and validates the answer against them

## C. GPU cloud — CoreWeave
Mostly **capacity-based cloud infrastructure sales**.

### C.1 What CoreWeave offers
1. GPU compute for AI training and inference: GB200, H200 Tensor Core, H100 Tensor Core, ...
   - Accelerators: specialized chips that accelerate compute-heavy work
   - Higher MFU: [[Layer 3 - Computing System#Model FLOPs Utilization|Model FLOPs Utilization]]
2. CPU / RAM
3. [[Layer 3 - Computing System#Module 5：Storage / Data Pipeline|AI object storage, distributed file storage]] (datasets, checkpoints, model weights), local storage, dedicated storage partner options, data movement
4. [[Layer 3 - Computing System#Module 4：Network|Networking]]: VPC, direct connect, private connectivity, internet transfer, high-performance cluster networking
5. Kubernetes-native bare-metal cloud built for HPC / AI workloads
6. On-demand vs committed / [[Layer 5 - Capital and timeline#D. Reserved capacity|reserved capacity]]
   - Reserved can offer **up to 60% discount** vs on-demand pricing
7. Dedicated inference: serverless, self-managed inference options — bring your own model weights, choose GPU types, runtimes, OpenAI-compatible endpoints while CoreWeave manages deployment, scaling, routing, operations

### C.2 Product surface

| Category                 | What customer buys                                                       |
| ------------------------ | ------------------------------------------------------------------------ |
| GPU instances            | Hourly access to nodes with NVIDIA GPUs                                  |
| CPU instances            | CPU-only compute for supporting workloads                                |
| Reserved capacity        | Committed GPU / CPU capacity, usually enterprise-scale                   |
| Spot / on-demand         | Flexible or burst compute                                                |
| Storage                  | Object storage, distributed file storage, local storage, dedicated storage |
| Networking               | VPC, public IPs, Direct Connect, peering / IP transit                    |
| Managed Kubernetes       | CoreWeave Kubernetes Service control plane                               |
| Inference platform       | Managed model serving, dedicated inference, OpenAI-compatible endpoints  |
| Training platform        | SUNK / Slurm-on-Kubernetes style training environments                   |
| Enterprise support       | Engineering support, deployment help, cluster management                 |

## D. Enterprise AI platform — Azure AI Foundry
Gives enterprises a unified environment to work with foundation models, generative AI apps, agents, RAG systems, evaluation tools, safety controls, and production deployment workflows.

### D.1 Core capabilities
1. **Model catalog / Foundry Models:** discover, compare, deploy, and manage models from multiple providers through an Azure-native interface; govern usage via Azure security, monitoring, compliance, and cost management tools
2. **Pay-as-you-go:** no need to reserve capacity
3. **Provisioned throughput**
4. **Enterprise security / compliance**
   1. Identity and access control
   2. Network security
   3. Data protection
   4. Governance and policy control
   5. Monitoring and auditability
   6. Responsible AI controls
   7. Compliance alignment

### D.2 How model providers enter the same cloud platform
1. **Agree on:** which models, which regions, pricing and revenue sharing, usage terms, enterprise data protection requirements, support responsibilities, compliance and safety expectations
2. **Model packaging and hosting**
   - *Cloud-hosted model:* Azure provides the GPU infra, networking, endpoint, management, scaling, monitoring, security controls. Customer calls Azure endpoint, not the model provider's public API directly → more control over data flow, access, compliance, operational governance.
   - *Partner-hosted or brokered model:* model provider operates part of the backend; cloud platform provides the marketplace, identity, billing, endpoint abstraction, and enterprise control layer.
3. **Unified API and endpoint abstraction:** cloud platform hides complexity (different providers have different native APIs, model formats, tokenization behavior, safety systems, deployment requirements) by exposing models through a consistent developer experience
4. **Unified identity and access control**
5. **Unified billing and procurement**
6. **Unified security and compliance layer**
7. **Unified model catalog and discovery experience**

## E. Managed AI supercomputing — NVIDIA DGX Cloud
Managed training and fine-tuning platform / full-stack AI supercomputing service. Customers get:
- NVIDIA GPU clusters
- NVIDIA AI software
- Networking
- Operational tooling — without having to build a full GPU supercomputer / data center themselves

**Why customers buy it:** AI teams need huge GPU capacity, but building it themselves is slow, expensive, and operationally hard.
- Fast access to scarce NVIDIA GPUs
- Full-stack NVIDIA environment
- Less infra burden
- Regional and sovereign AI options
- Training and inference at scale

**Demand mainly from:**
- Hyperscalers and cloud providers: Oracle, Azure, GCP, AWS, CoreWeave, ...
- AI model builders and AI-native startups
- Enterprises adopting genAI
- Sovereign AI and governments
- Robotics, autonomous vehicles, physical AI

### E.1 DGX Cloud vs OCI / Azure / AWS
**NVIDIA DGX Cloud is not a normal general-purpose cloud like OCI, Azure, or AWS.** It is an NVIDIA-managed AI supercomputing platform that runs _on top of_ or _through_ cloud providers. NVIDIA describes DGX Cloud as a fully managed AI platform for NVIDIA GPU performance "across clouds."

| Item                   | What it is                                              | Who owns the customer relationship? | What you buy                                                                              |
| ---------------------- | ------------------------------------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------- |
| **OCI**                | Oracle's full cloud platform                            | Oracle                              | Compute, storage, networking, databases, AI services, GPU clusters                        |
| **Azure**              | Microsoft's full cloud platform                         | Microsoft                           | Compute, storage, networking, Microsoft services, Azure OpenAI, GPU clusters              |
| **AWS**                | Amazon's full cloud platform                            | AWS                                 | EC2, S3, Bedrock, SageMaker, GPU clusters, etc.                                           |
| **NVIDIA DGX Cloud**   | NVIDIA's managed AI supercomputing / software experience | Usually NVIDIA + cloud partner      | NVIDIA-optimized GPU cluster access, DGX stack, NVIDIA AI Enterprise / NIM, NVIDIA support |
| **DGX Cloud Lepton**   | NVIDIA's GPU marketplace / routing layer                | NVIDIA ecosystem + providers        | Access to GPU capacity across providers / regions                                         |

**Bottom line:** OCI / Azure / AWS are clouds. DGX Cloud is an NVIDIA AI supercomputer experience hosted through clouds.

NVIDIA originally launched DGX Cloud with cloud partners, starting with OCI. NVIDIA said OCI Supercluster provided RDMA networking, bare-metal compute, and storage that could scale to very large GPU superclusters. DGX Cloud later became available through other environments, including Microsoft Azure and AWS Marketplace / private offers.

### E.2 What does "Oracle buys DGX" mean?
It usually does **not** mean Oracle is buying "NVIDIA's cloud business." It normally means one of these:

- **A. Oracle buys NVIDIA DGX systems / GPU racks / NVIDIA infrastructure**
  Oracle purchases NVIDIA GPU systems, networking, and software stack components, then deploys them inside OCI data centers.
- **B. Oracle hosts DGX Cloud capacity on OCI**
  NVIDIA DGX Cloud workloads can run on OCI infrastructure. In this case, the physical data center, network, power, storage, bare metal, and cloud control plane are OCI, while the branded managed AI experience is NVIDIA DGX Cloud.
- **C. Oracle integrates OCI GPU clusters into DGX Cloud Lepton**
  Oracle has said it is one of the first hyperscalers to integrate with NVIDIA DGX Cloud Lepton, so developers can access OCI GPU clusters for AI training, inference, digital twins, and HPC.

So yes: **if Oracle is "buying DGX" or "hosting DGX Cloud," it can still absolutely use OCI.** In fact, that's the point. OCI provides the underlying cloud infrastructure; NVIDIA provides the GPU architecture, DGX software / platform layer, and go-to-market channel.

**Simplified stack:**
```
Customer AI workload
        ↓
NVIDIA DGX Cloud / Lepton / NVIDIA AI Enterprise / NIM
        ↓
OCI GPU Supercluster, bare metal, RDMA networking, storage
        ↓
Oracle data center, power, cooling, operations
        ↓
NVIDIA GPUs, networking, systems
```

For Oracle, this is attractive because DGX Cloud can become a demand channel into OCI GPU capacity. NVIDIA / Oracle announcements specifically mention NVIDIA GB200 NVL72 systems on OCI Supercluster and up to 131,072 Blackwell GPUs.
