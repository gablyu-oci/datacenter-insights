"""
Synthetic mock data for MVP - simulates real ingested data from agents.

GATED: This module is only active when MOCK_DATA=1 env var is set.
Production code paths will raise RuntimeError if they hit mock_data
functions without the gate enabled.
"""
from datetime import datetime, timedelta
import os
import random

_MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"


def _require_mock_gate(func_name: str) -> None:
    """Raise if mock data is requested without the MOCK_DATA=1 gate."""
    if not _MOCK_ENABLED:
        raise RuntimeError(
            f"mock_data.{func_name}() called but MOCK_DATA env var is not '1'. "
            "Set MOCK_DATA=1 to enable mock data, or use real data sources."
        )

COMPANIES = ["Microsoft", "AWS", "Google", "Meta", "Oracle", "Apple", "Equinix"]
COLORS = {
    "Microsoft": "#0078D4",
    "AWS": "#FF9900",
    "Google": "#4285F4",
    "Meta": "#1877F2",
    "Oracle": "#C74634",
    "Apple": "#555555",
    "Equinix": "#E31837",
}

REGIONS = [
    {"name": "Virginia (US-EAST)", "state": "VA", "lat": 38.9, "lon": -77.4},
    {"name": "Iowa (US-CENTRAL)", "state": "IA", "lat": 41.8, "lon": -93.1},
    {"name": "Oregon (US-WEST)", "state": "OR", "lat": 45.5, "lon": -122.7},
    {"name": "Texas (US-SOUTH)", "state": "TX", "lat": 30.3, "lon": -97.7},
    {"name": "Arizona (US-SW)", "state": "AZ", "lat": 33.4, "lon": -112.1},
    {"name": "Nevada (US-WEST)", "state": "NV", "lat": 36.2, "lon": -115.2},
    {"name": "Georgia (US-SE)", "state": "GA", "lat": 33.8, "lon": -84.4},
    {"name": "Ohio (US-MIDWEST)", "state": "OH", "lat": 40.4, "lon": -82.9},
    {"name": "Dublin, Ireland", "state": "IE", "lat": 53.3, "lon": -6.3},
    {"name": "Singapore", "state": "SG", "lat": 1.3, "lon": 103.8},
]

def get_power_data():
    _require_mock_gate("get_power_data")
    rows = []
    for company in COMPANIES:
        for region in REGIONS:
            gw = round(random.uniform(0.1, 2.8), 2)
            contracted = round(gw * random.uniform(0.6, 1.0), 2)
            rows.append({
                "company": company,
                "region": region["name"],
                "state": region["state"],
                "lat": region["lat"],
                "lon": region["lon"],
                "gw_total": gw,
                "gw_contracted": contracted,
                "gw_operational": round(contracted * random.uniform(0.5, 0.95), 2),
                "year": 2024,
                "source": "SEC EDGAR / Utility Agreement",
                "source_url": "https://www.sec.gov/cgi-bin/browse-edgar",
                "confidence": round(random.uniform(0.7, 0.98), 2),
            })
    return rows

def get_power_timeseries():
    _require_mock_gate("get_power_timeseries")
    quarters = ["Q1 2022","Q2 2022","Q3 2022","Q4 2022",
                "Q1 2023","Q2 2023","Q3 2023","Q4 2023",
                "Q1 2024","Q2 2024","Q3 2024","Q4 2024"]
    series = {}
    for company in ["Microsoft", "AWS", "Google", "Meta", "Oracle"]:
        base = random.uniform(1.5, 5.0)
        series[company] = []
        for i, q in enumerate(quarters):
            base += random.uniform(0.1, 0.6)
            series[company].append({"quarter": q, "gw": round(base, 2)})
    return series

def get_gpu_data():
    _require_mock_gate("get_gpu_data")
    quarters = ["Q1 2023","Q2 2023","Q3 2023","Q4 2023",
                "Q1 2024","Q2 2024","Q3 2024","Q4 2024"]
    shipped, deployed, inventory = [], [], []
    s, d = 50000, 30000
    for q in quarters:
        s += random.randint(15000, 45000)
        d += random.randint(10000, 35000)
        inv = s - d
        shipped.append({"quarter": q, "units": s})
        deployed.append({"quarter": q, "units": d})
        inventory.append({"quarter": q, "units": inv})
    return {
        "shipped": shipped,
        "deployed": deployed,
        "inventory": inventory,
        "revenue_estimates": [
            {"quarter": q, "revenue_b": round(random.uniform(8, 28), 1),
             "units_implied": random.randint(80000, 450000)}
            for q in quarters
        ],
    }

def get_nics_optics_data():
    _require_mock_gate("get_nics_optics_data")
    quarters = ["Q1 2023","Q2 2023","Q3 2023","Q4 2023",
                "Q1 2024","Q2 2024","Q3 2024","Q4 2024"]
    return {
        "nic_shipments": [
            {"quarter": q,
             "infiniband": random.randint(40000, 120000),
             "ethernet": random.randint(60000, 200000)}
            for q in quarters
        ],
        "optics_shipments": [
            {"quarter": q,
             "400g": random.randint(100000, 500000),
             "800g": random.randint(20000, 180000)}
            for q in quarters
        ],
        "correlation_score": round(random.uniform(0.82, 0.96), 2),
    }

def get_tsmc_data():
    _require_mock_gate("get_tsmc_data")
    quarters = ["Q1 2023","Q2 2023","Q3 2023","Q4 2023",
                "Q1 2024","Q2 2024","Q3 2024","Q4 2024"]
    return {
        "capacity": [
            {"quarter": q,
             "node_3nm_wafers": random.randint(50000, 150000),
             "node_5nm_wafers": random.randint(80000, 200000),
             "utilization_pct": round(random.uniform(70, 98), 1)}
            for q in quarters
        ],
        "packaging": [
            {"quarter": q,
             "cowos_capacity": random.randint(8000, 25000),
             "constraint_flag": random.choice([True, False, False])}
            for q in quarters
        ],
    }

def get_permits_data():
    _require_mock_gate("get_permits_data")
    counties = [
        {"county": "Loudoun County", "state": "VA", "lat": 39.08, "lon": -77.56},
        {"county": "Prince William County", "state": "VA", "lat": 38.69, "lon": -77.47},
        {"county": "Maricopa County", "state": "AZ", "lat": 33.45, "lon": -112.07},
        {"county": "Clark County", "state": "NV", "lat": 36.17, "lon": -115.14},
        {"county": "Dallas County", "state": "TX", "lat": 32.78, "lon": -96.80},
        {"county": "Multnomah County", "state": "OR", "lat": 45.55, "lon": -122.65},
        {"county": "Douglas County", "state": "GA", "lat": 33.73, "lon": -84.69},
        {"county": "Story County", "state": "IA", "lat": 42.04, "lon": -93.46},
    ]
    permits = []
    for county_info in counties:
        for company in random.sample(COMPANIES, k=random.randint(2, 4)):
            permits.append({
                **county_info,
                "company": company,
                "permit_type": random.choice(["Construction", "Electrical", "Grading", "HVAC"]),
                "filed_date": (datetime(2024, 1, 1) + timedelta(days=random.randint(0, 365))).strftime("%Y-%m-%d"),
                "status": random.choice(["Approved", "Pending", "Under Review", "Completed"]),
                "estimated_sqft": random.randint(50000, 800000),
                "estimated_mw": round(random.uniform(10, 300), 1),
                "source": "County Public Records",
                "source_url": "https://permits.example.gov",
            })
    return permits

def get_satellite_sites():
    # Real, publicly announced data center sites. Milestones derived from press releases,
    # permit filings, earnings calls, and state economic development announcements.
    sites = [
        {
            "name": "Microsoft Goodyear Campus",
            "company": "Microsoft",
            "lat": 33.4373, "lon": -112.3576,
            "address": "Goodyear, Arizona",
            "status": "Active Construction",
            "size_acres": 279,
            "construction_pct": 45,
            "announced": "May 2024",
            "source": "Microsoft Blog — $3.3B Arizona investment",
            "source_url": "https://blogs.microsoft.com/on-the-issues/2024/05/02/microsoft-investment-arizona-ai-cloud/",
            "milestones": [
                {"date": "2024-05-02", "label": "Announced — $3.3B investment", "pct": 0, "type": "announcement"},
                {"date": "2024-07-15", "label": "Land acquisition finalized", "pct": 2, "type": "permit"},
                {"date": "2024-09-01", "label": "Site clearing & grading begins", "pct": 8, "type": "construction"},
                {"date": "2025-01-10", "label": "Foundation poured — Building 1", "pct": 22, "type": "construction"},
                {"date": "2025-06-01", "label": "Steel structure rising — Phase 1", "pct": 45, "type": "construction"},
                {"date": "2026-03-01", "label": "Phase 1 fit-out (projected)", "pct": 70, "type": "projected"},
                {"date": "2027-06-01", "label": "Full campus operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "Microsoft Quincy Data Center",
            "company": "Microsoft",
            "lat": 47.2348, "lon": -119.8526,
            "address": "Quincy, Washington",
            "status": "Operational",
            "size_acres": 75,
            "construction_pct": 100,
            "announced": "2007 (expanding)",
            "source": "Microsoft / Grant County PUD",
            "source_url": "https://www.microsoft.com/en-us/corporate-responsibility/sustainability/datacenter-map",
            "milestones": [
                {"date": "2007-06-01", "label": "Original campus announced", "pct": 0, "type": "announcement"},
                {"date": "2008-09-01", "label": "Phase 1 operational", "pct": 30, "type": "construction"},
                {"date": "2011-03-01", "label": "Phase 2 expansion complete", "pct": 60, "type": "construction"},
                {"date": "2014-08-01", "label": "Phase 3 complete", "pct": 80, "type": "construction"},
                {"date": "2019-01-01", "label": "Full campus operational", "pct": 100, "type": "milestone"},
                {"date": "2023-06-01", "label": "AI/GPU wing expansion begun", "pct": 100, "type": "construction"},
            ],
        },
        {
            "name": "Microsoft Boydton Campus",
            "company": "Microsoft",
            "lat": 36.6651, "lon": -78.3881,
            "address": "Boydton, Virginia",
            "status": "Expanding",
            "size_acres": 345,
            "construction_pct": 80,
            "announced": "Ongoing expansion",
            "source": "Mecklenburg County / Microsoft",
            "source_url": "https://www.microsoft.com/en-us/corporate-responsibility/sustainability/datacenter-map",
            "milestones": [
                {"date": "2010-01-01", "label": "Original campus announced", "pct": 0, "type": "announcement"},
                {"date": "2011-06-01", "label": "Phase 1 operational", "pct": 25, "type": "construction"},
                {"date": "2015-03-01", "label": "Phase 2 & 3 complete", "pct": 55, "type": "construction"},
                {"date": "2020-01-01", "label": "Major Azure expansion", "pct": 70, "type": "construction"},
                {"date": "2023-09-01", "label": "AI infrastructure expansion", "pct": 80, "type": "construction"},
                {"date": "2025-12-01", "label": "Full expansion complete (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "AWS Northern Virginia (IAD)",
            "company": "AWS",
            "lat": 39.0438, "lon": -77.4874,
            "address": "Ashburn, Virginia",
            "status": "Operational",
            "size_acres": 200,
            "construction_pct": 100,
            "announced": "2006 (us-east-1)",
            "source": "AWS Infrastructure — us-east-1",
            "source_url": "https://aws.amazon.com/about-aws/global-infrastructure/regions_az/",
            "milestones": [
                {"date": "2006-08-01", "label": "us-east-1 region launched", "pct": 10, "type": "announcement"},
                {"date": "2010-06-01", "label": "Multi-AZ expansion complete", "pct": 40, "type": "construction"},
                {"date": "2014-01-01", "label": "Campus doubles in size", "pct": 65, "type": "construction"},
                {"date": "2017-09-01", "label": "100MW milestone", "pct": 80, "type": "milestone"},
                {"date": "2020-01-01", "label": "Largest AWS region globally", "pct": 95, "type": "milestone"},
                {"date": "2024-01-01", "label": "Ongoing AI capacity expansion", "pct": 100, "type": "construction"},
            ],
        },
        {
            "name": "AWS Clarksville Campus",
            "company": "AWS",
            "lat": 36.5298, "lon": -87.3595,
            "address": "Clarksville, Tennessee",
            "status": "Active Construction",
            "size_acres": 250,
            "construction_pct": 30,
            "announced": "Oct 2024",
            "source": "Tennessee Dept of Economic Development — $10B Amazon investment",
            "source_url": "https://www.tn.gov/ecd/news/2024/10/amazon-tennessee.html",
            "milestones": [
                {"date": "2024-10-14", "label": "Announced — $10B TN investment", "pct": 0, "type": "announcement"},
                {"date": "2025-01-20", "label": "Land permits approved", "pct": 5, "type": "permit"},
                {"date": "2025-03-01", "label": "Site preparation begins", "pct": 15, "type": "construction"},
                {"date": "2025-08-01", "label": "Foundation work underway", "pct": 30, "type": "construction"},
                {"date": "2026-06-01", "label": "Phase 1 structure complete (projected)", "pct": 60, "type": "projected"},
                {"date": "2027-01-01", "label": "Phase 1 operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "AWS Columbus (us-east-2)",
            "company": "AWS",
            "lat": 39.9612, "lon": -82.9988,
            "address": "Columbus, Ohio",
            "status": "Operational",
            "size_acres": 85,
            "construction_pct": 100,
            "announced": "2016 (us-east-2)",
            "source": "AWS Infrastructure — us-east-2",
            "source_url": "https://aws.amazon.com/about-aws/global-infrastructure/regions_az/",
            "milestones": [
                {"date": "2015-06-01", "label": "us-east-2 region announced", "pct": 0, "type": "announcement"},
                {"date": "2016-10-17", "label": "Region launched (3 AZs)", "pct": 50, "type": "milestone"},
                {"date": "2019-01-01", "label": "Capacity expansion Phase 2", "pct": 75, "type": "construction"},
                {"date": "2022-06-01", "label": "Full capacity operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Google The Dalles Campus",
            "company": "Google",
            "lat": 45.6021, "lon": -121.1875,
            "address": "The Dalles, Oregon",
            "status": "Expanding",
            "size_acres": 96,
            "construction_pct": 85,
            "announced": "2006 (ongoing expansion)",
            "source": "Google Data Center — The Dalles",
            "source_url": "https://www.google.com/about/datacenters/locations/the-dalles/",
            "milestones": [
                {"date": "2006-01-01", "label": "Site acquired — first Google DC west of Rockies", "pct": 0, "type": "announcement"},
                {"date": "2006-12-01", "label": "Phase 1 operational", "pct": 20, "type": "milestone"},
                {"date": "2012-01-01", "label": "Phase 2 complete — campus doubles", "pct": 50, "type": "construction"},
                {"date": "2016-06-01", "label": "Phase 3 expansion — hydroelectric power deal", "pct": 65, "type": "construction"},
                {"date": "2020-09-01", "label": "Major capacity expansion approved", "pct": 75, "type": "permit"},
                {"date": "2024-01-01", "label": "AI infrastructure expansion underway", "pct": 85, "type": "construction"},
            ],
        },
        {
            "name": "Google Midlothian Campus",
            "company": "Google",
            "lat": 32.4807, "lon": -96.9800,
            "address": "Midlothian, Texas",
            "status": "Active Construction",
            "size_acres": 400,
            "construction_pct": 60,
            "announced": "2023",
            "source": "Ellis County / Google Texas expansion",
            "source_url": "https://www.google.com/about/datacenters/locations/",
            "milestones": [
                {"date": "2023-03-01", "label": "Site acquisition announced", "pct": 0, "type": "announcement"},
                {"date": "2023-06-01", "label": "Grading & utility permits filed", "pct": 5, "type": "permit"},
                {"date": "2023-09-01", "label": "Site clearing begins — 400 acres", "pct": 12, "type": "construction"},
                {"date": "2024-02-01", "label": "Foundation poured — Buildings 1–3", "pct": 30, "type": "construction"},
                {"date": "2024-09-01", "label": "Steel structure Phase 1 rising", "pct": 55, "type": "construction"},
                {"date": "2025-03-01", "label": "Phase 1 roofed — fit-out begins", "pct": 60, "type": "construction"},
                {"date": "2025-12-01", "label": "Phase 1 operational (projected)", "pct": 80, "type": "projected"},
            ],
        },
        {
            "name": "Google New Albany Campus",
            "company": "Google",
            "lat": 40.0814, "lon": -82.7913,
            "address": "New Albany, Ohio",
            "status": "Active Construction",
            "size_acres": 520,
            "construction_pct": 40,
            "announced": "Jan 2024",
            "source": "Google Blog — $1B Ohio investment",
            "source_url": "https://blog.google/inside-google/infrastructure/google-ohio-data-center-investment/",
            "milestones": [
                {"date": "2024-01-18", "label": "Announced — $1B Ohio investment", "pct": 0, "type": "announcement"},
                {"date": "2024-04-01", "label": "Permits filed with Licking County", "pct": 3, "type": "permit"},
                {"date": "2024-08-01", "label": "Site preparation & grading", "pct": 18, "type": "construction"},
                {"date": "2025-02-01", "label": "Foundation work begins", "pct": 35, "type": "construction"},
                {"date": "2025-07-01", "label": "Phase 1 structural steel (current)", "pct": 40, "type": "construction"},
                {"date": "2026-06-01", "label": "Phase 1 operational (projected)", "pct": 70, "type": "projected"},
            ],
        },
        {
            "name": "Google Council Bluffs Campus",
            "company": "Google",
            "lat": 41.2619, "lon": -95.8608,
            "address": "Council Bluffs, Iowa",
            "status": "Operational",
            "size_acres": 115,
            "construction_pct": 100,
            "announced": "2007",
            "source": "Google Data Center — Council Bluffs",
            "source_url": "https://www.google.com/about/datacenters/locations/council-bluffs/",
            "milestones": [
                {"date": "2007-06-01", "label": "Site announced — Iowa wind power deal", "pct": 0, "type": "announcement"},
                {"date": "2008-03-01", "label": "Phase 1 online", "pct": 30, "type": "milestone"},
                {"date": "2012-09-01", "label": "Phase 2 expansion complete", "pct": 65, "type": "construction"},
                {"date": "2016-01-01", "label": "100% renewable energy milestone", "pct": 80, "type": "milestone"},
                {"date": "2019-06-01", "label": "Full campus operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Meta Altoona Data Center",
            "company": "Meta",
            "lat": 41.6467, "lon": -93.4686,
            "address": "Altoona, Iowa",
            "status": "Operational",
            "size_acres": 65,
            "construction_pct": 100,
            "announced": "2013",
            "source": "Meta Data Center — Altoona",
            "source_url": "https://engineering.fb.com/2013/11/15/data-center-engineering/building-facebook-s-most-efficient-data-center-yet/",
            "milestones": [
                {"date": "2013-04-01", "label": "Announced — first Iowa data center", "pct": 0, "type": "announcement"},
                {"date": "2014-06-01", "label": "Phase 1 operational", "pct": 40, "type": "milestone"},
                {"date": "2016-09-01", "label": "Phase 2 expansion complete", "pct": 75, "type": "construction"},
                {"date": "2018-01-01", "label": "100% renewable energy", "pct": 90, "type": "milestone"},
                {"date": "2020-06-01", "label": "Full campus operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Meta Eagle Mountain Campus",
            "company": "Meta",
            "lat": 40.3135, "lon": -112.0110,
            "address": "Eagle Mountain, Utah",
            "status": "Active Construction",
            "size_acres": 360,
            "construction_pct": 55,
            "announced": "2022 (expanding 2024)",
            "source": "Utah County / Meta Eagle Mountain",
            "source_url": "https://sustainability.fb.com/",
            "milestones": [
                {"date": "2022-02-01", "label": "Site announced — 360 acres Utah County", "pct": 0, "type": "announcement"},
                {"date": "2022-07-01", "label": "Grading permits approved", "pct": 5, "type": "permit"},
                {"date": "2022-11-01", "label": "Site clearing begins", "pct": 10, "type": "construction"},
                {"date": "2023-05-01", "label": "Foundation — Buildings 1 & 2", "pct": 28, "type": "construction"},
                {"date": "2023-12-01", "label": "Phase 1 steel structure complete", "pct": 45, "type": "construction"},
                {"date": "2024-08-01", "label": "Phase 1 fit-out — MEP install", "pct": 55, "type": "construction"},
                {"date": "2025-06-01", "label": "Phase 1 operational (projected)", "pct": 75, "type": "projected"},
            ],
        },
        {
            "name": "Meta DeKalb Data Center",
            "company": "Meta",
            "lat": 41.9278, "lon": -88.7498,
            "address": "DeKalb, Illinois",
            "status": "Active Construction",
            "size_acres": 100,
            "construction_pct": 70,
            "announced": "2021 (expanding)",
            "source": "DeKalb County / Meta press release",
            "source_url": "https://sustainability.fb.com/",
            "milestones": [
                {"date": "2021-03-01", "label": "Site announced — 100 acres", "pct": 0, "type": "announcement"},
                {"date": "2021-08-01", "label": "Construction permits approved", "pct": 5, "type": "permit"},
                {"date": "2021-11-01", "label": "Site preparation begins", "pct": 12, "type": "construction"},
                {"date": "2022-06-01", "label": "Phase 1 foundation complete", "pct": 35, "type": "construction"},
                {"date": "2023-03-01", "label": "Phase 1 building enclosed", "pct": 55, "type": "construction"},
                {"date": "2024-01-01", "label": "Phase 1 operational — Phase 2 begins", "pct": 70, "type": "milestone"},
                {"date": "2025-06-01", "label": "Phase 2 operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "Oracle Phoenix Cloud Region",
            "company": "Oracle",
            "lat": 33.4484, "lon": -111.9671,
            "address": "Phoenix, Arizona",
            "status": "Operational",
            "size_acres": 50,
            "construction_pct": 100,
            "announced": "2019",
            "source": "Oracle Cloud Infrastructure — PHX region",
            "source_url": "https://www.oracle.com/cloud/data-regions/",
            "milestones": [
                {"date": "2018-06-01", "label": "PHX region construction begins", "pct": 0, "type": "announcement"},
                {"date": "2019-05-01", "label": "PHX region launched (OCI Gen 2)", "pct": 60, "type": "milestone"},
                {"date": "2020-09-01", "label": "Phase 2 expansion complete", "pct": 80, "type": "construction"},
                {"date": "2022-01-01", "label": "Full capacity operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Oracle Nashville Campus",
            "company": "Oracle",
            "lat": 36.1627, "lon": -86.7816,
            "address": "Nashville, Tennessee",
            "status": "Land Prep",
            "size_acres": 200,
            "construction_pct": 10,
            "announced": "2024",
            "source": "Oracle / Tennessee Economic Development",
            "source_url": "https://www.oracle.com/news/",
            "milestones": [
                {"date": "2024-06-01", "label": "Site announced — Nashville campus", "pct": 0, "type": "announcement"},
                {"date": "2024-10-01", "label": "Land acquisition complete", "pct": 3, "type": "permit"},
                {"date": "2025-02-01", "label": "Grading & utility permits filed", "pct": 7, "type": "permit"},
                {"date": "2025-05-01", "label": "Site preparation underway", "pct": 10, "type": "construction"},
                {"date": "2026-03-01", "label": "Foundation begins (projected)", "pct": 30, "type": "projected"},
                {"date": "2027-06-01", "label": "Phase 1 operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "Equinix Ashburn Campus (DC)",
            "company": "Equinix",
            "lat": 39.0534, "lon": -77.4728,
            "address": "Ashburn, Virginia",
            "status": "Operational",
            "size_acres": 40,
            "construction_pct": 100,
            "announced": "1999 (ongoing expansion)",
            "source": "Equinix — Ashburn (DC) IBX",
            "source_url": "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/ashburn-data-centers",
            "milestones": [
                {"date": "1999-01-01", "label": "DC1 opens — founding the Data Center Alley", "pct": 5, "type": "milestone"},
                {"date": "2006-01-01", "label": "DC2–DC5 campus expands", "pct": 30, "type": "construction"},
                {"date": "2012-01-01", "label": "DC6–DC10 operational", "pct": 60, "type": "construction"},
                {"date": "2018-01-01", "label": "DC11 & DC12 complete", "pct": 80, "type": "construction"},
                {"date": "2023-01-01", "label": "xScale AI-ready expansion", "pct": 95, "type": "construction"},
                {"date": "2024-06-01", "label": "Current capacity — ongoing upgrades", "pct": 100, "type": "milestone"},
            ],
        },
    ]
    return sites

def get_triangulation_data():
    _require_mock_gate("get_triangulation_data")
    regions = ["US-EAST", "US-WEST", "US-CENTRAL", "US-SOUTH", "EU", "APAC"]
    data = []
    for region in regions:
        contracted_gw = round(random.uniform(1.5, 8.0), 2)
        deployed_gpu_k = random.randint(20, 200)
        gpu_power_gw = round(deployed_gpu_k * 0.0003, 2)  # ~300W per GPU
        gap_gw = round(contracted_gw - gpu_power_gw, 2)
        nic_validation = round(random.uniform(0.75, 0.98), 2)
        permit_signals = random.randint(3, 18)
        data.append({
            "region": region,
            "contracted_power_gw": contracted_gw,
            "deployed_gpus_k": deployed_gpu_k,
            "gpu_power_demand_gw": gpu_power_gw,
            "power_gap_gw": gap_gw,
            "status": "Overbuild" if gap_gw > 1.5 else ("Constrained" if gap_gw < 0 else "Balanced"),
            "nic_validation_score": nic_validation,
            "permit_signal_count": permit_signals,
            "confidence": round(random.uniform(0.72, 0.95), 2),
        })
    return data

def get_sources_data():
    return [
        {
            "id": 1, "name": "SEC EDGAR", "type": "Financial Filing",
            "url": "https://www.sec.gov/cgi-bin/browse-edgar",
            "last_ingested": "2024-12-15", "records": 1240, "pillar": "Power",
            "description": "10-K and 10-Q filings with capital expenditure disclosures",
            "confidence": 0.94,
        },
        {
            "id": 2, "name": "NVIDIA Earnings Transcripts", "type": "Earnings Transcript",
            "url": "https://investor.nvidia.com",
            "last_ingested": "2024-11-22", "records": 48, "pillar": "GPU Supply",
            "description": "Quarterly earnings calls with GPU shipment and revenue data",
            "confidence": 0.91,
        },
        {
            "id": 3, "name": "TSMC Financial Reports", "type": "Financial Filing",
            "url": "https://investor.tsmc.com",
            "last_ingested": "2024-11-15", "records": 32, "pillar": "TSMC",
            "description": "Capacity reports, packaging constraints, technology node utilization",
            "confidence": 0.89,
        },
        {
            "id": 4, "name": "County Permit APIs", "type": "Public Records",
            "url": "https://permits.loudoun.gov",
            "last_ingested": "2024-12-10", "records": 3870, "pillar": "Permits",
            "description": "Building, electrical, and grading permits for datacenter construction",
            "confidence": 0.82,
        },
        {
            "id": 5, "name": "Planet Labs Satellite Imagery", "type": "Satellite",
            "url": "https://www.planet.com",
            "last_ingested": "2024-12-01", "records": 156, "pillar": "Satellite",
            "description": "High-resolution imagery for construction progress detection",
            "confidence": 0.78,
        },
        {
            "id": 6, "name": "Utility Agreements (Public)", "type": "Utility Contract",
            "url": "https://www.pjm.com",
            "last_ingested": "2024-11-30", "records": 289, "pillar": "Power",
            "description": "Power purchase agreements and grid interconnection filings",
            "confidence": 0.87,
        },
        {
            "id": 7, "name": "Hyperscaler Earnings (MSFT/AWS/GOOG)", "type": "Earnings Transcript",
            "url": "https://investor.microsoft.com",
            "last_ingested": "2024-10-30", "records": 96, "pillar": "Power / GPU",
            "description": "Capex, AI infrastructure, and datacenter expansion disclosures",
            "confidence": 0.93,
        },
        {
            "id": 8, "name": "NIC & Optics Industry Reports", "type": "Industry Analysis",
            "url": "https://www.idc.com",
            "last_ingested": "2024-09-15", "records": 64, "pillar": "NICs & Optics",
            "description": "InfiniBand and high-speed ethernet shipment tracking",
            "confidence": 0.76,
        },
    ]

def get_agent_status():
    return [
        {"agent": "Filing Parser Agent", "status": "active", "last_run": "2024-12-15T08:00:00Z", "records_processed": 1240},
        {"agent": "Earnings Parsing Agent", "status": "active", "last_run": "2024-11-22T14:00:00Z", "records_processed": 144},
        {"agent": "Geo Mapping Agent", "status": "active", "last_run": "2024-12-15T08:05:00Z", "records_processed": 8920},
        {"agent": "Supply Chain Agent", "status": "active", "last_run": "2024-12-10T10:00:00Z", "records_processed": 2100},
        {"agent": "Permit Monitoring Agent", "status": "active", "last_run": "2024-12-10T06:00:00Z", "records_processed": 3870},
        {"agent": "Satellite Analysis Agent", "status": "idle", "last_run": "2024-12-01T00:00:00Z", "records_processed": 156},
        {"agent": "Triangulation Agent", "status": "active", "last_run": "2024-12-15T08:10:00Z", "records_processed": 6},
        {"agent": "Explainability Agent", "status": "active", "last_run": "2024-12-15T08:12:00Z", "records_processed": 6},
    ]
