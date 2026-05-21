# Main Conclusion

Related layers: [[Layer 2 - Computing product#Computing Product|how demand becomes a product]], [[Layer 3 - Computing System#Module 1: Workload|training vs inference workloads]], [[Layer 5 - Capital and timeline#Module 2: Revenue & Utilization|how demand becomes revenue and utilization]]

> 哪些 AI 需求会真实转化为算力需求、token 消耗、GPU-hour、云服务收入和数据中心 Capex？
1. **AI demand 已经从技术验证进入大规模采用，但企业生产化仍在早期。**  
    Consumer adoption 已经很快，开发者和知识工作者也开始高频使用 AI。但企业侧大多数仍处在 experimentation / pilot 阶段，尚未全面进入 workflow-level scaling。因此，AI demand 已经存在，但真正稳定、可预算、可长期签约的企业级需求还在释放过程中。
2. **Frontier training 仍然拉动大规模 AI 集群 [[Layer 5 - Capital and timeline#Module 1: Capex & Financing|Capex]]，但长期回报要靠 [[Layer 3 - Computing System#Module 1: Workload|inference demand]] 消化。**  
    训练需求解释了为什么 hyperscalers、模型公司和 sovereign AI 项目持续建设大规模 GPU 集群；但这些重资产投入的长期经济性，最终取决于推理负载是否持续增长、是否有高利用率、是否能形成稳定收入。
3. **Inference demand 的关键不是用户数，而是使用频率、任务复杂度、agent 化和 workflow 嵌入深度。**  
    “有多少人用 AI”只是起点。真正决定推理算力需求的是：用户多久用一次、每次任务多复杂、上下文多长、是否多模态、是否调用工具、是否进入企业核心流程、是否有 SLA 要求。
4. **Jagged frontier 决定 AI demand 会先在数字知识工作中释放，物理世界和高可靠任务会慢一些。** 
    AI 在代码、文本、知识检索、数据分析、客服、内容生成等数字任务中更容易商业化；但在机器人、复杂物理环境、高可靠自动化、多步骤稳定执行等场景中仍有明显短板。因此，短中期 AI datacenter demand 主要来自数字世界，而不是通用机器人或完全自动化企业。
5. **Agent 和多模态是未来单任务算力强度上升的核心变量。**  
    普通 chatbot 是一次输入、一次输出；agent workload 会拆解任务、调用工具、检索资料、执行代码、多轮反思和修正。因此，同一个用户任务在 agent 模式下会消耗更多 [[Layer 2 - Computing product#2.1 Token-based API|token]]、更多模型调用、更多上下文、更高 [[Layer 3 - Computing System#Module 5：Storage / Data Pipeline|存储和检索需求]]。多模态，尤其图像、视频、语音，也会显著提高单任务算力强度。
6. **Enterprise workflow redesign 是从“AI 试点”变成“稳定 datacenter demand”的关键转折点。**  
    企业只是试用 Copilot、chatbot 或部门 PoC，并不必然带来稳定算力需求。只有当 AI 被嵌入客服、销售、代码开发、数据分析、知识管理、财务、运营等核心流程，并且改变 workflow，才会形成长期、稳定、高 [[Layer 4 - Physical#Module 5: Operations / Reliability|SLA]]、高合规的 AI infrastructure demand。

# 核心问题
```
AI capability improvement
→ new use cases become viable
→ users / enterprises generate AI workloads
→ workloads become training / inference / fine-tuning / agent tasks
→ workloads consume tokens, GPU-hours, storage, networking, power
→ cloud / model lab / enterprise / sovereign AI 扩建 AI datacenter
```

Key links: [[Layer 3 - Computing System#Module 1: Workload|training / inference]], [[Layer 2 - Computing product#1.3 By revenue unit|tokens and GPU-hours]], [[Layer 3 - Computing System#Module 5：Storage / Data Pipeline|storage]], [[Layer 3 - Computing System#Module 4：Network|networking]], [[Layer 4 - Physical#Module 1: Electricity / Power Chain|power]], [[Layer 4 - Physical#Module 6: Physical Metrics / Unit Economics Bridge|AI datacenter]].

# Demand

## 算力需求计算模型
```
Inference compute demand
= number of users
× usage frequency
× tokens per task
× model cost per token
× task complexity
× SLA requirement
× paid conversion / enterprise procurement
```

See also: [[Layer 3 - Computing System#Module 1: Workload|Inference workload]].

## Four demand types for AI: 

| 需求类型                    | 由什么驱动                                                                  | 对数据中心意味着什么                                   | 关键指标                                                                           |
| ----------------------- | ---------------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------ |
| **Frontier training**   | 模型能力继续 scaling，模型公司竞争，reasoning / RL，多模态训练，synthetic data，sovereign AI | 大规模 GPU 集群、高速网络、HBM、checkpoint storage、高电力密度 | Training cluster size、GPU count、HBM、network bandwidth、power density            |
| **Inference**           | 用户规模、[[Layer 2 - Computing product#2.1 Token-based API|token]] 使用量、多模态、低延迟体验、API 调用、consumer AI、developer tools            | 高利用率推理集群、[[Layer 5 - Capital and timeline#Cost/token|成本/token]]、分布式部署、服务稳定性、低延迟            | Tokens/day、requests/sec、cost/token、latency、utilization                         |
| **Enterprise workflow** | 企业把 AI 放进客服、销售、代码、财务、数据分析、知识管理等业务流程                                    | 私有化、合规、数据安全、云上托管、长期合同、高 SLA                  | Enterprise seats、production workloads、SLA、contract length、workflow penetration |
| **Agent / tool-use**    | 多步骤任务、工具调用、代码执行、浏览器操作、RAG、规划与记忆                                        | 更长上下文、更高 token 消耗、更多中间步骤、更高可靠性要求、更多存储和检索     | Calls/task、tokens/task、tool calls、context length、task success rate             |

- Stanford AI Index：模型能力仍在进步，AI 已快速进入大众采用阶段，并且 frontier training 的能耗继续上升
- McKinsey：企业采用广泛，但规模化仍早期，真正的企业级需求还没有完全释放

**Training: 拉动大集群建设的前置信号**
>"models have scaled faster than efficiency has improved, so total power required to train frontier systems has continued to increase" -- Standford AI Index
1. Demand from: Frontier model race, larger models, more synthetic data, multimodal training, reasoning/RL, post-training, national/sovereign AI
2. 特点：大集群，短期爆发性 capex，高网络要求，高hbm要求，高电力密度，客户集中在少数模型公司和hyperscalers
3. 主要拉动：GPU cluster, [[Layer 3 - Computing System#High Bandwidth Memory|HBM]], [[Layer 3 - Computing System#Module 4：Network|scale-up/scale-out networking]], infiniband/ethernet fabric, [[Layer 3 - Computing System#Training storage|checkpoint storage]], [[Layer 4 - Physical#kW per rack|high-density racks]], [[Layer 4 - Physical#Module 2: Cooling / Thermal System|liquid cooling]], large power blocks
4. Risks: 客户集中，投资节奏受hyperscaler capex控制，训练集群可能阶段性过度建设，模型架构变化可能改变算力需求，单位模型训练成本下降


**Inference：长期利用率和回报率**
1. Demand from: consumer usage, enterprise deployment, API calls, coding agents, customer support, search/ads/recommendation integration, multimodal generation
2. 特点：持续，贴近收入，看中 [[Layer 5 - Capital and timeline#Cost/token|成本/token]]，看重 [[Layer 5 - Capital and timeline#2. Utilization is the core of the economics|利用率]]，看中服务稳定性和延迟，客户面更广
3. 主要拉动：high-utilization GPU clusters, cost-optimized accelerators, distributed serving infrastructure, low-latency networking, storage/retrieval systems, observability, autoscaling, model routing, batch inference, edge/regional deployment in some cases

**Enterprise** 
- Stage 1: Experiment 个人试用、部门试点、PoC
	- 对算力需求分散、不稳定、预算小
- Stage 2: Adoption 开始接入客服、销售、代码、文档、数据分析
	- 对 API / cloud service 需求上升
- Stage 3: Workflow transformation AI 嵌入核心流程，重构业务系统
	- 长期、稳定、高 SLA、高合规、高算力需求

每个阶段对 datacenter 的含义

|阶段|企业行为|算力需求特征|商业模式|
|---|---|---|---|
|Experiment|试用 ChatGPT / Copilot / 部门 PoC|分散、低预算、不稳定|SaaS seat、API trial|
|Adoption|部分业务接入 AI，如客服、代码、文档、数据分析|开始形成持续 API / cloud usage|[[Layer 2 - Computing product#2.2 Cloud AI service|Cloud AI service]]、API、[[Layer 5 - Capital and timeline#D. Reserved capacity|reserved capacity]]|
|Workflow transformation|AI 改造核心流程，成为生产系统|稳定、高 [[Layer 4 - Physical#Module 5: Operations / Reliability|SLA]]、高合规、高算力|长期云合同、私有化、[[Layer 5 - Capital and timeline#F. Dedicated capacity|专属集群]]、hybrid cloud|

## Demand Quality Scoring

|维度|低质量需求|高质量需求|
|---|---|---|
|使用频率|偶尔尝鲜|每日 / 每小时使用|
|付费意愿|免费用户|企业预算 / 生产系统预算|
|工作流嵌入|独立工具|嵌入核心业务流程|
|任务复杂度|一问一答|多轮、多工具、多模态|
|SLA 要求|可慢、可失败|低延迟、高可用|
|数据要求|通用数据|企业私有数据、RAG、fine-tuning|
|可扩展性|单点试点|多部门、多地区复制|
|经济性|ROI 不清晰|明确降本 / 增收|
|合规要求|无明确要求|需要私有化、审计、权限控制|
|使用模式|随机使用|形成可预测 workload|

# Reading Notes
## Stanford AI Index 2026
> AI 需求来自哪些应用？训练和推理哪个更重要？模型能力提升是否刺激更多应用？

Top Takeaways: 
1. AI capability is not plateuing, it is accelerating and reaching more people than ever
2. The US-China AI model performance gap has effectively closed
3. The US hosts the most AI datacenters, with the majority of their chips fabricated by one taiwanese foundry. 
	1. US: 5427 data centers
	2. TSMC fabricates almost every leading AI chio
4. **Jagged frontier**: AI models can win a gold medal in IMO but cant reliably tell time
	1. strengths: abstract reasoning, pattern recognition in large datasets
	2. weakness: simple visual reasoning, consistent execution of multi step tasks, reliability
```
why? different skills rely on very different capabiilties
- math problems: symbolic reasoning, training data patterns
- reading clocks: precise visual, spatial reasoning (harder for models)
- computer tasks: planning + memory + tool use (still dveloping) 
```
5. Robot still fal at most household tasks, even as they excel in controlled env -> far from mastering the physical world (89% in predictable lab settings vs 12% in unpredictable household env)
6. Responsible AI is not keeping pace with AI capability with safety benchmarks lagging and incidents rising sharply
7. AI adoption is spreding at historic speed and consumers are deriving substantial value from tools they access for free (53% population adopt AI: singapore 61%, UAE 54%, US 28.3%)
8. Productivity gains from AI are appearing in many of the same fields where entry-level employment is starting to decline
	1. 14% - 26% productivity gain in customer support and sde
	2. 22-25 age developers fell 20%, while hc for older developers growing
9. models have scaled faster than efficiency has improved, so total power required to train frontier systems has continued to increase

## McKinsey The state of AI in 2025
1. Most organizations are still in the experimentation or piloting phase: Nearly 2/3 of respondents say their organizations have not yet begun scaling AI across the enterprise.
2. High curiosity in AI agents: 62% of survey respondents say their organizations are at least experimenting with AI agents.
3. Positive leading indicators on impact of AI: Respondents report use-case level cost and revenue benefits, and 64% say that AI is enabling their innovation. However, just 39% report EBIT impact at the enterprise level.
4. High performers use AI to drive growth, innovation, and cost: 80% of respondents say their companies set efficiency as an objective of their AI initiatives, but the companies seeing the most value from AI often set growth or innovation as additional objectives.
5. Redesigning workflows is a key success factor: Half of those AI high performers intend to use AI to transform their businesses, and most are redesigning workflows.
6. Differing perspectives on employment impact: Respondents vary in their expectations of AI’s impact on the overall workforce size of their organizations in the coming year: 32% expect decreases, 43% no change, and 13% increases.
7. 
