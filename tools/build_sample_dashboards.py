"""Write the sample dashboards that ship with the app.

Each sample is defined here as plain data and saved to
``frontend/app_server/default_dashboards`` with the table every data source
returned at build time, so it opens with its charts drawn on a PC that has
never reached the server. Refresh Data in the app replaces those tables with
the server's current figures.

The tables come from ``dashboard_service.load_source``, the same call the app
makes. Run it where the projects can be read: on a signed-in PC once the
Gateway offers the dashboard reads, or on the Server PC with ``--on-server``,
which runs the reads in place against the server folder.

    py -3.10 tools/build_sample_dashboards.py --on-server
    py -3.10 tools/build_sample_dashboards.py --only "Quarter Over Quarter Movement"

The projects are the general demo (``ABC_Group_Quarterly_Review_202608``) and
the two Fake valuations. A dataset a class does not hold is reported, not fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for root in (REPOSITORY_ROOT / "python-api" / "src", REPOSITORY_ROOT / "frontend"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

DEMO_PROJECT = "ABC_Group_Quarterly_Review_202608"
FAKE_MAY = "NJ_Annual_Prod_202605_Fake"
FAKE_AUGUST = "NJ_Annual_Prod_202608_Fake"
MAY, AUGUST = "May 2026", "Aug 2026"
LEVELS = ["Company", "Product", "State", "Channel", "Coverage"]
YEAR = "Origin Year"

PAID = "Net Loss--Paid"
INCURRED = "Net Loss--Incurred"
SELECTED = "F 92 - Current Qtr Selected"
PRIOR = "F 82 - Prior Qtr Selected"
PREMIUM = "Earned Premium"
REPORTED = "Claim Counts--Reported"
CLOSED = "Claim Counts--Total Closed"
PAID_TO_INCURRED = "Losses--Net Paid as % of Net Incurred"
CLOSURE = "Claim Counts--Closed as % of Reported"
SEVERITY = "Severity--Net Incurred per Reported"

DEMO_CLASSES = [
    r"ABC Auto\PPA\All States\Exclusive\Collision",
    r"ABC Auto\PPA\All States\Exclusive\Comp ex Cat",
    r"ABC Auto\PPA\All States\Exclusive\PD Total",
    r"ABC Auto\PPA\MA\Exclusive\BI Total",
    r"ABC Auto\PPA\MA\Exclusive\Medical and PIP",
    r"ABC Auto\PPA\NJ\Exclusive\BI Full Tort",
    r"ABC Auto\PPA\NJ\Exclusive\BI Limited Tort",
    r"ABC Auto\PPA\NJ\Exclusive\Medical and PIP",
    r"ABC Auto\PPA\NY\Exclusive\BI Total",
    r"ABC Auto\PPA\NY\Exclusive\Medical and PIP",
    r"ABC Auto\PPA\PA+CT\Exclusive\BI Total",
    r"ABC Auto\PPA\PA+CT\Exclusive\Medical and PIP",
    r"ABC Home\HO+DF\NJ\Legacy\Home Liability",
    r"ABC Home\HO+DF\NJ\Legacy\Home Property ex Cat",
    r"ABC Moto\MC\All States\Exclusive\Injury Total",
    r"ABC Moto\MC\All States\Exclusive\PD Total",
    r"ABC Moto\MC\All States\Exclusive\Phys Dmg ex Cat",
]
# The demo classes that carry both a current and a prior selected ultimate.
REVIEW_CLASSES = [name for name in DEMO_CLASSES if not name.endswith((
    r"\Collision", r"\Comp ex Cat", r"MA\Exclusive\Medical and PIP", r"\Phys Dmg ex Cat",
))]
FAKE_CLASSES = [
    r"PRNJ - PA\PA\NJ\Direct Group\MP+PIP",
    r"PRNJ - PA\PA\NJ\Direct Group\BIx51+UMBIx51",
    r"PRNJ - PA\PA\NJ\Direct Group\BIR51+UMBIR51",
    r"PRNJ - PA\PA\NY\Direct Group\MP+PIP",
    r"PRNJ - PA\PA\MA\Direct Group\MP+PIP",
    r"PRNJ - PA\PA\MA\Direct Group\BI Total",
    r"PRNJ - PA\PA\Penn+CT\Direct Group\BI Total",
    r"PRNJ - PA\PA\Penn+CT\Direct Group\MP+PIP",
    r"PRNJ - PA\PA\All States\Direct Group\COL",
    r"PRNJ - PA\PA\All States\Direct Group\PD+UMPD",
]


def measure(field: str, agg: str = "", label: str = "", fmt: str = "", decimals: int | None = None) -> dict:
    item: dict = {"field": field}
    if agg:
        item["agg"] = agg
    return _styled(item, label, fmt, decimals)


def calc(expr: str, label: str, fmt: str = "", decimals: int | None = None) -> dict:
    return _styled({"expr": expr}, label, fmt, decimals)


def _styled(item: dict, label: str, fmt: str, decimals: int | None) -> dict:
    if label:
        item["label"] = label
    if fmt:
        item["format"] = fmt
    if decimals is not None:
        item["decimals"] = decimals
    return item


def widget(kind: str, title: str, x: int, y: int, w: int, h: int, source: str = "src1", **fields) -> dict:
    item = {"type": kind, "title": title, "layout": {"x": x, "y": y, "w": w, "h": h}}
    if kind != "text":
        item["source"] = source
    item.update(fields)
    return item


def page(name: str, widgets: list[dict], filters: list | None = None) -> dict:
    for index, item in enumerate(widgets, start=1):
        item["id"] = f"w{index}"
    return {
        "name": name,
        "filters": [entry if isinstance(entry, dict) else {"field": entry, "values": []} for entry in filters or []],
        "widgets": widgets,
    }


ULTIMATE = measure(SELECTED, "sum", "Selected Ultimate", "compact")
PAID_LATEST = measure(PAID, "latest", "Paid", "compact")
INCURRED_LATEST = measure(INCURRED, "latest", "Case Incurred", "compact")
IBNR = calc(f"sum([{SELECTED}]) - latest([{INCURRED}])", "IBNR", "compact")
LOSS_RATIO = calc(f"sum([{SELECTED}]) / sum([{PREMIUM}])", "Ultimate Loss Ratio", "percent")


def reserve_review_summary() -> dict:
    overview = page("Overview", [
        widget("kpi", "Selected Ultimate", 0, 0, 3, 2, category=YEAR, measures=[ULTIMATE]),
        widget("kpi", "Paid To Date", 3, 0, 3, 2, category=YEAR, measures=[PAID_LATEST]),
        widget("kpi", "IBNR", 6, 0, 3, 2, category=YEAR, measures=[IBNR]),
        widget("kpi", "Ultimate Loss Ratio", 9, 0, 3, 2, category=YEAR, measures=[LOSS_RATIO]),
        widget("bar", "Ultimate By Accident Year", 0, 2, 7, 5, category=YEAR, options={"stacked": True}, measures=[
            PAID_LATEST,
            calc(f"latest([{INCURRED}]) - latest([{PAID}])", "Case Reserve", "compact"),
            IBNR,
        ]),
        widget("line", "Ultimate Loss Ratio By Accident Year", 7, 2, 5, 5, category=YEAR, series="Company", measures=[LOSS_RATIO]),
        widget("heatmap", "Ultimate Loss Ratio By Coverage And State", 0, 7, 7, 5, category="Coverage", series="State", measures=[LOSS_RATIO]),
        widget("bar", "IBNR By Coverage", 7, 7, 5, 5, category="Coverage", measures=[IBNR],
               options={"horizontal": True}, sort={"by": "value", "dir": "desc"}),
    ], filters=["Company", "State", YEAR])
    movement = page("Change From Prior Quarter", [
        widget("kpi", "Change In Selected Ultimate", 0, 0, 4, 2, measures=[
            calc(f"sum([{SELECTED}]) - sum([{PRIOR}])", "Change In Selected Ultimate", "compact"),
        ]),
        widget("kpi", "Percent Change", 4, 0, 4, 2, measures=[
            calc(f"sum([{SELECTED}]) / sum([{PRIOR}]) - 1", "Percent Change", "percent"),
        ]),
        widget("kpi", "Prior Quarter Selected", 8, 0, 4, 2, measures=[measure(PRIOR, "sum", "Prior Quarter Selected", "compact")]),
        widget("bar", "Change In Selected Ultimate By Accident Year", 0, 2, 6, 5, category=YEAR, measures=[
            calc(f"sum([{SELECTED}]) - sum([{PRIOR}])", "Change In Selected Ultimate", "compact"),
        ]),
        widget("bar", "Change In Selected Ultimate By Coverage", 6, 2, 6, 5, category="Coverage", measures=[
            calc(f"sum([{SELECTED}]) - sum([{PRIOR}])", "Change In Selected Ultimate", "compact"),
        ], options={"horizontal": True}, sort={"by": "value", "dir": "desc"}),
        widget("table", "Segments", 0, 7, 12, 6, category="Segment", measures=[
            PAID_LATEST, INCURRED_LATEST,
            measure(PRIOR, "sum", "Prior Selected", "number", 0),
            measure(SELECTED, "sum", "Current Selected", "number", 0),
            calc(f"sum([{SELECTED}]) - sum([{PRIOR}])", "Change", "number", 0),
            IBNR, LOSS_RATIO,
        ]),
    ], filters=["Company", "State", YEAR])
    return {
        "name": "Reserve Review Summary",
        "description": "Where the quarter stands: paid, case incurred, selected ultimate, IBNR and loss ratio by accident year, coverage and state.",
        "sources": [{
            "id": "src1", "name": "Reserve Datasets", "kind": "arco_datasets",
            "projects": [{"name": DEMO_PROJECT, "label": "Aug 2026"}],
            "reserving_classes": REVIEW_CLASSES,
            "datasets": [PAID, INCURRED, SELECTED, PRIOR, PREMIUM, REPORTED],
            "level_names": LEVELS,
        }],
        "pages": [overview, movement],
    }


def loss_development_monitor() -> dict:
    recent = {"field": YEAR, "values": ["2019", "2020", "2021", "2022", "2023", "2024", "2025"]}
    triangles = page("Development", [
        widget("heatmap", "Paid Loss Triangle", 0, 0, 6, 6, category=YEAR, series="Development",
               measures=[measure(PAID, "latest", "Paid", "compact")]),
        widget("line", "Paid Development By Accident Year", 6, 0, 6, 6, category="Development", series=YEAR,
               measures=[measure(PAID, "latest", "Paid", "compact")], filters=[recent]),
        widget("heatmap", "Paid To Incurred Ratio", 0, 6, 6, 5, category=YEAR, series="Development",
               measures=[measure(PAID_TO_INCURRED, "avg", "Paid To Incurred", "percent")]),
        widget("line", "Claim Closure Rate By Development Age", 6, 6, 6, 5, category="Development", series=YEAR,
               measures=[measure(CLOSURE, "avg", "Closed Share Of Reported", "percent")], filters=[recent]),
    ], filters=[{"field": "Segment", "values": [FAKE_CLASSES[0]]}])
    claims = page("Claims", [
        widget("kpi", "Reported Claims", 0, 0, 3, 2, category=YEAR, measures=[measure(REPORTED, "latest", "Reported Claims", "number", 0)]),
        widget("kpi", "Open Claims", 3, 0, 3, 2, category=YEAR, measures=[
            calc(f"latest([{REPORTED}]) - latest([{CLOSED}])", "Open Claims", "number", 0),
        ]),
        widget("kpi", "Case Incurred", 6, 0, 3, 2, category=YEAR, measures=[INCURRED_LATEST]),
        widget("kpi", "Paid Share Of Incurred", 9, 0, 3, 2, measures=[
            calc(f"latest([{PAID}]) / latest([{INCURRED}])", "Paid Share Of Incurred", "percent"),
        ]),
        widget("bar", "Reported And Open Claims By Accident Year", 0, 2, 6, 5, category=YEAR, measures=[
            measure(REPORTED, "latest", "Reported", "number", 0),
            calc(f"latest([{REPORTED}]) - latest([{CLOSED}])", "Open", "number", 0),
        ]),
        widget("bar", "Incurred Severity By Accident Year", 6, 2, 6, 5, category=YEAR, measures=[
            calc(f"latest([{INCURRED}]) / latest([{REPORTED}])", "Incurred Per Reported Claim", "number", 0),
        ], options={"labels": True}),
        widget("line", "Open Share Of Reported Claims By Accident Year", 0, 7, 6, 5, category=YEAR, measures=[
            calc(f"1 - latest([{CLOSED}]) / latest([{REPORTED}])", "Open Share Of Reported", "percent"),
        ]),
        widget("heatmap", "Reported Claims Triangle", 6, 7, 6, 5, category=YEAR, series="Development",
               measures=[measure(REPORTED, "latest", "Reported", "number", 0)]),
    ], filters=[{"field": "Segment", "values": [FAKE_CLASSES[0]]}])
    return {
        "name": "Loss Development Monitor",
        "description": "How one segment's triangles are developing: paid and reported triangles, development curves, paid-to-incurred and closure rates.",
        "sources": [{
            "id": "src1", "name": "Development Triangles", "kind": "arco_datasets",
            "projects": [{"name": FAKE_MAY, "label": MAY}],
            "reserving_classes": FAKE_CLASSES,
            "datasets": [PAID, INCURRED, REPORTED, CLOSED, PAID_TO_INCURRED, CLOSURE],
            "level_names": LEVELS,
        }],
        "pages": [triangles, claims],
    }


BOOK_FILTERS = [
    {"field": "PROD_CD", "label": "Product", "values": []},
    {"field": "STATE_CD", "label": "State", "values": []},
    {"field": "CHANNEL", "label": "Channel", "values": []},
]


def portfolio_mix_and_trends() -> dict:
    year = "acc_yrmo Year"
    loss_ratio = calc("sum([net_incurred]) / sum([Earned_Premium])", "Incurred Loss Ratio", "percent")
    frequency = calc("sum([reported]) / sum([Earned_Exposure]) * 100", "Claims Per 100 Exposures", "number", 2)
    severity = calc("sum([net_incurred]) / sum([reported])", "Incurred Per Claim", "number", 0)
    book = page("Book", [
        widget("kpi", "Earned Premium", 0, 0, 3, 2, category=year, measures=[measure("Earned_Premium", "sum", "Earned Premium", "compact")]),
        widget("kpi", "Net Incurred", 3, 0, 3, 2, category=year, measures=[measure("net_incurred", "sum", "Net Incurred", "compact")]),
        widget("kpi", "Incurred Loss Ratio", 6, 0, 3, 2, category=year, measures=[loss_ratio]),
        widget("kpi", "Claims Per 100 Exposures", 9, 0, 3, 2, category=year, measures=[frequency]),
        widget("bar", "Earned Premium By Accident Year And Product", 0, 2, 7, 5, category=year, series="PROD_CD",
               measures=[measure("Earned_Premium", "sum", "Earned Premium", "compact")], options={"stacked": True}),
        widget("share", "Earned Premium By Channel", 7, 2, 5, 2, category="CHANNEL",
               measures=[measure("Earned_Premium", "sum", "Earned Premium", "compact")]),
        widget("bar", "Incurred Loss Ratio By State", 7, 4, 5, 3, category="STATE_CD", measures=[loss_ratio],
               options={"horizontal": True}, sort={"by": "value", "dir": "desc"}),
        widget("heatmap", "Incurred Loss Ratio By State And Accident Year", 0, 7, 7, 5, category="STATE_CD", series=year, measures=[loss_ratio]),
        widget("scatter", "Frequency And Severity By Coverage", 7, 7, 5, 5, category="Coverage", measures=[frequency, severity]),
    ], filters=BOOK_FILTERS)
    trends = page("Trends", [
        widget("line", "Claims Per 100 Exposures By Accident Year", 0, 0, 6, 5, category=year, series="PROD_CD", measures=[frequency]),
        widget("line", "Incurred Per Claim By Accident Year", 6, 0, 6, 5, category=year, series="PROD_CD", measures=[severity]),
        widget("line", "Incurred Loss Ratio By Accident Year", 0, 5, 6, 5, category=year, series="CHANNEL", measures=[loss_ratio]),
        widget("table", "Coverages", 6, 5, 6, 5, category="Coverage", measures=[
            measure("Earned_Premium", "sum", "Earned Premium", "number", 0),
            measure("net_incurred", "sum", "Net Incurred", "number", 0),
            measure("reported", "sum", "Reported Claims", "number", 0),
            loss_ratio, severity,
        ], sort={"by": "value", "dir": "desc"}),
    ], filters=BOOK_FILTERS)
    return {
        "name": "Portfolio Mix And Trends",
        "description": "Where the book is growing and how it performs, straight from the project's imported source table: premium mix, loss ratio, frequency and severity.",
        "sources": [{
            "id": "src1", "name": "Source Table", "kind": "arco_source_table",
            "projects": [{"name": DEMO_PROJECT, "label": "Aug 2026"}],
            "dimensions": ["PROD_CD", "STATE_CD", "CHANNEL", "Coverage", "acc_yrmo:year"],
            "measures": ["Earned_Premium", "Earned_Exposure", "net_incurred", "gross_paid", "reported", "CWP"],
        }],
        "pages": [book, trends],
    }


def quarter_over_quarter_movement() -> dict:
    change = {"field": "Project", "base": MAY, "target": AUGUST, "mode": "delta"}
    # Accident years already a year old at the earlier valuation: their movement is development, not new business.
    prior_years = {"field": YEAR, "values": [str(year) for year in range(2017, 2026)]}
    paid = measure(PAID, "latest", "Paid", "compact")
    incurred = measure(INCURRED, "latest", "Case Incurred", "compact")
    reported = measure(REPORTED, "latest", "Reported Claims", "number", 0)
    movement = page("Movement", [
        widget("kpi", "Paid Loss", 0, 0, 3, 2, measures=[paid], compare=change),
        widget("kpi", "Case Incurred", 3, 0, 3, 2, measures=[incurred], compare=change),
        widget("kpi", "Reported Claims", 6, 0, 3, 2, measures=[reported], compare=change),
        widget("kpi", "Earned Premium", 9, 0, 3, 2, measures=[measure(PREMIUM, "sum", "Earned Premium", "compact")], compare=change),
        widget("bar", "Paid And Incurred Movement By Accident Year", 0, 2, 7, 5, category=YEAR, measures=[paid, incurred], compare=change),
        widget("bar", "Incurred Movement By Coverage", 7, 2, 5, 5, category="Coverage", measures=[incurred], compare=change,
               options={"horizontal": True}, sort={"by": "value", "dir": "desc"}),
        widget("heatmap", "Incurred Movement By Coverage And Accident Year", 0, 7, 7, 5, category="Coverage", series=YEAR,
               measures=[incurred], compare=change),
        widget("line", "Case Incurred By Accident Year At Each Valuation", 7, 7, 5, 5, category=YEAR, series="Project", measures=[incurred]),
    ], filters=["State", "Coverage"])
    detail = page("Segments", [
        widget("table", "Movement By Segment", 0, 0, 12, 6, category="Segment", measures=[paid, incurred, reported], compare=change),
        widget("bar", "Incurred Development On Prior Accident Years By Coverage", 0, 6, 6, 5, category="Coverage",
               measures=[incurred], compare=change, filters=[prior_years],
               options={"horizontal": True}, sort={"by": "value", "dir": "desc"}),
        widget("bar", "Reported Claims By Accident Year At Each Valuation", 6, 6, 6, 5, category=YEAR, series="Project", measures=[reported]),
    ], filters=["State", "Coverage"])
    return {
        "name": "Quarter Over Quarter Movement",
        "description": "What moved between two valuations of the same book: paid, case incurred, claim counts and premium, read from two projects side by side.",
        "sources": [{
            "id": "src1", "name": "Two Valuations", "kind": "arco_datasets",
            "projects": [{"name": FAKE_MAY, "label": MAY}, {"name": FAKE_AUGUST, "label": AUGUST}],
            "reserving_classes": FAKE_CLASSES,
            "datasets": [PAID, INCURRED, REPORTED, PREMIUM],
            "level_names": LEVELS,
        }],
        "pages": [movement, detail],
    }


NORMALIZE_SCRIPT = (
    "import { normalizeDashboard } from './ui/dashboard/dashboard_model.js';"
    "let text = '';"
    "process.stdin.setEncoding('utf8');"
    "process.stdin.on('data', (chunk) => { text += chunk; });"
    "process.stdin.on('end', () => process.stdout.write(JSON.stringify(normalizeDashboard(JSON.parse(text)))));"
)


def normalized(dashboard: dict) -> dict:
    """The dashboard as the page itself would save it.

    `normalizeDashboard` in the page's model owns the document's shape, so a
    sample goes through it rather than being written in a second dialect.
    """

    frontend = REPOSITORY_ROOT / "frontend"
    done = subprocess.run(
        [str(frontend / "node-portable" / "node.exe"), "--input-type=module", "-e", NORMALIZE_SCRIPT],
        cwd=frontend, input=json.dumps(dashboard), capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


SAMPLES = (reserve_review_summary, loss_development_monitor, portfolio_mix_and_trends, quarter_over_quarter_movement)


def build(only: str = "") -> int:
    from app_server import config
    from app_server.services import dashboard_service

    output = Path(config.DEFAULT_DASHBOARDS_DIR)
    for make in SAMPLES:
        dashboard = {"format": dashboard_service.DASHBOARD_FORMAT, "version": dashboard_service.DASHBOARD_VERSION, **make()}
        if only and dashboard["name"] != only:
            continue
        for index, item in enumerate(dashboard["pages"], start=1):
            item["id"] = f"p{index}"
        for source in dashboard["sources"]:
            table = dashboard_service.load_source({key: value for key, value in source.items() if key != "extract"})
            source["extract"] = table
            missing = table.get("missing") or []
            print(f"{dashboard['name']} / {source['name']}: {table['row_count']:,} rows, {len(table['columns'])} fields"
                  + (f", {len(missing)} dataset(s) not found" if missing else ""))
            for item in missing:
                print(f"    missing: {item.get('project', '')} | {item['reserving_class']} | {item['dataset_name']}")
        path = output / f"{dashboard['name']}{config.DASHBOARD_EXT}"
        dashboard_service._write_json(path, normalized(dashboard))
        print(f"  wrote {path} ({path.stat().st_size / 1024:,.0f} KB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the sample dashboards that ship with the app.")
    parser.add_argument("--on-server", action="store_true",
                        help="Run the project reads in place; use on the Server PC, where the projects are local disk.")
    parser.add_argument("--only", default="", help="Build just the sample with this name.")
    args = parser.parse_args(argv)
    if args.on_server:
        from app_server import config

        # Marks this process as one that reads the server folder itself.
        os.environ[config.RUNTIME_SERVER_ROOT_ENV] = config.get_root_path()
    return build(args.only)


if __name__ == "__main__":
    raise SystemExit(main())
