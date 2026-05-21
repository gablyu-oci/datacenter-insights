# Framework: How to Look at the AI Datacenter Industry

## Model 
### 5 layers
[[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)]]
- Application, model, inference, enterprise procurement
[[Layer 2 - Computing product]]
- GPU hour, Cloud Services, API, token, hosting capacity
[[Layer 3 - Computing System]]
- Chip, Server, network, storage, software 
[[Layer 4 - Physical]]
- Electricity, Cooling, land, engineering, operations
[[Layer 5 - Capital and timeline]]
- Capex, financing, depreciation, payback period, utilization rate

### Questions
For each layer, I need to know:
1. why do we need it
2. what does it sell
3. how to produce
4. physical constraints?
5. how to make money
6. what are the risks

## Focusing area
For Companies:
- 算力芯片：NVIDIA、AMD、Intel
- 网络芯片 / ASIC：Broadcom、Marvell
- 交换机：Arista、Cisco
- 服务器 / ODM：Dell、HPE、Supermicro、Quanta、Wiwynn
- 电力设备：Schneider、Eaton、Vertiv、ABB、Siemens
- 冷却设备：Vertiv、Schneider、Johnson Controls、Trane
- IDC / Colo：Equinix、Digital Realty、GDS、秦淮数据相关资料
- 云厂商：Amazon、Microsoft、Google、Oracle、Meta
- GPU Cloud / NeoCloud：CoreWeave、Nebius、IREN、Crusoe 等

Each company:
- 年报 / 10-K / 20-F
- 季度财报电话会
- Investor Day
- 产品白皮书
- 客户案例
- 资本开支指引
- 订单 backlog
- 管理层对 AI data center 的表述

For financial reports:
- AI 订单来自哪里
- 数据中心业务占比
- 产能瓶颈在哪里
- 交付周期多长
- 客户是否集中
- 毛利率是否提升
- Capex 是否扩张
- 管理层如何描述电力和散热瓶颈

## GPT recommendations
### 总体阅读原则

你不要按“文章数量”读，要按这 5 个问题读：

```
Layer 1：为什么需要算力？
Layer 2：算力被包装成什么产品卖出去？
Layer 3：算力产品背后需要什么计算系统？
Layer 4：计算系统受什么物理约束？
Layer 5：谁出钱、多久回本、风险在哪里？
```

1–2 天内，**每层读 2–4 个材料就够了**。目标不是掌握所有细节，而是能画出这张图：

```
AI 应用需求
   ↓
Token / API / GPU-hour / 云服务 / 托管容量
   ↓
芯片 / 服务器 / 网络 / 存储 / 调度软件
   ↓
电力 / 散热 / 土地 / 工程 / 运维
   ↓
Capex / 折旧 / 融资 / 利用率 / 回本周期
```

Navigation version: [[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Demand|AI 应用需求]] → [[Layer 2 - Computing product#1.3 By revenue unit|Token / API / GPU-hour / 云服务 / 托管容量]] → [[Layer 3 - Computing System#Main Takeaways|芯片 / 服务器 / 网络 / 存储 / 调度软件]] → [[Layer 4 - Physical#Module 6: Physical Metrics / Unit Economics Bridge|电力 / 散热 / 土地 / 工程 / 运维]] → [[Layer 5 - Capital and timeline#Layer 5: Capital, Revenue, Timeline, and Risk|Capex / 折旧 / 融资 / 利用率 / 回本周期]].

---

### Layer 1 — AI Demand

**Application, model, inference, enterprise procurement**

这一层解决的问题是：**为什么要建 AI datacenter？需求到底从哪里来？**

#### 必读材料

|材料|看什么|你要产出的笔记|
|---|---|---|
|**Stanford AI Index 2025**|看 AI 技术进步、模型能力、AI 投资、企业采用、推理成本变化。它是建立 AI 需求大背景最好的年度材料之一。Stanford HAI 称 AI Index 是一个综合、数据驱动的 AI 技术、经济和社会影响资料库。|写出：AI 需求来自哪些应用？训练和推理哪个更重要？模型能力提升是否刺激更多应用？|
|**McKinsey State of AI 2025**|看企业 AI 采用情况。McKinsey 2025 调研显示，近 9 成受访者所在组织已常规使用 AI，但大多数仍处于试验或试点阶段，只有约三分之一开始规模化；agentic AI 也处于实验到扩张的早期阶段。|写出：企业采购 AI 的阶段：试点、规模化、Agent、私有化部署。|
|**Microsoft / Alphabet / Meta 年报里的 AI 叙述**|看大厂如何描述真实需求。比如 Alphabet 在 2025 年报中把 AI-optimized infrastructure 放在 full-stack AI strategy 的基础层，并提到 GPU、TPU、数据中心效率和 Google Cloud 客户需求。|写出：谁是最终需求方？消费者、企业、开发者、大模型公司、广告系统、搜索系统分别需要什么算力？|

#### 这一层你要形成的地图

```
AI Demand
├─ Consumer AI：ChatGPT / Gemini / Copilot / 搜索 / 图片 / 视频
├─ Enterprise AI：知识库问答 / 代码助手 / 客服 / 销售 / 金融 / 医疗
├─ Developer AI：API / coding agent / workflow automation
├─ Model lab：基础模型训练 / 微调 / RL / synthetic data
└─ Existing platforms：广告推荐 / 搜索排序 / 内容生成 / 风控
```

#### 快速判断问题

看完这一层，你应该能回答：

```
需求是训练驱动，还是推理驱动？需求来自 C 端用户，还是企业采购？是短期试点，还是进入生产系统？AI 应用增长会转化成 token、API call、GPU hour 还是私有集群需求？
```

Key links: [[Layer 3 - Computing System#Module 1: Workload|训练 vs 推理 workload]], [[Layer 2 - Computing product#1.3 By revenue unit|token、API call、GPU hour、私有集群需求]].

---

### Layer 2 — Computing Product

**GPU hour, Cloud Services, API, token, hosting capacity**

这一层解决的问题是：**算力最后以什么形式被卖出去？**

#### 必读材料

| 材料                                            | 看什么                                                                                                                                                                      | 你要产出的笔记                                                                     |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| **OpenAI API Pricing**                        | 看 token 如何计价。OpenAI 文档说明，Responses API、Chat Completions API、Realtime API、Batch API 等不是单独定价，tokens 会按所选模型的 input / output rate 计费；内置工具、file search、web search 等也会影响成本结构。  | 写出：token 是如何变成收入单位的？input token、output token、cached token、tool call 有什么差异？  |
| **Amazon Bedrock Cost Management**            | 看云厂商如何包装模型推理成本。AWS 文档说明，Bedrock 成本由模型推理驱动，API call 会处理输入和输出 token，成本取决于模型、token 类型、区域路由等因素。                                                                              | 写出：云厂商如何卖“模型 API”？按 token、按 provisioned throughput、按区域、按模型分层。               |
| **Azure AI Foundry Models Pricing**           | 看企业云平台如何把多模型做成托管服务。Azure Foundry Models 支持 OpenAI、DeepSeek、Grok、Llama、Mistral 等模型，并提供 pay-as-you-go 和 provisioned throughput 两类模式。                                       | 写出：企业客户买的是模型能力，不一定直接买 GPU。                                                  |
| **Google Agent Platform / Vertex AI Pricing** | 看 Google 如何把生成式 AI、agent、partner models 做成 managed APIs。Google 页面说明 partner models 以 managed APIs 形式提供，并列出不同模型的定价。                                                       | 写出：不同云平台的 AI 产品如何分层。                                                        |
| **CoreWeave Cloud Pricing**                   | 看 GPU cloud 如何按 GPU、CPU、storage、networking 卖资源。CoreWeave 将其定价页定位为 AI compute、storage、networking 等产品组合定价。                                                                 | 写出：GPU-hour / reserved capacity / storage / networking 是如何组合成 AI cloud 产品的。 |
| **NVIDIA DGX Cloud**                          | 看“managed training platform”这种产品形态。NVIDIA DGX Cloud 被描述为跨 AWS、Google Cloud、Azure、OCI 的 fully managed AI training platform，提供协同优化的 NVIDIA accelerated computing clusters。 | 写出：有些客户买的不是裸 GPU，而是托管训练平台。                                                  |

#### 这一层你要形成的地图

```
Computing Product
├─ Token / API
│  ├─ input token
│  ├─ output token
│  ├─ cached token
│  └─ tool / retrieval / agent call
├─ Cloud AI Service
│  ├─ AWS Bedrock
│  ├─ Azure AI Foundry
│  ├─ Google Vertex / Agent Platform
│  └─ model marketplace
├─ GPU Cloud
│  ├─ GPU-hour
│  ├─ reserved GPU capacity
│  ├─ managed Kubernetes / Slurm
│  └─ storage + networking
├─ Dedicated AI Cluster
│  ├─ enterprise private AI
│  ├─ model lab training cluster
│  └─ sovereign AI cluster
└─ Hosting Capacity
   ├─ rack
   ├─ cage
   ├─ MW
   └─ build-to-suit data center
```

#### 快速判断问题

```
客户买的是 token、API、GPU-hour、云服务，还是 MW 容量？收入是按量付费，还是长期合同？谁承担利用率风险：客户、云厂商、GPU cloud，还是数据中心运营商？
```

Key links: [[Layer 2 - Computing product#1.3 By revenue unit|revenue units]], [[Layer 5 - Capital and timeline#2. Utilization is the core of the economics|utilization risk]].

---

### Layer 3 — Computing System

**Chip, server, network, storage, software**

这一层解决的问题是：**算力产品背后，实际需要什么系统来生产？**

#### 必读材料

|材料|看什么|你要产出的笔记|
|---|---|---|
|**NVIDIA GB200 NVL72**|看 AI datacenter 为什么从服务器级走向 rack-scale。NVIDIA 把 GB200 NVL72 描述为单柜 exascale computer，72 个 Blackwell GPU 通过 NVLink 互联，并提供 130 TB/s 低延迟 GPU 通信。|画出：GPU → board → server → rack → cluster。|
|**NVIDIA Blackwell Architecture**|看新一代 AI 芯片平台如何围绕生成式 AI、效率、scale 来设计。NVIDIA 官方页面把 Blackwell 定义为面向 generative AI 和 accelerated computing 的架构。|写出：芯片不只是 FLOPS，还包括 [[Layer 3 - Computing System#High Bandwidth Memory|显存]]、[[Layer 3 - Computing System#Module 4：Network|互联]]、[[Layer 3 - Computing System#TDP / power efficiency|功耗]]、[[Layer 3 - Computing System#Module 6: Software Stack|软件栈]]。|
|**NVIDIA Spectrum-X Ethernet**|看 AI 网络为什么重要。NVIDIA 称 Spectrum-X 是面向 AI networking 的 Ethernet 平台，用于训练和部署大规模 AI，并强调 switch、SuperNIC、RoCE、性能隔离、storage fabric、跨数据中心扩展等。|写出：[[Layer 3 - Computing System#Module 4：Network|scale-up 与 scale-out 网络]]分别解决什么问题。|
|**MLCommons MLPerf Training**|看系统级 benchmark。MLPerf Training 衡量的是系统把模型训练到目标质量所需速度，不只是单个芯片指标。|写出：AI 集群性能 = 芯片 + 网络 + 存储 + 软件 + 调度。|
|**Arista AI Networking Whitepaper**|看 Ethernet AI fabric 的另一种叙事。Arista 白皮书讨论 AI clusters 从几十到 100,000+ XPUs 的 Ethernet networking 方案。|写出：InfiniBand、Ethernet、RoCE、UEC 等网络路线如何竞争。|

#### 这一层你要形成的地图

```
Computing System
├─ Chip
│  ├─ GPU / ASIC / TPU
│  ├─ HBM
│  ├─ advanced packaging
│  └─ power efficiency
├─ Server / Rack
│  ├─ HGX / MGX / NVL rack
│  ├─ CPU + GPU
│  ├─ NIC / DPU
│  └─ power shelf / liquid cooling interface
├─ Network
│  ├─ scale-up：GPU 内部互联，NVLink / UALink / proprietary fabric
│  ├─ scale-out：InfiniBand / Ethernet / RoCE
│  ├─ switch ASIC
│  ├─ optical module
│  └─ cables / transceivers
├─ Storage
│  ├─ training data
│  ├─ checkpoint
│  ├─ object storage
│  └─ high-throughput file system
└─ Software
   ├─ CUDA / ROCm / compiler
   ├─ Kubernetes / Slurm
   ├─ vLLM / Triton / inference serving
   ├─ observability
   └─ scheduler / utilization optimizer
```

#### 快速判断问题

```
系统瓶颈在 GPU、HBM、网络、存储、散热，还是调度？这个方案是为训练优化，还是为推理优化？是单机性能提升，还是集群效率提升？
```

---

### Layer 4 — Physical

**Electricity, cooling, land, engineering, operations**

这一层解决的问题是：**AI 算力为什么会被电力、散热、土地、工程约束？**

#### 必读材料

|材料|看什么|你要产出的笔记|
|---|---|---|
|**IEA Energy and AI**|看电力约束。IEA 预计全球数据中心用电到 2030 年将超过翻倍，达到约 945 TWh，AI 是主要驱动之一。|写出：电力为什么成为 AI datacenter 的核心瓶颈。|
|**McKinsey Beyond Compute**|看 power 和 cooling 设备机会。McKinsey 把 power 和 cooling equipment 称为 AI data center infrastructure 的 backbone，并预计数据中心需求到 2030 年可能达到 220 GW，约为 2020 年的近 6 倍。|画出：电力设备、散热设备、工程建设的产业链。|
|**OCP Cooling Environments**|看液冷技术路线。OCP 指出高功率密度带来新的冷却挑战，液冷尤其是温水冷却成为有效替代方案；其 Cooling Environments 项目覆盖 cold plate、CDU、immersion、door heat exchanger、heat reuse 等方向。|写出：风冷、冷板液冷、浸没式、CDU、rear-door 的位置。|
|**Uptime Institute Tier Certification**|看可靠性和冗余。Uptime Institute 的 Tier Certification 将数据中心分为 Tier I 到 Tier IV，并与其 Tier Standard 中的基础设施和运营标准对应。|写出：数据中心不只是能跑，还要可维护、可用、可冗余。|
|**Schneider Electric Data Center Reference Designs**|看真实工程设计如何集成电力、冷却和 IT。Schneider 的参考设计覆盖 AI、液冷、高密度工作负载，并说明现代 reference design 通常包括电气配电、机械系统、冷却架构、机房布局和 IT 空间规划。|画出：从电网到机柜、从热量到冷却系统的工程图。|
|**ODCC / 中国信通院《智算中心液冷产业全景研究报告 2025》**|看中国语境下的液冷产业链。ODCC 页面介绍该报告聚焦液冷系统关键零部件、液冷 IT 设备、整体解决方案和液冷智算中心实践，并梳理 17 个关键环节和 110 余家代表企业。|写出：中国智算中心液冷产业链有哪些环节。|
|**国家数据基础设施建设指引**|看中国政策语境。国家发改委、国家数据局、工信部于 2025 年 1 月发布《国家数据基础设施建设指引》，用于指导国家数据基础设施建设和运营。|写出：中国政策里“数据基础设施 / 算力 / 数据流通 / 绿色低碳”的关系。|

#### 这一层你要形成的地图

```
Physical Infrastructure
├─ Electricity
│  ├─ grid connection
│  ├─ substation
│  ├─ transformer
│  ├─ switchgear
│  ├─ UPS
│  ├─ generator
│  ├─ busway / PDU
│  └─ rack power
├─ Cooling
│  ├─ air cooling
│  ├─ direct-to-chip liquid cooling
│  ├─ CDU
│  ├─ immersion cooling
│  ├─ rear-door heat exchanger
│  ├─ chiller
│  └─ heat reuse
├─ Site
│  ├─ land
│  ├─ water
│  ├─ fiber
│  ├─ permits
│  └─ grid queue
├─ Engineering
│  ├─ design
│  ├─ procurement
│  ├─ construction
│  ├─ commissioning
│  └─ maintenance
└─ Operations
   ├─ uptime
   ├─ redundancy
   ├─ monitoring
   ├─ failure response
   └─ capacity planning
```

#### 快速判断问题

```
这个项目卡在 GPU，还是卡在电力接入？单柜功率密度是多少？PUE、WUE、kW/rack、MW capacity 怎么影响商业模型？液冷是必要条件，还是效率优化？
```

---

### Layer 5 — Capital and Timeline

**Capex, financing, depreciation, payback period, utilization rate**

这一层解决的问题是：**这个重资产生意如何赚钱？风险在哪里？**

#### 必读材料

|材料|看什么|你要产出的笔记|
|---|---|---|
|**Microsoft 2025 Annual Report**|看 hyperscaler 如何披露 AI 基础设施投资。Microsoft 年报提到 2025 财年 additions to property and equipment 为 645.51 亿美元，并披露 computer equipment 的使用寿命通常为 2–6 年；还提到截至 2025 年 6 月已承诺 321 亿美元用于新建筑、建筑改善和租赁改良，主要与数据中心有关。|写出：云厂商 Capex 如何进入资产负债表，折旧如何影响利润表。|
|**Meta Q4 / FY2025 Results**|看 AI infra capex 如何跳升。Meta 披露 2025 年全年 capital expenditures 为 722.2 亿美元，并预计 2026 年 capex 达 1150–1350 亿美元，增长由 Meta Superintelligence Labs 和核心业务投资驱动；同时指出费用增长主要来自基础设施成本，包括第三方云支出、更高折旧和更高基础设施运营费用。|写出：AI datacenter 的费用压力来自 capex、折旧、云支出和运维。|
|**Alphabet 2025 Form 10-K**|看 AI 基础设施的供应约束。Alphabet 披露其 AI strategy 的基础是 AI-optimized infrastructure，包括 GPU 和自研 TPU；同时说明技术基础设施扩张受电力、水和土地可得性约束，AI 计算需求增加使全球能源供应更紧张。|写出：电力、土地、水、设备供应如何进入风险因素。|
|**CoreWeave 2025 Form 10-K**|看 GPU cloud / neocloud 的商业模型。CoreWeave 说明 AI workloads 需要不同于通用云的基础设施，包括高密度计算、先进网络、优化存储和能管理复杂分布式系统的软件；其风险因素也提到 power、供应商、数据中心提供商、客户集中、资本开支和融资需求。|写出：GPU cloud 的经济性 = 长约收入 + 高折旧 + 高融资 + 高利用率要求。|
|**Schneider CapEx / PUE Calculator 与 Reference Designs**|看项目早期如何估算工程成本。Schneider 页面说明 reference design 可用于估算每 rack 或每 kW 的工程系统成本，并支持 PUE、资本成本等工具。|写出：Capex/MW、PUE、电价、利用率如何影响回本。|

#### 这一层你要形成的地图

```
Capital & Timeline
├─ Capex
│  ├─ GPU / server
│  ├─ networking
│  ├─ storage
│  ├─ power equipment
│  ├─ cooling equipment
│  ├─ building / land
│  └─ engineering / commissioning
├─ Financing
│  ├─ operating cash flow
│  ├─ debt
│  ├─ lease
│  ├─ project finance
│  ├─ customer prepayment
│  └─ take-or-pay contract
├─ Cost
│  ├─ depreciation
│  ├─ electricity
│  ├─ maintenance
│  ├─ cloud / colo rent
│  ├─ staff
│  └─ interest expense
├─ Revenue
│  ├─ token
│  ├─ API call
│  ├─ GPU-hour
│  ├─ reserved capacity
│  ├─ MW lease
│  └─ managed service
└─ Risk
   ├─ utilization risk
   ├─ customer concentration
   ├─ power delay
   ├─ GPU price decline
   ├─ model efficiency improvement
   ├─ technology route change
   └─ financing cost
```

#### 快速判断问题

```
谁出 Capex？收入是一次性设备销售，还是持续服务收入？资产折旧几年？GPU 利用率多少才能赚钱？客户合同期限是否覆盖资产折旧期？如果模型效率提升，算力需求是上升还是下降？
```

---

### 1 天极速阅读顺序

如果你只有 **1 天**，按这个顺序，不要扩展：

#### 上午：需求和产品

```
09:00–09:45  Stanford AI Index 202509:45–10:30  McKinsey State of AI 202510:30–11:15  OpenAI API Pricing + AWS Bedrock Cost Management11:15–12:00  Azure AI Foundry / Google Agent Platform / CoreWeave Pricing
```

上午结束时，你要画出：

```
AI Demand → Token / API / GPU-hour / Cloud Service
```

---

#### 下午：系统和物理基础设施

```
13:30–14:15  NVIDIA GB200 NVL72
14:15–15:00  NVIDIA Spectrum-X / Arista AI Networking
15:00–15:45  IEA Energy and AI
15:45–16:30  McKinsey Beyond Compute
16:30–17:15  OCP Cooling Environments
17:15–18:00  Uptime Institute / Schneider Reference Designs
```

下午结束时，你要画出：

```
Chip → Server → Rack → Cluster → Network → StorageGrid → Power chain → Rack → Heat → Cooling chain
```

---

#### 晚上：资本和周期

```
20:00–20:45  Microsoft 2025 Annual Report20:45–21:30  Meta FY2025 Results21:30–22:15  Alphabet 2025 Form 10-K22:15–23:00  CoreWeave 2025 Form 10-K
```

晚上结束时，你要写出：

```
AI datacenter 经济账 =Capex + financing + depreciation + electricity + utilization + customer contract
```

---

### 2 天版本：更完整的输出

如果你有 **2 天**，建议这样安排。

#### Day 1：从需求到计算系统

目标：搞清楚 **为什么需要算力、算力怎么卖、系统怎么搭**。

```
Layer 1：Stanford AI Index + McKinsey State of AI
Layer 2：OpenAI / AWS / Azure / Google / CoreWeave pricing
Layer 3：NVIDIA GB200 + Blackwell + Spectrum-X + MLPerf
```

Day 1 的最终产出：

```
图 1：AI 需求地图
图 2：算力产品地图
图 3：计算系统地图
```

---

#### Day 2：从物理约束到资本回报

目标：搞清楚 **为什么电力和散热成为瓶颈、这个生意如何回本**。

```
Layer 4：IEA + McKinsey Beyond Compute + OCP + Uptime + Schneider
Layer 5：Microsoft + Meta + Alphabet + CoreWeave filings
中国补充：ODCC / 信通院液冷报告 + 国家数据基础设施建设指引
```

Day 2 的最终产出：

```
图 4：物理基础设施地图
图 5：资本回报模型
图 6：产业链玩家地图
```

---

### 你最后应该形成的产业地图

读完这些材料后，把所有玩家放进下面这张图里：

```
Layer 1：AI Demand
应用公司 / 模型公司 / 企业客户 / 开发者 / 广告搜索平台

Layer 2：Computing Product
OpenAI API / AWS Bedrock / Azure AI Foundry / Google Vertex / CoreWeave / DGX Cloud / Colocation

Layer 3：Computing System
NVIDIA / AMD / Broadcom / Marvell / Arista / Cisco / Dell / HPE / Supermicro / ODM / storage vendors

Layer 4：Physical
Vertiv / Schneider / Eaton / ABB / Siemens / Johnson Controls / Trane / engineering contractors / utilities / landowners

Layer 5：Capital & Timeline
Microsoft / Amazon / Google / Meta / Oracle / CoreWeave / Equinix / Digital Realty / REITs / debt investors / project finance
```

---

### 最小阅读包：只看这 12 个

如果你想压缩到最少，先看这 12 个：

```
1. Stanford AI Index 2025
2. McKinsey State of AI 2025
3. OpenAI API Pricing
4. AWS Bedrock Cost Management
5. CoreWeave Pricing
6. NVIDIA GB200 NVL72
7. NVIDIA Spectrum-X
8. MLPerf Training
9. IEA Energy and AI
10. McKinsey Beyond Compute
11. OCP Cooling Environments
12. Microsoft / Meta / Alphabet / CoreWeave annual filings
```

这 12 个对应的就是：

```
需求 → 产品 → 系统 → 物理约束 → 资本周期
```
