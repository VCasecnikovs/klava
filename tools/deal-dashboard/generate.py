#!/usr/bin/env python3
"""
Deal Velocity Dashboard Generator

Scans deal files from Obsidian, parses YAML frontmatter,
calculates velocity metrics, and generates a self-contained HTML dashboard.

Usage: python3 generate.py
Output: dashboard.html (same directory)

Override location via DEALS_DIR env var, or fall back to
"$OBSIDIAN_VAULT/Deals" (default vault: ~/Documents/MyBrain).
"""

import os
import re
import json
from datetime import datetime, date
from pathlib import Path

DEALS_DIR = Path(
    os.path.expanduser(
        os.environ.get(
            "DEALS_DIR",
            os.path.join(
                os.environ.get("OBSIDIAN_VAULT", "~/Documents/MyBrain"), "Deals"
            ),
        )
    )
)
OUTPUT_DIR = Path(__file__).parent
OUTPUT_FILE = OUTPUT_DIR / "dashboard.html"

TODAY = date.today()

# Stage number -> canonical name mapping
STAGE_NAMES = {
    1: "prospecting",
    2: "outreach",
    3: "meeting",
    4: "qualified",
    5: "proposal",
    6: "negotiation",
    7: "pilot",
    8: "legal",
    9: "contract",
    10: "procurement",
    11: "signed",
    12: "onboarding",
    13: "delivery",
    14: "renewal",
    15: "expansion",
    16: "stalled",
    17: "lost",
}

# Weighted pipeline multipliers by stage range
WEIGHT_BRACKETS = {
    (1, 3): 0.10,
    (4, 6): 0.25,
    (7, 9): 0.50,
    (10, 12): 0.75,
    (13, 15): 0.90,
}

# Priority deals to highlight
PRIORITY_DEALS = []  # configure via environment or config file


def parse_frontmatter(filepath: Path) -> dict | None:
    """Parse YAML frontmatter from a markdown file. Returns dict or None."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None

    fm = {}
    raw = match.group(1)

    # Simple YAML parser for flat key-value pairs (no nested objects needed)
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith("- "):
            # Skip list items (tags etc)
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()

            # Strip quotes
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]

            # Handle null/empty
            if val in ("null", "~", ""):
                val = None

            fm[key] = val

    return fm


def parse_stage(stage_str: str) -> tuple[int, str]:
    """Parse stage string like '13-delivery' into (13, 'delivery')."""
    if not stage_str:
        return (0, "unknown")
    match = re.match(r"(\d+)-?(.*)", str(stage_str))
    if match:
        num = int(match.group(1))
        name = match.group(2).strip() if match.group(2) else STAGE_NAMES.get(num, "unknown")
        return (num, name)
    return (0, str(stage_str))


def parse_date(date_str: str | None) -> date | None:
    """Parse date string to date object."""
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_value(val_str: str | None) -> float | None:
    """Parse numeric value."""
    if val_str is None:
        return None
    try:
        return float(str(val_str).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def clean_lead(lead_str: str | None) -> str:
    """Clean lead name from wikilink format [[Name]]."""
    if not lead_str:
        return "Unknown"
    return re.sub(r"\[{1,2}|\]{1,2}", "", str(lead_str)).strip()


def get_weight(stage_num: int) -> float:
    """Get pipeline weight for a stage number."""
    for (lo, hi), weight in WEIGHT_BRACKETS.items():
        if lo <= stage_num <= hi:
            return weight
    return 0.0  # stalled/lost get 0 weight


def load_deals() -> list[dict]:
    """Load and parse all deal files."""
    deals = []

    if not DEALS_DIR.exists():
        print(f"ERROR: Deals directory not found: {DEALS_DIR}")
        return deals

    for filepath in sorted(DEALS_DIR.glob("*.md")):
        fm = parse_frontmatter(filepath)
        if not fm:
            continue

        # Skip non-deal files (no stage)
        if "stage" not in fm:
            continue

        stage_num, stage_name = parse_stage(fm.get("stage"))
        value = parse_value(fm.get("value"))
        mrr = parse_value(fm.get("mrr"))
        last_contact_date = parse_date(fm.get("last_contact"))
        follow_up_date = parse_date(fm.get("follow_up"))

        # Calculate days in stage (from last_contact)
        days_in_stage = None
        if last_contact_date:
            days_in_stage = (TODAY - last_contact_date).days

        # Calculate days until follow-up (negative = overdue)
        days_until_follow_up = None
        overdue = False
        if follow_up_date:
            days_until_follow_up = (follow_up_date - TODAY).days
            overdue = days_until_follow_up < 0

        # Deal name from filename
        deal_name = filepath.stem

        deal = {
            "name": deal_name,
            "file": str(filepath),
            "lead": clean_lead(fm.get("lead")),
            "stage_num": stage_num,
            "stage_name": stage_name,
            "stage_display": f"{stage_num}-{stage_name}",
            "value": value,
            "mrr": mrr,
            "deal_size": fm.get("deal_size"),
            "deal_type": fm.get("deal_type"),
            "owner": fm.get("owner"),
            "payment_type": fm.get("payment_type"),
            "product": fm.get("product"),
            "last_contact": str(last_contact_date) if last_contact_date else None,
            "follow_up": str(follow_up_date) if follow_up_date else None,
            "days_in_stage": days_in_stage,
            "days_until_follow_up": days_until_follow_up,
            "overdue": overdue,
            "is_active": stage_num not in (16, 17),
            "is_priority": any(
                p in deal_name.lower() for p in PRIORITY_DEALS
            ),
            "weight": get_weight(stage_num),
        }
        deals.append(deal)

    return deals


def compute_metrics(deals: list[dict]) -> dict:
    """Compute aggregate pipeline metrics."""
    active_deals = [d for d in deals if d["is_active"]]
    overdue_deals = [d for d in active_deals if d["overdue"]]

    total_pipeline = sum(d["value"] or 0 for d in active_deals)
    weighted_pipeline = sum((d["value"] or 0) * d["weight"] for d in active_deals)

    # Stage distribution
    stage_groups = {}
    for d in active_deals:
        key = d["stage_display"]
        if key not in stage_groups:
            stage_groups[key] = {"count": 0, "value": 0, "deals": []}
        stage_groups[key]["count"] += 1
        stage_groups[key]["value"] += d["value"] or 0
        stage_groups[key]["deals"].append(d["name"])

    return {
        "total_pipeline": total_pipeline,
        "weighted_pipeline": weighted_pipeline,
        "active_count": len(active_deals),
        "overdue_count": len(overdue_deals),
        "overdue_deals": sorted(overdue_deals, key=lambda d: d["days_until_follow_up"] or 0),
        "stage_groups": stage_groups,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def format_currency(val: float | None) -> str:
    """Format a number as currency string."""
    if val is None:
        return "-"
    if val >= 1_000_000:
        return f"${val / 1_000_000:,.1f}M"
    if val >= 1_000:
        return f"${val:,.0f}"
    return f"${val:,.2f}"


def generate_html(deals: list[dict], metrics: dict) -> str:
    """Generate the complete HTML dashboard."""
    deals_json = json.dumps(deals, default=str)
    metrics_json = json.dumps(metrics, default=str)

    # Build stage pipeline data (sorted by stage number)
    stage_data = []
    for d in deals:
        if not d["is_active"]:
            continue
    stage_map = {}
    for d in deals:
        if not d["is_active"]:
            continue
        sn = d["stage_num"]
        if sn not in stage_map:
            stage_map[sn] = {
                "stage_num": sn,
                "stage_display": d["stage_display"],
                "count": 0,
                "value": 0,
                "deals": [],
            }
        stage_map[sn]["count"] += 1
        stage_map[sn]["value"] += d["value"] or 0
        stage_map[sn]["deals"].append(d["name"])

    pipeline_stages = sorted(stage_map.values(), key=lambda s: s["stage_num"])
    pipeline_stages_json = json.dumps(pipeline_stages, default=str)

    # Priority deals
    priority_deals = [d for d in deals if d["is_priority"] and d["is_active"]]
    priority_json = json.dumps(priority_deals, default=str)

    # Overdue deals
    overdue_deals = metrics["overdue_deals"]
    overdue_json = json.dumps(overdue_deals, default=str)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Deal Velocity Dashboard</title>
<style>
:root {{
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --bg-hover: #292e36;
    --border: #30363d;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --accent-blue: #58a6ff;
    --accent-green: #3fb950;
    --accent-yellow: #d29922;
    --accent-orange: #db6d28;
    --accent-red: #f85149;
    --accent-purple: #bc8cff;
    --accent-cyan: #39d2c0;
}}

* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 24px;
    min-height: 100vh;
}}

.dashboard {{
    max-width: 1600px;
    margin: 0 auto;
}}

/* Header */
.header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
}}

.header h1 {{
    font-size: 24px;
    font-weight: 600;
    color: var(--text-primary);
}}

.header h1 span {{
    color: var(--accent-blue);
}}

.generated-at {{
    color: var(--text-muted);
    font-size: 13px;
}}

/* Metric Cards */
.metrics-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
}}

.metric-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    transition: border-color 0.2s;
}}

.metric-card:hover {{
    border-color: var(--accent-blue);
}}

.metric-card.danger {{
    border-color: var(--accent-red);
}}

.metric-card.danger:hover {{
    border-color: var(--accent-red);
    background: rgba(248, 81, 73, 0.05);
}}

.metric-label {{
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    margin-bottom: 8px;
}}

.metric-value {{
    font-size: 32px;
    font-weight: 700;
    color: var(--text-primary);
}}

.metric-value.red {{
    color: var(--accent-red);
}}

.metric-value.green {{
    color: var(--accent-green);
}}

.metric-sub {{
    font-size: 13px;
    color: var(--text-muted);
    margin-top: 4px;
}}

/* Alerts Section */
.alerts-section {{
    margin-bottom: 24px;
}}

.alert-group {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
}}

.alert-group.urgent {{
    border-left: 4px solid var(--accent-red);
}}

.alert-group.priority {{
    border-left: 4px solid var(--accent-cyan);
}}

.alert-title {{
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 10px;
}}

.alert-title.urgent {{
    color: var(--accent-red);
}}

.alert-title.priority {{
    color: var(--accent-cyan);
}}

.alert-item {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    margin-bottom: 4px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    font-size: 14px;
}}

.alert-item .deal-name {{
    font-weight: 500;
}}

.alert-item .overdue-badge {{
    background: rgba(248, 81, 73, 0.15);
    color: var(--accent-red);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
}}

.alert-item .stage-badge {{
    background: rgba(88, 166, 255, 0.12);
    color: var(--accent-blue);
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
}}

.alert-item .value-badge {{
    color: var(--accent-green);
    font-weight: 600;
    font-size: 13px;
}}

/* Pipeline Visualization */
.pipeline-section {{
    margin-bottom: 24px;
}}

.section-title {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 12px;
    color: var(--text-primary);
}}

.pipeline-chart {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
}}

.pipeline-bar-row {{
    display: flex;
    align-items: center;
    margin-bottom: 10px;
    gap: 12px;
}}

.pipeline-stage-label {{
    width: 140px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-secondary);
    text-align: right;
    flex-shrink: 0;
}}

.pipeline-bar-container {{
    flex: 1;
    height: 32px;
    background: var(--bg-tertiary);
    border-radius: 6px;
    overflow: hidden;
    position: relative;
}}

.pipeline-bar {{
    height: 100%;
    border-radius: 6px;
    display: flex;
    align-items: center;
    padding-left: 10px;
    transition: width 0.5s ease;
    min-width: 2px;
}}

.pipeline-bar-text {{
    font-size: 12px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
}}

.pipeline-stats {{
    width: 120px;
    text-align: right;
    font-size: 13px;
    color: var(--text-muted);
    flex-shrink: 0;
}}

.pipeline-stats .count {{
    color: var(--text-secondary);
    font-weight: 600;
}}

.pipeline-stats .value {{
    color: var(--accent-green);
    font-weight: 500;
}}

/* Deal Table */
.table-section {{
    margin-bottom: 24px;
}}

.table-container {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
}}

.table-controls {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
}}

.filter-group {{
    display: flex;
    gap: 8px;
    align-items: center;
}}

.filter-btn {{
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
}}

.filter-btn:hover {{
    border-color: var(--accent-blue);
    color: var(--text-primary);
}}

.filter-btn.active {{
    background: rgba(88, 166, 255, 0.12);
    border-color: var(--accent-blue);
    color: var(--accent-blue);
}}

.search-input {{
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-primary);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 13px;
    width: 220px;
    outline: none;
    transition: border-color 0.15s;
}}

.search-input:focus {{
    border-color: var(--accent-blue);
}}

.search-input::placeholder {{
    color: var(--text-muted);
}}

table {{
    width: 100%;
    border-collapse: collapse;
}}

thead th {{
    background: var(--bg-tertiary);
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    text-align: left;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
    transition: color 0.15s;
}}

thead th:hover {{
    color: var(--accent-blue);
}}

thead th.sorted-asc::after {{
    content: " \\25B2";
    font-size: 10px;
}}

thead th.sorted-desc::after {{
    content: " \\25BC";
    font-size: 10px;
}}

tbody tr {{
    border-bottom: 1px solid var(--border);
    transition: background 0.1s;
}}

tbody tr:hover {{
    background: var(--bg-hover);
}}

tbody tr.overdue {{
    background: rgba(248, 81, 73, 0.04);
}}

tbody tr.overdue:hover {{
    background: rgba(248, 81, 73, 0.08);
}}

tbody tr.due-today {{
    background: rgba(210, 153, 34, 0.04);
}}

tbody tr.priority-deal {{
    border-left: 3px solid var(--accent-cyan);
}}

tbody td {{
    padding: 10px 14px;
    font-size: 14px;
    color: var(--text-primary);
    white-space: nowrap;
}}

.deal-name-cell {{
    font-weight: 500;
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
}}

.stage-pill {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
}}

.stage-early {{ background: rgba(88, 166, 255, 0.12); color: var(--accent-blue); }}
.stage-mid {{ background: rgba(210, 153, 34, 0.15); color: var(--accent-yellow); }}
.stage-late {{ background: rgba(63, 185, 80, 0.15); color: var(--accent-green); }}
.stage-won {{ background: rgba(63, 185, 80, 0.25); color: var(--accent-green); }}
.stage-stalled {{ background: rgba(139, 148, 158, 0.15); color: var(--text-secondary); }}
.stage-lost {{ background: rgba(248, 81, 73, 0.12); color: var(--accent-red); }}

.overdue-cell {{
    font-weight: 600;
}}

.overdue-cell.red {{ color: var(--accent-red); }}
.overdue-cell.yellow {{ color: var(--accent-yellow); }}
.overdue-cell.green {{ color: var(--accent-green); }}
.overdue-cell.muted {{ color: var(--text-muted); }}

.value-cell {{
    font-weight: 500;
    color: var(--accent-green);
}}

.value-cell.empty {{
    color: var(--text-muted);
}}

.owner-cell {{
    color: var(--text-secondary);
}}

.product-cell {{
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-secondary);
}}

/* Stalled/Lost section */
.inactive-section {{
    margin-top: 24px;
    opacity: 0.7;
    transition: opacity 0.2s;
}}

.inactive-section:hover {{
    opacity: 1;
}}

.inactive-header {{
    font-size: 14px;
    color: var(--text-muted);
    margin-bottom: 8px;
    cursor: pointer;
}}

.inactive-header:hover {{
    color: var(--text-secondary);
}}

/* Responsive */
@media (max-width: 1200px) {{
    .metrics-grid {{
        grid-template-columns: repeat(2, 1fr);
    }}
}}

@media (max-width: 768px) {{
    .metrics-grid {{
        grid-template-columns: 1fr;
    }}
    body {{
        padding: 12px;
    }}
}}

/* Scrollbar */
::-webkit-scrollbar {{
    width: 8px;
    height: 8px;
}}
::-webkit-scrollbar-track {{
    background: var(--bg-primary);
}}
::-webkit-scrollbar-thumb {{
    background: var(--border);
    border-radius: 4px;
}}
::-webkit-scrollbar-thumb:hover {{
    background: var(--text-muted);
}}
</style>
</head>
<body>
<div class="dashboard">

<!-- Header -->
<div class="header">
    <h1><span>Deal Velocity</span></h1>
    <div class="generated-at">Generated: {metrics['generated_at']}</div>
</div>

<!-- Alerts -->
<div class="alerts-section" id="alerts-section"></div>

<!-- Metrics -->
<div class="metrics-grid" id="metrics-grid"></div>

<!-- Pipeline -->
<div class="pipeline-section">
    <div class="section-title">Stage Pipeline</div>
    <div class="pipeline-chart" id="pipeline-chart"></div>
</div>

<!-- Deal Table -->
<div class="table-section">
    <div class="section-title">All Deals</div>
    <div class="table-container">
        <div class="table-controls">
            <div class="filter-group">
                <button class="filter-btn active" data-filter="active">Active</button>
                <button class="filter-btn" data-filter="overdue">Overdue</button>
                <button class="filter-btn" data-filter="priority">Priority</button>
                <button class="filter-btn" data-filter="all">All</button>
            </div>
            <input type="text" class="search-input" placeholder="Search deals..." id="search-input">
        </div>
        <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr>
                        <th data-sort="name">Deal</th>
                        <th data-sort="stage_num">Stage</th>
                        <th data-sort="value">Value</th>
                        <th data-sort="mrr">MRR</th>
                        <th data-sort="owner">Owner</th>
                        <th data-sort="last_contact">Last Contact</th>
                        <th data-sort="follow_up">Follow-up</th>
                        <th data-sort="days_until_follow_up">Status</th>
                        <th data-sort="product">Product</th>
                        <th data-sort="deal_type">Type</th>
                    </tr>
                </thead>
                <tbody id="deal-tbody"></tbody>
            </table>
        </div>
    </div>
</div>

</div>

<script>
const DEALS = {deals_json};
const METRICS = {metrics_json};
const PIPELINE_STAGES = {pipeline_stages_json};
const PRIORITY = {priority_json};
const OVERDUE = {overdue_json};
const TODAY = "{TODAY.isoformat()}";

// --- Formatting ---
function fmtCurrency(val) {{
    if (val === null || val === undefined || val === 0) return "-";
    if (val >= 1000000) return "$" + (val / 1000000).toFixed(1) + "M";
    if (val >= 1000) return "$" + val.toLocaleString("en-US", {{maximumFractionDigits: 0}});
    return "$" + val.toFixed(0);
}}

function fmtDate(d) {{
    if (!d) return "-";
    return d;
}}

function stageClass(num) {{
    if (num <= 3) return "stage-early";
    if (num <= 6) return "stage-mid";
    if (num <= 9) return "stage-mid";
    if (num <= 15) return "stage-late";
    if (num === 16) return "stage-stalled";
    return "stage-lost";
}}

function statusText(d) {{
    if (d.follow_up === null) return {{ text: "No follow-up", cls: "muted" }};
    if (d.days_until_follow_up === null) return {{ text: "-", cls: "muted" }};
    if (d.days_until_follow_up < 0) return {{ text: Math.abs(d.days_until_follow_up) + "d overdue", cls: "red" }};
    if (d.days_until_follow_up === 0) return {{ text: "Due today", cls: "yellow" }};
    if (d.days_until_follow_up <= 3) return {{ text: "In " + d.days_until_follow_up + "d", cls: "yellow" }};
    return {{ text: "In " + d.days_until_follow_up + "d", cls: "green" }};
}}

function barColor(stageNum) {{
    const colors = {{
        1: "#58a6ff", 2: "#58a6ff", 3: "#58a6ff",
        4: "#d29922", 5: "#d29922", 6: "#d29922",
        7: "#db6d28", 8: "#db6d28", 9: "#db6d28",
        10: "#3fb950", 11: "#3fb950", 12: "#3fb950",
        13: "#39d2c0", 14: "#39d2c0", 15: "#39d2c0",
    }};
    return colors[stageNum] || "#6e7681";
}}

// --- Render Metrics ---
function renderMetrics() {{
    const grid = document.getElementById("metrics-grid");
    const overdueCount = parseInt(METRICS.overdue_count);
    grid.innerHTML = `
        <div class="metric-card">
            <div class="metric-label">Total Pipeline</div>
            <div class="metric-value">${{fmtCurrency(parseFloat(METRICS.total_pipeline))}}</div>
            <div class="metric-sub">Sum of all active deal values</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Weighted Pipeline</div>
            <div class="metric-value">${{fmtCurrency(parseFloat(METRICS.weighted_pipeline))}}</div>
            <div class="metric-sub">Stage-adjusted expected revenue</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Active Deals</div>
            <div class="metric-value green">${{METRICS.active_count}}</div>
            <div class="metric-sub">Excluding stalled and lost</div>
        </div>
        <div class="metric-card ${{overdueCount > 0 ? 'danger' : ''}}">
            <div class="metric-label">Overdue Follow-ups</div>
            <div class="metric-value ${{overdueCount > 0 ? 'red' : 'green'}}">${{overdueCount}}</div>
            <div class="metric-sub">${{overdueCount > 0 ? 'Action required!' : 'All on track'}}</div>
        </div>
    `;
}}

// --- Render Alerts ---
function renderAlerts() {{
    const section = document.getElementById("alerts-section");
    let html = "";

    if (OVERDUE.length > 0) {{
        html += `<div class="alert-group urgent">
            <div class="alert-title urgent">URGENT - Overdue Follow-ups (${{OVERDUE.length}})</div>`;
        OVERDUE.forEach(d => {{
            const days = Math.abs(d.days_until_follow_up);
            html += `<div class="alert-item">
                <span class="deal-name">${{d.name}}</span>
                <span class="stage-badge">${{d.stage_display}}</span>
                <span class="value-badge">${{fmtCurrency(d.value)}}</span>
                <span class="overdue-badge">${{days}}d overdue</span>
            </div>`;
        }});
        html += `</div>`;
    }}

    if (PRIORITY.length > 0) {{
        html += `<div class="alert-group priority">
            <div class="alert-title priority">TOP PRIORITY DEALS</div>`;
        PRIORITY.forEach(d => {{
            const st = statusText(d);
            html += `<div class="alert-item">
                <span class="deal-name">${{d.name}}</span>
                <span class="stage-badge">${{d.stage_display}}</span>
                <span class="value-badge">${{fmtCurrency(d.value)}}</span>
                <span class="overdue-cell ${{st.cls}}" style="font-size:12px">${{st.text}}</span>
            </div>`;
        }});
        html += `</div>`;
    }}

    section.innerHTML = html;
}}

// --- Render Pipeline ---
function renderPipeline() {{
    const chart = document.getElementById("pipeline-chart");
    if (PIPELINE_STAGES.length === 0) {{
        chart.innerHTML = '<div style="color: var(--text-muted); padding: 20px;">No active deals</div>';
        return;
    }}

    const maxValue = Math.max(...PIPELINE_STAGES.map(s => s.value), 1);
    const maxCount = Math.max(...PIPELINE_STAGES.map(s => s.count), 1);

    let html = "";
    PIPELINE_STAGES.forEach(s => {{
        const pctValue = Math.max((s.value / maxValue) * 100, (s.count / maxCount) * 15);
        const pct = Math.max(pctValue, 5);
        const color = barColor(s.stage_num);
        html += `<div class="pipeline-bar-row">
            <div class="pipeline-stage-label">${{s.stage_display}}</div>
            <div class="pipeline-bar-container">
                <div class="pipeline-bar" style="width: ${{pct}}%; background: ${{color}}33; border: 1px solid ${{color}}88;">
                    <span class="pipeline-bar-text" style="color: ${{color}}">${{s.deals.join(", ")}}</span>
                </div>
            </div>
            <div class="pipeline-stats">
                <span class="count">${{s.count}} deal${{s.count > 1 ? 's' : ''}}</span>
                ${{s.value > 0 ? ' <span class="value">' + fmtCurrency(s.value) + '</span>' : ''}}
            </div>
        </div>`;
    }});
    chart.innerHTML = html;
}}

// --- Render Table ---
let currentSort = {{ col: "stage_num", dir: "asc" }};
let currentFilter = "active";
let searchQuery = "";

function renderTable() {{
    const tbody = document.getElementById("deal-tbody");
    let filtered = DEALS.slice();

    // Filter
    if (currentFilter === "active") filtered = filtered.filter(d => d.is_active);
    else if (currentFilter === "overdue") filtered = filtered.filter(d => d.overdue && d.is_active);
    else if (currentFilter === "priority") filtered = filtered.filter(d => d.is_priority && d.is_active);
    // "all" = no filter

    // Search
    if (searchQuery) {{
        const q = searchQuery.toLowerCase();
        filtered = filtered.filter(d =>
            d.name.toLowerCase().includes(q) ||
            (d.product || "").toLowerCase().includes(q) ||
            (d.lead || "").toLowerCase().includes(q) ||
            (d.owner || "").toLowerCase().includes(q) ||
            d.stage_display.toLowerCase().includes(q)
        );
    }}

    // Sort
    filtered.sort((a, b) => {{
        let va = a[currentSort.col];
        let vb = b[currentSort.col];
        if (va === null || va === undefined) va = currentSort.dir === "asc" ? Infinity : -Infinity;
        if (vb === null || vb === undefined) vb = currentSort.dir === "asc" ? Infinity : -Infinity;
        if (typeof va === "string") va = va.toLowerCase();
        if (typeof vb === "string") vb = vb.toLowerCase();
        if (va < vb) return currentSort.dir === "asc" ? -1 : 1;
        if (va > vb) return currentSort.dir === "asc" ? 1 : -1;
        return 0;
    }});

    let html = "";
    filtered.forEach(d => {{
        const st = statusText(d);
        const rowClass = [];
        if (d.overdue && d.is_active) rowClass.push("overdue");
        if (d.days_until_follow_up === 0) rowClass.push("due-today");
        if (d.is_priority) rowClass.push("priority-deal");

        html += `<tr class="${{rowClass.join(' ')}}">
            <td class="deal-name-cell" title="${{d.name}}">${{d.name}}</td>
            <td><span class="stage-pill ${{stageClass(d.stage_num)}}">${{d.stage_display}}</span></td>
            <td class="value-cell ${{d.value ? '' : 'empty'}}">${{fmtCurrency(d.value)}}</td>
            <td class="value-cell ${{d.mrr ? '' : 'empty'}}">${{fmtCurrency(d.mrr)}}</td>
            <td class="owner-cell">${{d.owner || "-"}}</td>
            <td>${{fmtDate(d.last_contact)}}</td>
            <td>${{fmtDate(d.follow_up)}}</td>
            <td class="overdue-cell ${{st.cls}}">${{st.text}}</td>
            <td class="product-cell" title="${{d.product || ''}}">${{d.product || "-"}}</td>
            <td>${{d.deal_type || "-"}}</td>
        </tr>`;
    }});

    tbody.innerHTML = html || '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);padding:24px;">No deals match filters</td></tr>';

    // Update sort indicators
    document.querySelectorAll("thead th").forEach(th => {{
        th.classList.remove("sorted-asc", "sorted-desc");
        if (th.dataset.sort === currentSort.col) {{
            th.classList.add(currentSort.dir === "asc" ? "sorted-asc" : "sorted-desc");
        }}
    }});
}}

// --- Event Handlers ---
document.querySelectorAll("thead th[data-sort]").forEach(th => {{
    th.addEventListener("click", () => {{
        const col = th.dataset.sort;
        if (currentSort.col === col) {{
            currentSort.dir = currentSort.dir === "asc" ? "desc" : "asc";
        }} else {{
            currentSort.col = col;
            currentSort.dir = "asc";
        }}
        renderTable();
    }});
}});

document.querySelectorAll(".filter-btn").forEach(btn => {{
    btn.addEventListener("click", () => {{
        document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentFilter = btn.dataset.filter;
        renderTable();
    }});
}});

document.getElementById("search-input").addEventListener("input", (e) => {{
    searchQuery = e.target.value;
    renderTable();
}});

// --- Init ---
renderMetrics();
renderAlerts();
renderPipeline();
renderTable();

</script>
</body>
</html>"""

    return html


def main():
    print(f"Scanning deals in: {DEALS_DIR}")
    deals = load_deals()
    print(f"Found {len(deals)} deals ({sum(1 for d in deals if d['is_active'])} active)")

    metrics = compute_metrics(deals)
    print(f"Total pipeline: {format_currency(metrics['total_pipeline'])}")
    print(f"Weighted pipeline: {format_currency(metrics['weighted_pipeline'])}")
    print(f"Overdue follow-ups: {metrics['overdue_count']}")

    html = generate_html(deals, metrics)

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\nDashboard generated: {OUTPUT_FILE}")
    print(f"Open in browser: file://{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
