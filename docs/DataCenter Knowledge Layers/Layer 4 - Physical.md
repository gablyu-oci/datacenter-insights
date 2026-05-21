# Layer 4: Physical Infrastructure

# Module 1: Electricity / Power Chain

Related layers: [[Layer 3 - Computing System#TDP / power efficiency|chip/rack power demand]], [[Layer 3 - Computing System#Module 3：Server / Rack|rack-scale systems]], [[Layer 5 - Capital and timeline#5. Power and operating risk|power and operating risk]], [[Layer 5 - Capital and timeline#B. Time to power|time to power]]

## Keywords and Concepts
```
Outside the data center:
Utility grid, generation, transmission, substation interconnection

Inside the data center:
Switchgear, transformers, UPS, busway, PDU, rack power, cooling
```
**Electric Grid**: a massive, interconnected network that delivers electricity from power plants to homes and businesses. Because electricity is used the instant it is generated and cannot easily be stored, the grid must constantly balance supply and demand in real-time across three key stages: 
- Generation: Power is produced at facilities like coal, natural gas, nuclear, wind, solar, and hydroelectric plants.
- Transmission: Step-up transformers boost the electricity to high voltages so it can travel efficiently across vast distances on high-voltage power lines.
- Distribution: Substations reduce the voltage, routing the power through smaller lines to your local neighborhood and directly to your home.
> Power plants / generation → high-voltage transmission lines → regional substations → local distribution lines → customers

In the US, there are 3 major interconnected systems:
- Eastern Interconnection
- Western Interconnection
- ERCOT/Texas Interconnection

**Substation**: a facility that controls and changes electricity voltage between parts of the grid
- on the utility side, serving multiple customers or an area, or
- on/near the data center campus, dedicated partly or fully to that data center
A substation usually contains transformers, breakers, switches, protection systems, meters, and control equipment.

**Transformers**: Devices that step voltage up for transmission or step it down for safe use by consumers. In a data center, transformers are used at several layers:
- Grid/substation transformer: Steps high-voltage utility power down to a medium voltage suitable for the data center campus.
- Building-level transformer: Steps medium voltage down for building distribution.
- IT/load transformer or UPS-related transformer: May further condition or adapt power for server racks, cooling systems, pumps, fans, and other equipment.
A transformer changes the relationship between voltage and current. So when voltage goes down, current usually goes up.
```
Power = Voltage × Current
```

**Switchgear**: equipment that controls, protects, and isolates electrical circuits.
- Switchgear can turn power on/off, route power between sources, and automatically disconnect equipment during faults
- In a data center, switchgear is critical because it helps manage power from: 
	- Utility grid
	- Backup generators
	- UPS systems
	- Transformers
	- Cooling equipment
	- Server halls

**UPS**: Uninterruptible Power Supply
- A UPS provides temporary backup power when the main power source fails or becomes unstable
- The UPS usually uses large battery systems, flywheels, or other energy storage.

**PDU**: Power Distribution Unit. Distribute upstream electricity to downstream facilities
- Facility-level PDU: Distributes power from UPS or switchgear to rows or zones of racks
- Rack PDU: Mounted inside the rack. It distributes power to servers, switches, storage, and other IT gear

**Busway**: 母线槽 / 母线系统 a power highway installed above or near rows of racks. Instead of pulling many individual cables to each rack, the data center can run a busway along the row and tap power off wherever needed.
- PDU distributes power. Busway transports large amounts of power across the data hall.

**Rack power shelf**: a rack-level power conversion and distribution module. See also [[Layer 3 - Computing System#Power shelf|Power shelf]] in the computing system layer.

|Component|Main job|Where it usually sits|Think of it as|
|---|---|---|---|
|**Busway**|Carries large power along a row or zone|Above/near rows of racks|Power highway|
|**Rack PDU**|Distributes power inside one rack to IT devices|Inside the rack|Smart power strip / branch distributor|
|**Rack power shelf**|Converts and regulates power for GPU/server trays|Inside AI rack, close to compute trays|Rack-level power supply|
**Power density**: [[Layer 4 - Physical#kW per rack|kW/rack]]

|Rack type|Typical power density|
|---|--:|
|Traditional enterprise rack|3–8 kW/rack|
|Higher-density cloud rack|10–30 kW/rack|
|AI / HPC rack|40–100+ kW/rack|
|Latest liquid-cooled AI rack|100–200+ kW/rack|
**VDC**: Volts Direct Current

**为什么电力成为data center核心瓶颈**：大量、连续、稳定、可快速接入、价格可控、低碳且不扰乱电网的电。This connects directly to [[Layer 5 - Capital and timeline#B. Time to power|time to power]] and [[Layer 5 - Capital and timeline#5. Power and operating risk|power risk]].
1. AI 负载太“吃电”
2. Data center 不能随便停电
3. 真正卡住的是“并网”和“输配电”，不是只差发电量
	1. data center 可以 18–24 个月建好，但电网扩容可能要 4–8 年
4. 电力设备供应链也卡
	1. 数据中心要接入大规模电力，需要大量变压器、开关设备、电缆、冷却设备、电力电子设备。IEA 指出，变压器和电缆等关键设备的交付周期近年明显拉长
5. AI 数据中心选址变成“先找电，再找地”
	1. **power-first site selection**：先看哪里有可用电力，再决定数据中心建在哪里
	2. 这也是为什么一些公司会靠近天然气、核电、水电、可再生能源基地，甚至考虑自建电厂或签长期购电协议。近期行业报道也提到，一些 AI 数据中心因为并网等待时间长，开始考虑现场发电或临时使用自备电源
6. [[Layer 4 - Physical#Module 2: Cooling / Thermal System|冷却]]也让电力需求更复杂：
	1. AI 芯片功率密度高，散热压力大。冷却系统本身也耗电。液冷可以提高效率，但会增加基础设施复杂度。换句话说，AI data center 的电力需求不只是 GPU 本身，还包括GPU/CPU、网络设备、存储、冷却、UPS、配电损耗、备用系统。所以实际要准备的电力容量会比“芯片标称功耗”更大
7. 低碳要求让问题更难
所以电力瓶颈会直接影响**AI 部署速度、[[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Four demand types for AI:|训练规模]]、[[Layer 5 - Capital and timeline#Cost/token|推理成本]]、云服务价格、区域竞争力、能源安全**

## IEA - Energy and AI
Data-centre power demand is rising fast, but the local impact matters more than the global share.
- In 2024, data centres used about 415 TWh, around 1.5% of global electricity consumption. That sounds small globally, but data centres are geographically concentrated, so they can create major local grid stress. The US, China, and Europe dominate current demand.
Demand may more than double by 2030. 
- IEA projects data-centre electricity use could reach around 945 TWh by 2030, slightly more than Japan’s current total electricity consumption. In the US, data centres could account for nearly half of electricity demand growth through 2030.
The bottleneck is not only generation; it is the grid.
- Around 20% of planned data-centre projects could face delays if grid constraints are not addressed. Transmission lines can take 4–8 years to build in advanced economies, and lead times for critical equipment like transformers and cables have doubled in the past three years.
Smarter is faster when it comes to integrating data centres in electricity grids
- Electricity grids are already under strain in many places: we estimate that unless these risks are addressed, around 20% of planned data centre projects could be at risk of delays
- Building new transmission lines can take four to eight years in advanced economies and wait times for critical grid components such as transformers and cables have doubled in the past three years
- Generation equipment is also in high demand. Turbine deliveries for new gas-fired power plants now face lead times of several years, potentially delaying their commissioning beyond 2030.
- Key options to mitigate these risks include locating new data centres in areas of high power and grid availability, and operating either data centre servers or their onsite power generation and storage assets more flexibly.
Renewables and natural gas are likely to carry much of the growth.
- IEA expects renewables to meet about half of global data-centre demand growth, supported by storage and grids. Natural gas also plays a major role, especially in the US. Nuclear and geothermal may contribute too, partly because tech companies are helping bring forward advanced energy projects.
AI energy forecasts are highly uncertain.
- By 2035, IEA’s scenarios range from 700 TWh to 1,700 TWh for data-centre electricity demand. The final number depends on AI adoption, hardware/model efficiency, infrastructure bottlenecks, and how quickly power systems expand.
AI can help the energy sector, not just consume energy.
- IEA highlights uses such as renewable forecasting, grid fault detection, predictive maintenance, methane leak detection, industrial optimization, and smarter building controls. AI-based fault detection could reduce outage durations by 30–50%, and AI tools could unlock up to 175 GW of transmission capacity without building new lines.
The energy sector is underusing AI.
- The report says the sector has barriers: poor data access, limited digital infrastructure, lack of AI skills, cybersecurity concerns, and operational conservatism. In other words, the opportunity is real, but adoption is not automatic
AI is neither a climate disaster nor a climate miracle.
- IEA says fears that AI alone will massively accelerate climate change are probably overstated, but so are claims that AI will solve climate change. Existing AI applications could reduce emissions by an amount equal to around 5% of energy-related emissions in 2035, but that still falls far short of what climate goals require.

## Schneider / Vertiv / Eaton data center power reference designs
| Vendor                 | Reference design emphasis                                                                                                               | Best-fit use case                                                                                                         |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Schneider Electric** | Full-facility, pre-validated **power + cooling + IT layout** designs; strong in EcoStruxure controls and modular/full-site architecture | Owners who want a complete data center blueprint: electrical, mechanical, liquid cooling, room layout, CapEx/PUE planning |
| **Vertiv**             | AI-ready **power + cooling blocks**, retrofit and greenfield designs, rack-density driven design selector                               | Operators upgrading or building AI halls quickly, especially 40–140kW+ rack densities                                     |
| **Eaton**              | “Grid-to-chip” power chain, **800 VDC**, busbar, backup, protection, power distribution                                                 | Future AI factories, megawatt-scale racks, next-gen NVIDIA-style 800 VDC architectures                                    |

| Dimension           | Schneider                                                       | Vertiv                                                  | Eaton                                                         |
| ------------------- | --------------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------- |
| Scope               | Whole facility                                                  | AI power/cooling deployment blocks                      | Power chain / grid-to-chip                                    |
| AI readiness        | Strong; NVIDIA-aligned full-facility and liquid cooling designs | Strong; rack-density and GPU-specific reference designs | Strong but more next-gen; 800 VDC architecture                |
| Retrofit focus      | Yes, especially power-system retrofit guidance                  | Very strong; explicit retrofit design catalog           | More focused on future architectures                          |
| Cooling integration | Strong: liquid cooling + controls                               | Very strong: liquid + air, CDU, heat rejection          | Less cooling-centric; more electrical                         |
| Differentiator      | EcoStruxure + full-site engineering                             | Fast deployable AI infrastructure                       | 800 VDC, busbar, backup, power-burst management               |
| Buying center       | Data center owner, engineering team, EPC                        | Data center operator, colo, hyperscaler, retrofit team  | Electrical architect, power systems team, AI factory planners |
### Schneider Electric
<u>pre-validated blueprints</u> for organizing power, cooling, and IT infrastructure to reduce deployment risk, ensure compatibility, and speed up scalable AI-ready builds
- Its design library includes full-site, modular, prefab, and pod-based designs, with AI designs reaching 100+ kW/rack and full-site examples such as 10–12.4 MW NVIDIA Vera Rubin NVL72 liquid-cooled AI clusters.
complete facility engineering:
- electrical distribution
- mechanical systems
- cooling architecture
- room layout
- IT space planning
- liquid cooling and high-density GPU assumptions
For AI, Schneider is useful when you need to answer questions like:
- How many [[Layer 5 - Capital and timeline#G. MW lease|MW]] can this building or campus support?
- What redundancy tier should we use?
- Can the floor support UPS batteries and high-density racks?
- How do power and [[Layer 4 - Physical#Module 2: Cooling / Thermal System|liquid cooling]] fit together?
- What does the [[Layer 5 - Capital and timeline#Module 1: Capex & Financing|CapEx]] per rack or per kW look like?

Schneider also explicitly highlights controls designs that complement NVIDIA GB200, GB300, and Vera Rubin NVL72 architectures, plus AI liquid cooling designs developed with NVIDIA.

### Vertiv
AI-infra focused design portfolio. AI Hub includes designs organized by rack density, rack count, deployment size, GPU type, and cooling technology
- 20kw to 142kw rack densities
- hundreds of kw to 10mw deployments

### Eaton
Future-facing and power-chain specific design. Grid-to-chip strategy covering power distribution, backup power, digital technologies

Eaton is focused on the next bottleneck: how to deliver very large amounts of power closer to the chip with less conversion loss and less copper/material overhead
## McKinsey - Beyond compute: Infrastructure that powers and cools AI data centers
**Power and cooling equipment are the backbones of data center infrastructure**. Innovations and on-time supply of this technology will become increasingly relevant as the demand for data centers grows

1. Power and cooling are now strategic, not back-office infrastructure
	AI data centers are limited by things like:
	- switchgear
	- transformers
	- UPS
	- busway
	- rack PDUs
	- cooling distribution units
	- liquid cooling
	- commissioning capacity
	- service and maintenance support
	So the “AI infrastructure market” is not only NVIDIA GPUs. It also includes **Schneider, Vertiv, Eaton, ABB, Siemens, Johnson Controls, Trane, Carrier, Delta, Legrand,** and many specialized cooling/power suppliers.
2. Data center demand is scaling extremely fast
3. The investment requirement is massive
	- The AI buildout creates demand not only for chips, but also for electrical equipment, cooling systems, construction, services, and operations.
4. Power, cooling, and IT can no longer be designed separately
5. Time to market is becoming a major buying criterion
	- That is why reference designs, prefab modules, standardized power blocks, and integrated vendor solutions matter. The winner is not just whoever has the best equipment; it is whoever can deliver, commission, and support it fastest.
6. Services become part of the product
	- equipment repair and maintenance, start-up, commissioning, and power/cooling equipment support.
7. Vertical integration opportunities are increasing
	- Vendors that can provide a broader stack may have an advantage
	- Example: 
		- **Schneider**: switchgear, UPS, PDUs, cooling, racks, software, services
		- **Vertiv**: UPS, thermal, liquid cooling, racks, services, prefabricated systems
		- **Eaton**: switchgear, UPS, busway, power distribution, protection, DC architecture
---

# Module 2: Cooling / Thermal System

Related layers: [[Layer 3 - Computing System#Module 3：Server / Rack|rack-scale AI systems]], [[Layer 3 - Computing System#TDP / power efficiency|TDP and power efficiency]], [[Layer 5 - Capital and timeline#5. Power and operating risk|operating risk]]

## Keywords and Concepts
| Method                        | Where heat is captured | Best for                              |
| ----------------------------- | ---------------------- | ------------------------------------- |
| **Air cooling**               | Room / rack airflow    | Lower and moderate density            |
| **Rear-door heat exchanger**  | Rack exhaust air       | Retrofit, hybrid cooling              |
| **Direct-to-chip cold plate** | GPU / CPU package      | High-density AI racks                 |
| **Immersion cooling**         | Whole server submerged | Specialized high-density environments |
| **Heat reuse**                | Facility liquid loop   | Sites near useful heat demand         |
```
Direct-to-chip liquid cooling → GPUs / CPUs
Rear-door or air cooling → memory, power supplies, networking, residual heat
```

![[Pasted image 20260519141226.png]]

**Air cooling**: works fine when rack power is moderate. But air has limited heat-carrying ability. Once racks go from [[Layer 4 - Physical#kW per rack|10–20 kW to 60–100+ kW]], air cooling becomes difficult, loud, inefficient, and space-hungry.
```
Server fans blow hot air
  ↓
Hot aisle
  ↓
CRAH / CRAC unit
  ↓
Chilled air returns to cold aisle
```

**Direct-to-chip liquid cooling**: Instead of relying only on air, liquid is brought directly to the hottest components, usually [[Layer 3 - Computing System#CPU vs GPU vs TPU|GPUs and CPUs]].

**Code Plate**: a metal heat exchanger attached directly to a hot chip, usually GPU or CPU. Liquid flows through tiny channels inside the cold plate. Heat moves from the chip into the metal plate, then into the liquid. 

**manifold**: a distribution block or pipe assembly that splits coolant flow to multiple cold plates and collects it back.
- You can have manifolds inside a server, inside a rack, or at row level

**CDU**: Coolant Distribution Unit (The bridge between server liquid cooling and building cooling)
sits between the IT liquid loop and the facility water loop
```
IT loop: cold plates / racks
        ↓
       CDU
        ↓
Facility loop: building water system
```
The CDU usually does four things:
1. Transfers heat from the IT coolant loop to the facility water loop.
2. Controls coolant temperature.
3. Controls pressure and flow.
4. Helps manage water quality and reliability.

**Facility water loop**: moves heat from CDUs to the larger heat rejection system

**Chiller**: removes heat from water and produces chilled water
- chillers consume significant energy. That is why warm-water cooling is attractive: if the cooling water can run warmer, you may reduce or avoid mechanical chilling for more hours of the year

**Cooling tower / dry cooler**: heat rejection systems. They dump heat from the facility water loop to the outside environment. uses evaporation to reject heat.
- Pros:
	- Very effective
	- Efficient in many climates
- Cons:
	- Uses water
	- Needs water treatment
	- May be harder in water-constrained locations

**Dry cooler**: rejects heat to outside air using coils and fans
- Pros:
	- Uses little or no water
	- Simpler water management
- Cons:
	- Less effective in hot climates
	- May need larger equipment or higher fan power

Cooling tower = rejects heat using water evaporation
Dry cooler = rejects heat using air

**Rear-door heat exchanger (RDHx)**: a cooling door mounted on the back of a rack
- Liquid flows through coils inside the rear door. Hot server exhaust air passes through the door, and the liquid captures the heat.
- Useful when:
	- You want to retrofit existing air-cooled racks.
	- You want to neutralize hot exhaust.
	- You want a hybrid approach with air plus liquid.
	- Not every component is direct-to-chip cooled.
![[Pasted image 20260519140835.png]]

**Immersion cooling**: placing IT hardware into a special non-conductive liquid
- Single-phase immersion: The liquid stays liquid.
- Two-phase immersion: The liquid boils, turns into vapor, condenses, and cycles back
- Immersion can remove a lot of heat, but it changes operations significantly. Maintenance, component compatibility, fluids, warranties, cabling, signal integrity, and service procedures all become more complex.

**Heat reuse**: using waste heat from the data center for another purpose.

## OCP Liquid Distribution Guidance / Reference Designs
![[Pasted image 20260519140035.png]]
![[Pasted image 20260519140236.png]]
![[Pasted image 20260519140319.png]]

## Vertiv / Schneider liquid cooling reference designs
Vertiv:
- focuses on AI-ready, deployable power and cooling blocks
- Portfolio: CDU systems for direct-to-chip and rear-door cooling
- Reference designs:
	- prefabricated high-density AI data centers with direct-to-chip cooling, power train, pipework, head rejection systems
Schneider:
- focuses on reference designs that reduce deployment risk and integrate liquid cooling into broader AI data center architecture
- has NVIDIA-related reference architectures including liquid-to-liquid CDUs and direct-to-chip liquid cooling options

---
# Module 3: Site / Land / Grid Access
AI data center site selection is not real estate-first. It is [[Layer 5 - Capital and timeline#5. Power and operating risk|power-first]], then land, fiber, water, policy, and construction timeline.
For an AI data center, site selection is more like:
```
available power
+ grid interconnection timeline
+ expandable land
+ fiber connectivity
+ water / cooling feasibility
+ permits and zoning
+ tax incentives
+ customer / energy proximity
+ long-term power cost
```
##  Keywords and Concepts
Land: Can this land support multiple phases of expansion over 5–10 years?

**Power availability**:
- How many MW can the utility actually serve?
- Is the capacity available now or only after upgrades?
- Is the power firm or interruptible?
- What is the electricity price?
- What is the carbon profile?

**Grid interconnection queue**: the waiting line to connect a new large load or generation project to the power grid. This is one driver of [[Layer 5 - Capital and timeline#B. Time to power|time to power]].
- Common mismatch:
	- Data center building: 18–30 months
	- Grid upgrades: 3–7+ years

**Substation proximity**: reduce interconnection cost, transmission/feeder buildout, line losses, construction complexity, permitting burden
- Bad: far from grid and no capacity
- Better: near substation
- Best: near expandable substation with available capacity and fast utility approval

**Fiber connectivity**: for cloud connectivity, customer access, data movement, [[Layer 3 - Computing System#Module 4：Network|networking]], low-latency services, backup and replication

**[[Layer 3 - Computing System#Module 1: Workload|Training-heavy vs Inference]]/cloud/enterprise:**
- Training sites can move closer to power
- Inference sites often need to stay closer to users and network hubs

**Water availability**: for cooling and heat rejection

**Permitting**: government approvals. Permitting can kill speed.
- building construction
- electrical interconnection
- substation
- backup generators
- air emissions
- water use
- noise
- stormwater
- environmental impact
- fire safety
- road access

**Zoning**: determines whether a data center is legally allowed on the land

**Tax incentives**: sales tax exemptions, property tax, equipment tax, energy tax, job creation, special econ zone benefits...

**PPA**: Power Purchase Agreement
- a long-term contract to buy electricity, often from renewable energy projects such as wind or solar.
- Data center companies use PPAs to:
```
lock in long-term energy price
support renewable energy goals
claim clean energy procurement
finance new renewable projects
hedge electricity market volatility
```

**Customer proximity**: means being near the users or customers who need the compute.
This matters more for:
```
inference
financial services
enterprise workloads
content delivery
hybrid cloud
regulated workloads
```
It matters less for:
```
large batch training
offline model training
some internal AI workloads
```
So there are two site-selection models:
- <u>Customer-proximity model</u>
```
near major metro
near enterprises
low latency
rich fiber ecosystem
expensive land/power
```
- <u>Energy-proximity model</u>
```
near cheap power
near generation
large land
better expansion
possibly farther from users
```
AI training pushes the industry toward energy-proximity. AI inference pulls some demand back toward customer proximity. This maps back to [[Layer 1 - AI Demand (Application, model, inference, enterprise procurement)#Four demand types for AI:|demand type]].

## How a developer actually evaluates sites
- Stage 1: Power screen
	- How many MW are available?  
	- When?  
	- At what voltage?  
	- At what price?  
	- Can it expand?  
	- What grid upgrades are required?
- Stage 2: Land screen
	- Is the parcel large enough?
	- Can it support phased expansion?
	- Is the land buildable?
	- Any flood, seismic, environmental, or access issues?
- Stage 3: Fiber screen
	- Are there multiple fiber providers?
	- Can we get diverse routes?
	- Is latency acceptable?
	- Can we connect to cloud/network ecosystems?
- Stage 4: Cooling/water screen
	- Can we cool 50–150 kW racks?
	- Is water available?
	- Can we use dry cooling?
	- What happens during summer peaks?
- Stage 5: Policy screen
	- Zoning allowed?
	- Permitting timeline?
	- Tax incentives?
	- Community support?
	- Environmental constraints?
- Stage 6: Commercial screen
	- Can customers commit?
	- Can we sign PPAs?
	- Can we finance the project?
	- Can construction happen fast enough?

<u>Tradeoffs:</u>

|Site type|Strength|Weakness|
|---|---|---|
|Major metro|Fiber, customers, low latency|Expensive, power constrained, permitting harder|
|Rural power-rich area|Cheap land, energy proximity, expansion|Fiber may be weaker, customer distance, labor constraints|
|Industrial zone|Zoning, power infrastructure, community acceptance|Competition for grid capacity|
|Renewable-rich area|Cleaner energy, PPA potential|Intermittency, transmission constraints|
|Gas/nuclear/hydro-adjacent site|Reliable large-scale power|Permitting, politics, fuel/carbon issues|
|Existing data center hub|Ecosystem, fiber, talent|Grid queues, land scarcity, congestion|
Framework:
1. Power now: can I launch phase 1?
2. Power later: can this become a full AI campus?
3. Interconnection timeline
4. Land for expansion
5. Fiber
6. Cooling / water
7. Permitting / zoning
8. Energy cost and carbon profile
9. Tax incentives
10. Customer fit
---

# Module 4: Engineering / Construction / Capacity Delivery
## Keywords and Concepts
Delivery chain:
```
Design
  ↓
EPC selection
  ↓
Procurement
  ↓
Long-lead equipment ordering
  ↓
Site work and construction
  ↓
Modular / phased build
  ↓
Fit-out
  ↓
Commissioning
  ↓
Capacity delivery
  ↓
Customer goes live
  ↓
Revenue starts
```

The last two steps connect directly to [[Layer 5 - Capital and timeline#E. Commissioning|commissioning]] and [[Layer 5 - Capital and timeline#F. Time to revenue|time to revenue]].

Design: turns a customer demand, like 100 MW of AI capacity, into an engineering plan.
- How many MW?
- What rack density?
- Air cooling or liquid cooling?
- What redundancy level?
- How many data halls?
- What power architecture?
- What cooling architecture?
- What phasing plan?
- What customer requirements?

EPC: Engineering, Procurement, and Construction
- Engineering: detailed technical design
- Procurement: buying equipment and materials
- Construction: building and installing everything

Procurement: buying all the major equipment needed to build and operate the data center.

**Long-lead equipment**: means equipment that must be ordered far in advance because manufacturing and delivery take a long time.

**Modular build**: using pre-engineered or prefabricated blocks instead of building everything custom on site.

**Phased deployment** means the data center is delivered in stages.
Campus target: 300 MW
Phase 1: 48 MW
Phase 2: 72 MW
Phase 3: 120 MW
Phase 4: 60 MW

**Fit-out** means turning the building and data halls into usable customer space.

**Commissioning** means testing and proving that the facility works as designed before customers go live. See [[Layer 5 - Capital and timeline#E. Commissioning|commissioning risk]].

**Capacity delivery** means the developer hands over usable IT capacity.

**Time to power** means how long it takes to get usable electricity to the site or data hall. See also [[Layer 5 - Capital and timeline#B. Time to power|Layer 5 time to power]].
```
Site selected
  ↓
utility agreement
  ↓
substation / grid upgrades
  ↓
transformers installed
  ↓
switchgear installed
  ↓
UPS / generators ready
  ↓
data hall energized
```

**Time to revenue** means how long it takes from project start or capital spend to customer billing. See also [[Layer 5 - Capital and timeline#F. Time to revenue|Layer 5 time to revenue]].
```
Capital spent
  ↓
construction
  ↓
equipment delivery
  ↓
commissioning
  ↓
customer install
  ↓
go-live
  ↓
revenue
```
---

# Module 5: Operations / Reliability
## Keywords and Concepts

**Tier I/II/III/IV**: increasing levels of infrastructure reliability.

|Tier|Simple meaning|Key idea|
|---|---|---|
|**Tier I**|Basic capacity|Basic power, cooling, and IT space, but limited redundancy|
|**Tier II**|Some redundancy|Redundant capacity components, but still limited path redundancy|
|**Tier III**|Concurrently maintainable|Equipment can be maintained without shutting down IT load|
|**Tier IV**|Fault tolerant|A single failure should not interrupt IT operations|

**N, N+1, and 2N redundancy**: 
- N means exactly enough capacity
- N+1 means enough capacity plus one spare component
- 2N means two complete independent systems
- For AI data centers, redundancy is critical because GPU clusters are highly sensitive to power, cooling, and network interruptions

**Uptime**: the system is available and operating as expected

**SLA**: Service Level Agreement. 
- availability target
- response time
- recovery expectation
- planned maintenance rules
- customer communication process
- penalties or service credits

**Training workloads**
Training jobs often:
- run for a long time
- consume many GPUs
- require [[Layer 3 - Computing System#Module 4：Network|high-speed networking]]
- depend on distributed coordination
- generate expensive [[Layer 5 - Capital and timeline#C. GPU-hour|GPU-hour]] costs
- rely on [[Layer 3 - Computing System#Training storage|checkpointing]] for recovery
If a training job is interrupted, the cost is not just the outage duration.
The real cost may include:
```
lost GPU-hours
checkpoint rollback
job restart time
queue delays
engineering investigation
missed model delivery timeline
lower cluster utilization
```

For training, reliability depends on:
- stable power
- stable cooling
- reliable networking
- good checkpoint strategy
- failure-domain isolation
- scheduler resilience
- spare capacity
- fast incident response
A short facility issue can waste a large amount of compute time.

**Inference workloads**
Inference workloads are different.
They are usually:
- customer-facing
- latency-sensitive
- revenue-generating
- tied to enterprise SLAs
- exposed through APIs
- expected to scale with demand
If inference goes down, the impact can be immediate:

```
API failures
customer application outages
SLA violations
service credits
lost revenue
enterprise escalations
trust damage
```
For inference, reliability depends on:
- multi-zone or multi-region design
- load balancing
- automatic failover
- [[Layer 5 - Capital and timeline#D. Reserved capacity|capacity reservation]]
- autoscaling
- observability
- graceful degradation
- fast customer communication

Training interruptions waste compute. Inference interruptions affect customers directly.

**Data center reliability has three layers:**
1. Physical infrastructure reliability
   Power, cooling, space, network, security, fire protection
2. Operational reliability
   People, process, maintenance, monitoring, runbooks, incident response
3. Service reliability
   SLA, customer availability, API uptime, training continuity, revenue impact

---

# Module 6: Physical Metrics / Unit Economics Bridge
## Core idea

AI infrastructure economics start with physical constraints.
Before GPUs can generate revenue, the data center must provide:
```
power
cooling
rack capacity
networking
reliability
operations
```
So the key mental model is:
```
Physical capacity → Deployable compute → Utilization → Revenue
Physical inefficiency → Higher cost → Lower margin
```

See also: [[Layer 5 - Capital and timeline#2. Utilization is the core of the economics|utilization]] and [[Layer 5 - Capital and timeline#Module 2: Revenue & Utilization|revenue]].

Layer 4 is the precondition for Layer 5.
```
Layer 4 = physical data center infrastructure
Layer 5 = compute / cloud / AI service monetization
```

See also: [[Layer 5 - Capital and timeline#Layer 5: Capital, Revenue, Timeline, and Risk|Layer 5 monetization]].
## What to read
1. **IEA Energy and AI**  
    Focus on electricity demand, grid constraints, and how AI increases data center power needs.
2. **McKinsey Beyond Compute**  
    Focus on power, cooling, equipment lead times, and infrastructure bottlenecks.
3. **Data center operator investor materials**  
    Focus on MW capacity, leased capacity, CapEx per MW, utilization, and time to power.
4. **Schneider / Vertiv calculators or reference designs**  
    Focus on rack density, cooling design, power architecture, and cost assumptions.
## Key metrics

### MW / IT load
MW measures how much power is available for IT equipment such as servers, GPUs, [[Layer 3 - Computing System#Module 5：Storage / Data Pipeline|storage]], and [[Layer 3 - Computing System#Module 4：Network|networking]].
```
1 MW = 1,000 kW
```

Economic meaning:

```
More MW → more deployable compute → more revenue potential
```
### PUE

PUE measures total facility power relative to IT power.

```
PUE = Total facility power / IT equipment power
```
Example:
```
100 MW IT load
PUE = 1.2
Total facility power = 120 MW
```
Economic meaning:
```
Lower PUE → lower electricity cost → better margin
```
### WUE
WUE measures water consumed per unit of IT energy.
```
WUE = water used / IT energy
```
Economic meaning:
```
Higher WUE → more water cost, permitting risk, and sustainability risk
```

### kW per rack
kW/rack measures rack power density.
Example:
```
1 MW = 1,000 kWAt 20 kW/rack → 50 racksAt 100 kW/rack → 10 racks
```
Economic meaning:
```
1 MW = 1,000 kW
At 20 kW/rack → 50 racks
At 100 kW/rack → 10 racks
```
High-density AI racks may require liquid cooling.
### Cooling capacity
Nearly all IT power becomes heat.
```
1 MW IT load ≈ 1 MW heat to remove
```
Economic meaning:
```
Insufficient cooling → throttling, downtime, lower utilization, SLA risk
```
Cooling capacity determines whether compute can actually run at full performance.

### CapEx per MW
CapEx per MW measures how much [[Layer 5 - Capital and timeline#Module 1: Capex & Financing|capital]] is needed to build one MW of data center capacity.
It includes items such as:
```
land
building
electrical systems
cooling systems
UPS
generators
substation
power distribution
fit-out
```
Economic meaning:
```
CapEx per MW → upfront investment → return profile
```
Example
```
100 MW × $10M/MW = $1B facility CapEx
```
### Time to power
Time to power is how long it takes to secure and energize power for the site. See also [[Layer 5 - Capital and timeline#B. Time to power|Layer 5: Time to power]].
It depends on:
```
utility interconnection
substation construction
transformers
permits
grid upgrades
power contracts
```
Economic meaning:
```
Time to power = time to revenue
```
If power is delayed, compute deployment and revenue are delayed.
### Utilization
Utilization measures how much available capacity is actually used. See also [[Layer 5 - Capital and timeline#2. Utilization is the core of the economics|Layer 5 utilization economics]].
Economic meaning:
```
Low utilization → wasted capital
High utilization → better economics, but less headroom
```
You still need spare capacity for maintenance, failover, and demand spikes.
### Uptime
Uptime measures service availability.
Economic meaning:
```
Higher uptime → stronger SLA performance, customer trust, and revenue retention
Lower uptime → SLA penalties, customer escalation, and churn risk
```
For AI:
```
Training downtime wastes GPU-hours.
Inference downtime impacts customers and API revenue.
```

See also: [[Layer 5 - Capital and timeline#C. GPU-hour|GPU-hours]] and [[Layer 2 - Computing product#2.1 Token-based API|API revenue]].
### Electricity cost
Electricity cost is a major operating cost.
Formula:
```
Annual electricity cost =
IT load MW × 8,760 hours × PUE × electricity price per MWh
```
Example:
```
20 MW IT load
PUE = 1.25
Electricity price = $80/MWh

Annual electricity cost =
20 × 8,760 × 1.25 × 80
= $17.52M
```
Economic meaning:
```
Higher electricity cost → higher cost of revenue → lower margin
```

Physical metric → economic impact

|Physical metric|Economic impact|
|---|---|
|MW / IT load|Determines deployable compute capacity|
|PUE|Impacts total electricity cost|
|WUE|Impacts water cost and permitting risk|
|kW/rack|Determines cooling and rack design|
|Cooling capacity|Determines usable compute performance|
|CapEx per MW|Determines capital intensity|
|Time to power|Determines revenue start date|
|Utilization|Determines monetized capacity|
|Uptime|Determines SLA performance and customer trust|
|Electricity cost|Determines operating margin|
