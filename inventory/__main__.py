import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .model import Config, evaluate


def main():
    parser = argparse.ArgumentParser(
        description="Compare dated inventory policies on the Stratify case."
    )
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--start", default="2024-03-20")
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--output", type=Path, default=Path("reports/latest"))
    args = parser.parse_args()
    config = Config(days=args.days)
    daily, kpis = evaluate(args.data, args.start, config)
    args.output.mkdir(parents=True, exist_ok=True)
    daily.to_csv(args.output / "daily.csv", index=False)
    kpis.to_csv(args.output / "kpis.csv", index=False)
    totals = []
    for policy, frame in kpis.groupby("policy"):
        demand = frame.demand_units.sum()
        totals.append(
            dict(
                policy=policy,
                fill_rate=float(frame.sold_units.sum() / demand) if demand else 1,
                lost_units=float(frame.lost_units.sum()),
                waste_units=float(frame.waste_units.sum()),
                holding_cost=float(frame.holding_cost.sum()),
                ordering_cost=float(frame.ordering_cost.sum()),
                waste_cost=float(frame.waste_cost.sum()),
                lost_sales_at_cost=float(frame.lost_sales_at_cost.sum()),
            )
        )
    summary = {
        "start": args.start,
        "config": asdict(config),
        "policies": totals,
        "inputs": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in args.data.glob("*.xlsx")
        },
        "scope": "Case-data replay; cost assumptions are configurable engineering assumptions.",
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    html = '<!doctype html><meta charset="utf-8"><title>Inventory Rewired</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:right}h1,h2{color:#163d56}</style>'
    html += "<h1>Inventory Rewired</h1><p>Static versus adaptive replenishment. Both policies use the same demand, opening inventory and cost assumptions. No forecast observes future demand.</p>"
    html += "<h2>Portfolio totals</h2>" + pd.DataFrame(totals).to_html(
        index=False, float_format=lambda x: f"{x:.3f}"
    )
    html += "<h2>Store–SKU comparisons</h2>" + kpis.to_html(
        index=False, float_format=lambda x: f"{x:.3f}"
    )
    (args.output / "report.html").write_text(html)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
