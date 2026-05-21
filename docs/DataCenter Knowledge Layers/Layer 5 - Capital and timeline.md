# Layer 5: Capital, Revenue, Timeline, and Risk

Related layers: [[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Demand|demand quality]], [[Layer 2 - Computing product#Computing Product|revenue products]], [[Layer 3 - Computing System#Main Takeaways|compute systems]], [[Layer 4 - Physical#Module 6: Physical Metrics / Unit Economics Bridge|physical constraints]]

Layer 5 is where the AI data center story turns into finance. The key question is not only whether capacity can be built, but whether capital can be converted into contracted, utilized, profitable capacity before costs, depreciation, and pricing pressure erode returns.

The core chain is:

**Capex committed -> [[Layer 4 - Physical#Module 1: Electricity / Power Chain|power]] secured -> facility built -> [[Layer 3 - Computing System#Module 3：Server / Rack|equipment]] delivered -> capacity commissioned -> customer workloads deployed -> utilization ramps -> revenue converts to cash flow.**

# Module 1: Capex & Financing

## 1. What capex actually includes

AI infrastructure capex is not just GPUs. The full capital stack includes:

- [[Layer 3 - Computing System#Module 2: Chip/Accelerator|GPUs and accelerators]]
- [[Layer 3 - Computing System#Module 3：Server / Rack|Servers and racks]]
- [[Layer 3 - Computing System#Module 4：Network|Networking]]: InfiniBand / Ethernet, switches, optics, cabling
- [[Layer 3 - Computing System#Module 5：Storage / Data Pipeline|Storage]]: local NVMe, shared storage, object storage, backup
- [[Layer 4 - Physical#Module 1: Electricity / Power Chain|Power infrastructure]]: grid interconnection, substations, transformers, switchgear, UPS
- [[Layer 4 - Physical#Module 2: Cooling / Thermal System|Cooling]]: air cooling, liquid cooling, CDUs, chillers, pumps, heat rejection
- Land, shell, and building construction
- Mechanical, electrical, and plumbing engineering
- Security, fire systems, monitoring, and controls
- Software platform, orchestration, observability, and customer portal
- Commissioning, testing, and customer onboarding

The important distinction:

- **[[Layer 4 - Physical#Module 3: Site / Land / Grid Access|Real estate]] and [[Layer 4 - Physical#Module 1: Electricity / Power Chain|power]] capex** can have a long useful life.
- **[[Layer 3 - Computing System#Module 2: Chip/Accelerator|GPU]] and [[Layer 3 - Computing System#Module 3：Server / Rack|server]] capex** has a much shorter economic life because performance per watt and market pricing can change quickly.

## 2. Capital intensity and timing mismatch

AI data centers are capital intensive before they are revenue generating. Cash leaves early, while revenue arrives later and ramps gradually.

This creates three pressures:

- **Funding pressure:** large upfront commitments before the asset earns.
- **Execution pressure:** delays in power, construction, or equipment push revenue further out.
- **Market pressure:** by the time capacity is live, pricing or demand may have changed.

The business is strongest when capex is backed by customer commitments before money is spent.

## 3. Financing structures

Financing can come from several sources:

- **Debt:** lower cost of capital, but requires predictable cash flow and strong collateral.
- **Lease financing:** useful for equipment, but can create fixed obligations even if utilization is weak.
- **Project finance:** works best when there are long-term contracted cash flows from creditworthy customers.
- **Customer prepayment:** reduces funding risk and validates demand, but may require discounts or priority access.
- **Long-term customer contracts:** the most important support for external financing.
- **Equity:** absorbs more risk, but is expensive and dilutive.
- **Vendor financing:** GPU, server, or infrastructure vendors may support purchases, but terms depend on customer quality and market conditions.

## 4. What lenders and investors care about

For AI data center financing, the underwriting question is:

**Is this a speculative build, or is it a contracted infrastructure asset?**

Key diligence questions:

- How much of the capacity is already contracted?
- Are customers investment-grade or strategically important?
- Are contracts take-or-pay, minimum-commitment, or purely usage-based?
- How long is the contract term relative to GPU depreciation?
- Are prices fixed, indexed, or resettable?
- Who bears power price risk?
- Who bears equipment obsolescence risk?
- Can the customer terminate early?
- What happens if delivery is delayed?

# Module 2: Revenue & Utilization

After capex is spent, the company has capacity. But capacity itself does not equal revenue. The economics depend on whether that capacity is sold, used, paid for, and renewed at attractive prices.

## 1. Revenue models

Different business models use different revenue units.

### A. Token revenue

For AI APIs or model services, revenue may be calculated by [[Layer 2 - Computing product#2.1 Token-based API|token]]:

- input tokens
- output tokens
- cached tokens
- batch inference tokens

This model is closest to application-layer AI and model service providers. It connects revenue to end-user demand, but also exposes the provider to model efficiency, routing, caching, and price competition.

### B. API revenue

Customers call models through APIs, and the platform charges by call volume, token count, service tier, latency requirement, or feature bundle.

This is the model used by AI platforms such as OpenAI, Anthropic, Google, Azure AI, and AWS Bedrock. It is closer to software revenue, but the gross margin still depends heavily on infrastructure cost and utilization.

### C. GPU-hour

[[Layer 2 - Computing product#2.3 GPU cloud infrastructure|GPU cloud]] providers often charge by GPU-hour. Customers rent GPUs by the hour, by server, by rack, or by full cluster.

This model is simple and transparent, but more exposed to spot pricing, customer churn, and idle inventory.

### D. Reserved capacity

Customers reserve capacity in advance, usually paying monthly or annually.

This is better for suppliers because revenue is more predictable. It is also valuable for customers because it guarantees access to scarce compute.

### E. Provisioned throughput

Customers buy a fixed throughput commitment, such as guaranteed tokens/sec, requests/sec, or inference capacity.

This is often stronger than pure usage-based pricing because it converts variable demand into a more stable infrastructure commitment.

### F. Dedicated capacity

Customers rent a dedicated GPU cluster or dedicated infrastructure.

This usually means longer contracts, larger deal sizes, and better financing support. The tradeoff is customer concentration risk.

### G. MW lease

This is closer to the [[Layer 4 - Physical#Module 6: Physical Metrics / Unit Economics Bridge|data center operator model]]. Customers lease power capacity by MW instead of paying by GPU-hour.

For example, a hyperscaler may lease 20MW, 50MW, or 100MW of capacity. The operator's economics depend more on power availability, construction execution, lease terms, and tenant credit quality than on token-level monetization.

## 2. Utilization is the core of the economics

Built capacity only generates revenue when it is used or contractually paid for.

Key metrics:

### Occupancy

The share of data center space or power capacity that has been leased.

Example: if a site has 100MW of capacity and 80MW is contracted, occupancy is 80%.

### Contracted utilization

The share of capacity covered by customer commitments, regardless of actual usage.

This matters because a take-or-pay customer can support financing even if physical utilization is uneven.

### Physical GPU utilization

The share of time GPUs are actually running workloads.

Example: if a GPU runs customer workloads for 18 hours out of a 24-hour day, physical utilization is 75%.

This metric is critical. GPUs are expensive and depreciate quickly, so idle capacity destroys returns.

### Economic utilization

The share of capacity that is monetized at attractive prices.

This is more important than raw physical utilization. A provider can keep GPUs busy at low prices and still earn poor returns.

### Cost/token

The cost of generating one [[Layer 2 - Computing product#2.1 Token-based API|token]].

This matters for model service providers. It is affected by GPU cost, utilization, [[Layer 4 - Physical#Electricity cost|power cost]], model efficiency, [[Layer 3 - Computing System#10. Inference 的核心是 latency、throughput、KV cache、batching|batching]], caching, quantization, routing, and inference optimization.

### Revenue/MW

How much revenue each 1MW of power capacity generates.

This matters because power is scarce. The company that can generate more revenue from the same MW has higher asset efficiency.

### Gross margin by workload

[[Layer 3 - Computing System#Module 1: Workload|Training, fine-tuning, batch inference, and real-time inference]] have different utilization patterns and margin profiles.

- Training may drive large [[Layer 3 - Computing System#Main Takeaways|cluster]] demand but can be project-based.
- Batch inference can improve utilization because workloads are schedulable.
- Real-time inference may command better pricing but requires latency and [[Layer 4 - Physical#Module 5: Operations / Reliability|reliability]].
- Enterprise dedicated capacity can be stable but may concentrate revenue in a few customers.

## 3. The basic unit economics

A simple way to think about the business:

**Cash return = contracted price x paid utilization - power cost - operating cost - financing cost - depreciation / obsolescence.**

The most important variables are:

- price per unit of capacity
- utilization level
- contract duration
- customer credit quality
- power cost and availability
- hardware cost
- depreciation schedule
- residual value of GPUs
- financing cost

A high-utilization business can still be weak if pricing falls too fast or financing costs are too high.

## 4. Why "built capacity" does not equal profit

A company may spend $5 billion buying GPUs, building facilities, and securing power.

But after the build is complete:

- Customer demand may be weaker than expected.
- Customers may only use the capacity short term.
- Market prices may fall.
- Competitors may cut prices.
- GPU utilization may only reach 40%.
- Debt interest still has to be paid.
- GPU depreciation continues every day.
- Newer GPUs may reset the market's price/performance expectations.

In that case, even if the capacity is technically built, the project may fail economically.

## Core Insight From Module 2

A good business has: **high paid utilization + long-term contracts + creditworthy customers + stable pricing + disciplined capex.**

A bad business has: **low utilization + short-term demand + high depreciation + high financing costs + falling prices.**

The biggest risk for an AI data center is not simply "not having GPUs." It is:

**having expensive GPUs without enough high-quality, long-term, high-priced demand to fill them.**

# Module 3: Timeline & Risk

## 1. The timeline from capex to revenue

The timeline can be broken into stages:

### A. Customer contract and financing

Before construction, the project needs either customer commitments, financing, or both.

The strongest structure is to secure customer contracts before major capex is committed. The weakest structure is to buy equipment and build capacity speculatively, hoping demand appears later.

### B. Time to power

This is the time required to secure usable power.

It is one of the most important bottlenecks for AI data centers. Having money to buy GPUs does not mean a company can immediately connect to enough power.

[[Layer 4 - Physical#Module 3: Site / Land / Grid Access|Grid interconnection]], substations, transmission lines, transformers, permitting, and utility queues can all slow the timeline.

| Scenario | Approximate timing |
|---|--:|
| Existing powered shell / existing data center | 3-9 months |
| New build, but power is mostly secured | 12-24 months |
| New grid interconnection / grid upgrade / large substation required | 3-5+ years |

### C. Time to build

This is the time required to build the data center. A typical range is 9-24 months, but complex sites can take longer.

It includes land, permitting, construction, mechanical and electrical engineering, [[Layer 4 - Physical#Module 2: Cooling / Thermal System|cooling systems]], [[Layer 4 - Physical#Module 1: Electricity / Power Chain|power systems]], fire protection, security, [[Layer 3 - Computing System#Module 4：Network|networking]], and operational readiness.

### D. Equipment lead time

Equipment delivery can take 6-24 months, depending on market conditions and vendor allocation.

This includes:

- GPU delivery: 3-12 months
- server delivery
- [[Layer 3 - Computing System#Module 4：Network|networking equipment]]
- transformers
- UPS systems
- [[Layer 4 - Physical#Module 2: Cooling / Thermal System|cooling equipment]]
- switchgear and electrical components

Sometimes the GPUs arrive, but the power equipment has not. Or the building is complete, but the transformer is delayed. Or servers arrive, but networking is insufficient. If any critical link is delayed, the overall capacity cannot generate revenue.

### E. Commissioning

Commissioning and acceptance can take 1-6 months.

A data center does not become usable just because equipment is plugged in. It needs testing for power stability, [[Layer 4 - Physical#Cooling capacity|cooling capacity]], failover, network performance, security, and compatibility with customer workloads.

### F. Time to revenue

This is when customer workloads actually go live and begin generating payment. A typical range is 1-6 months after technical readiness, depending on customer onboarding and workload migration.

This is often much later than "construction completion."

| Stage | Fast | Normal | Slow |
|---|--:|--:|--:|
| Customer contract / financing | 1-3 months | 3-6 months | 6-12 months |
| Site / power secured | 3-9 months | 12-24 months | 3-5+ years |
| Data center construction | 6-12 months | 18-24 months | 24-36+ months |
| Critical equipment | 3-9 months | 12-24 months | 24-60 months |
| GPU / server deployment | 1-3 months | 3-9 months | 12-18+ months |
| Commissioning | 1-2 months | 2-4 months | 3-6 months |
| Revenue ramp | 1-3 months | 3-6 months | 6-12 months |

## 2. Depreciation and technical obsolescence risk

The special feature of AI infrastructure is:

**GPUs depreciate quickly, and the technology cycle moves fast.**

If a company buys one generation of GPU and the next generation launches soon after with better performance per watt, market prices may decline.

This creates two risks:

1. Market rental rates for older GPUs fall.
2. The asset may not be fully depreciated on the books, but its economic value has already declined.

This is why AI data centers are different from traditional real estate.

Ordinary data center buildings can be used for a long time, but the economic life of a GPU cluster may be much shorter.

## 3. Customer concentration

If most revenue comes from a small number of customers, the business is fragile.

Examples:

- One customer contributes 60% of revenue.
- One customer does not renew when the contract expires.
- One customer starts building its own capacity.
- One customer demands lower pricing.
- One customer delays workload deployment, leaving capacity idle.

Any of these can affect cash flow, financing capacity, and valuation.

When evaluating GPU cloud or neocloud companies, ask:

- Does revenue depend on a few large customers?
- How long are the contracts?
- Are the contracts take-or-pay or best-efforts?
- Do customers have termination rights?
- Is pricing fixed, indexed, or renegotiable?
- Is the customer using the provider as a bridge until internal capacity is ready?

## 4. Pricing pressure

AI compute prices may decline.

Reasons include:

- Increased GPU supply
- Hyperscaler price cuts
- Improved model inference efficiency
- Better price/performance from new hardware
- Intensifying competition
- Stronger customer bargaining power
- Customers shifting from training bursts to optimized inference workloads

If a company borrows at high rates and buys equipment at high prices, but future rental rates fall, its payback period extends and equity value can compress quickly.

## 5. Power and operating risk

[[Layer 4 - Physical#Module 1: Electricity / Power Chain|Power]] is not just a construction input. It is a long-term operating variable.

Important questions:

- Is power contracted or merely requested?
- Is the interconnection firm or conditional?
- Is the power price fixed, floating, or pass-through?
- Are there curtailment risks?
- Can the site support [[Layer 4 - Physical#Module 2: Cooling / Thermal System|liquid cooling]] or future [[Layer 4 - Physical#kW per rack|higher-density racks]]?
- Who pays for grid upgrades?
- Are there backup power, reliability, or emissions constraints?

For AI infrastructure, power quality and availability can be as important as GPU availability.

## 6. Risk waterfall

The risk stack can be read as a waterfall:

1. **Power risk:** can the site get enough [[Layer 4 - Physical#Module 1: Electricity / Power Chain|power]], on time, at a usable cost?
2. **Construction risk:** can the facility be built on schedule and within budget?
3. **Supply chain risk:** will [[Layer 3 - Computing System#Module 2: Chip/Accelerator|GPUs]], [[Layer 3 - Computing System#Module 4：Network|networking]], transformers, and [[Layer 4 - Physical#Module 2: Cooling / Thermal System|cooling]] arrive on time?
4. **Commissioning risk:** can the [[Layer 3 - Computing System#Main Takeaways|cluster]] operate reliably at target density?
5. **Demand risk:** are [[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Demand Quality Scoring|customers ready to use and pay]] for the capacity?
6. **Utilization risk:** will capacity stay filled over time?
7. **Pricing risk:** will rates remain high enough to earn the target return?
8. **Obsolescence risk:** will new hardware reduce the value of existing GPUs?
9. **Financing risk:** can the project service debt through delays or market changes?

## Core Insight From Module 3

The biggest question for an AI data center is not "can it be built?" It is:

**money is spent before the asset is live; revenue may arrive after a delay; and once revenue begins, pricing and utilization may still be unstable.**

The biggest risks include:

- Demand falling short of expectations
- Insufficient paid utilization
- Customer concentration
- Weak contract quality
- GPU depreciation and obsolescence
- Power interconnection delays
- Construction delays
- Equipment delivery delays
- Price declines
- Rising financing costs

# Module 4: What Makes a Strong AI Data Center Business

A strong AI data center business usually has:

- Scarce, secured power in a good location
- Clear path from power to commissioned capacity
- High-density cooling capability
- Access to GPU supply and critical equipment
- Long-term contracts before major capex is committed
- Creditworthy customers
- Take-or-pay or minimum-revenue commitments
- Pricing that protects against power and financing cost changes
- High paid utilization, not just high technical utilization
- Capex discipline and realistic depreciation assumptions
- Ability to upgrade or repurpose infrastructure over time

A weak AI data center business usually has:

- Speculative capacity without committed customers
- Unsecured or delayed power
- Short-term usage-based demand
- High customer concentration without contract protection
- Expensive financing
- Aggressive residual value assumptions
- Exposure to falling GPU rental prices
- Poor visibility into revenue ramp

# Final Mental Model

AI data centers look like infrastructure, but the GPU layer behaves more like fast-depreciating technology equipment.

The winning projects are not simply the ones with the most GPUs. They are the ones that match scarce power, reliable execution, disciplined financing, and durable customer demand before the hardware loses pricing power.
