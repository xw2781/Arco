"""Cut the Fake project's source table into the five pieces ResQ's saved imports read.

ResQ's ``NJ_Annual_Prod_202605_Fake`` does not import the source table itself. Its
saved imports read:

- three SQL Server tables on ``CO1ADBWPV01`` / ``Actuarial_NJ``,
  ``ResQ_Channel_{Loss,Reported_Counts,Closed_Counts}_202605_<suffix>``: the
  dated rows (``sys_yrmo`` not 0), each with its own measures;
- ``EP_EEX_NJ_2026May_channel_<suffix>.csv``: the rows carrying earned premium;
- ``Budget EEX and EP 2026 May_<suffix>.csv``: the rows carrying remaining budget.

This is how the ``_Fake_2`` pieces were cut from ``ResQ_Channel_202605_Fake_2.csv``
(checked row for row on 2026-11-09). The SQL tables copy the ``_Fake_2`` tables'
column types; an existing table of the new name is refused, never replaced.

Run ``py -3.10 tools/split_fake_source_for_resq.py --source <csv> --suffix Fake_3``
(``--dry-run`` writes nothing and prints the row counts).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

SERVER = "CO1ADBWPV01"
DATABASE = "Actuarial_NJ"
TEMPLATE_SUFFIX = "Fake_2"
KEYS = ["CO_CD", "PROD_CD", "STATE_CD", "CHANNEL", "IBNRCAT", "acc_yrmo", "sys_yrmo"]
TABLES = {
    "Loss": [
        "gross_paid", "expense", "salvage", "subro", "reserve", "recovery", "net_incurred",
        "gross_incurred", "net_incurred_capped_50k", "net_paid_capped_50k",
        "net_incurred_capped_100k", "net_paid_capped_100k", "net_incurred_capped_1000k",
        "net_paid_capped_1000k",
    ],
    "Reported_Counts": ["reported", "reported_ex_50k", "reported_ex_100k", "reported_ex_1000k"],
    "Closed_Counts": ["CWP", "CWOP", "CWP_ex_50k", "CWP_ex_100k", "CWP_ex_1000k"],
}
# (output name, source rows' marker column, {output column: source column}) in output order.
CSVS = [
    ("EP_EEX_NJ_2026May_channel_{suffix}.csv", "Earned_Premium", {
        "State_Cd": "STATE_CD", "Co_Cd": "CO_CD", "PROD_CD": "PROD_CD", "IBNRCAT": "IBNRCAT",
        "acc_yrmo": "acc_yrmo", "Channel": "CHANNEL",
        "Earned Exposure": "Earned_Exposure", "Earned Premium": "Earned_Premium",
    }),
    ("Budget EEX and EP 2026 May_{suffix}.csv", "Remaining_Budget_Premium", {
        "State_Cd": "STATE_CD", "Co_Cd": "CO_CD", "Channel": "CHANNEL", "PROD_CD": "PROD_CD",
        "IBNRCAT": "IBNRCAT", "acc_yrmo": "acc_yrmo",
        "Remaining Budget Exposure": "Remaining_Budget_Exposure",
        "Remaining Budget Premium": "Remaining_Budget_Premium",
    }),
]
INSERT_ROWS = 1000  # SQL Server's limit on rows in one VALUES list


def table_name(kind: str, suffix: str) -> str:
    return f"ResQ_Channel_{kind}_202605_{suffix}"


def read_source(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={key: str for key in KEYS[:5]})


def csv_frames(source: pd.DataFrame, suffix: str) -> dict[str, pd.DataFrame]:
    frames = {}
    for name, marker, columns in CSVS:
        rows = source[source[marker].notna()]
        frames[name.format(suffix=suffix)] = pd.DataFrame(
            {out: rows[src].to_numpy() for out, src in columns.items()})
    return frames


def table_frames(source: pd.DataFrame, suffix: str) -> dict[str, pd.DataFrame]:
    dated = source[source["sys_yrmo"] != 0]
    return {table_name(kind, suffix): dated[KEYS + cols] for kind, cols in TABLES.items()}


def _literal(value) -> str:
    if isinstance(value, str):
        return "N'" + value.replace("'", "''") + "'"
    if pd.isna(value):
        return "NULL"
    return repr(float(value)) if isinstance(value, float) else str(int(value))


def load_table(cursor, name: str, template: str, frame: pd.DataFrame) -> None:
    exists = cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?", name).fetchone()[0]
    if exists:
        raise SystemExit(f"{name} already exists; drop it by hand to replace it")
    cursor.execute(f"SELECT TOP 0 * INTO dbo.[{name}] FROM dbo.[{template}]")
    columns = ", ".join(f"[{c}]" for c in frame.columns)
    records = frame.astype(object).itertuples(index=False, name=None)
    batch: list[str] = []
    for record in records:
        batch.append("(" + ", ".join(_literal(v) for v in record) + ")")
        if len(batch) == INSERT_ROWS:
            cursor.execute(f"INSERT INTO dbo.[{name}] ({columns}) VALUES " + ", ".join(batch))
            batch = []
    if batch:
        cursor.execute(f"INSERT INTO dbo.[{name}] ({columns}) VALUES " + ", ".join(batch))
    count = cursor.execute(f"SELECT COUNT(*) FROM dbo.[{name}]").fetchone()[0]
    if count != len(frame):
        raise SystemExit(f"{name}: wrote {count} rows, expected {len(frame)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--suffix", required=True, help="for example Fake_3")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = read_source(args.source)
    csvs = csv_frames(source, args.suffix)
    tables = table_frames(source, args.suffix)
    for name, frame in {**csvs, **tables}.items():
        print(f"{name}: {len(frame)} rows")
    if args.dry_run:
        return

    import pyodbc

    for name, frame in csvs.items():
        target = args.source.parent / name
        if target.exists():
            raise SystemExit(f"{target} already exists")
        frame.to_csv(target, index=False)
    connection = pyodbc.connect(
        f"DRIVER={{SQL Server}};SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes",
        autocommit=False)
    cursor = connection.cursor()
    for kind in TABLES:
        name = table_name(kind, args.suffix)
        load_table(cursor, name, table_name(kind, TEMPLATE_SUFFIX), tables[name])
        connection.commit()
        print(f"loaded {name}")


if __name__ == "__main__":
    main()
