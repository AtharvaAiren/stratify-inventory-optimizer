from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt
from statistics import NormalDist
from typing import Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Config:
    days: int = 21
    training_days: int = 56
    minimum_history: int = 14
    review_days: int = 7
    holding_rate_daily: float = 0.0005
    order_cost: float = 20.0

    def __post_init__(self):
        if min(self.days, self.minimum_history, self.review_days) < 1:
            raise ValueError("Horizons must be positive")
        if self.training_days < self.minimum_history:
            raise ValueError("Training window is shorter than minimum history")
        if (
            not np.isfinite([self.holding_rate_daily, self.order_cost]).all()
            or min(self.holding_rate_daily, self.order_cost) < 0
        ):
            raise ValueError("Costs must be finite and nonnegative")


@dataclass
class Lot:
    units: float
    expires: pd.Timestamp


@dataclass(frozen=True)
class Item:
    cost: float
    lead: int
    shelf: int
    service: float

    def __post_init__(self):
        if not np.isfinite([self.cost, self.service]).all() or self.cost <= 0:
            raise ValueError("Invalid cost or service level")
        if self.lead < 1 or self.shelf < 1 or not 0.5 < self.service < 1:
            raise ValueError(
                "Lead/shelf life must be positive; service must be in (0.5, 1)"
            )


def forecast(history: pd.Series, dates: pd.DatetimeIndex, seasonal: bool) -> np.ndarray:
    """Shrink weekday means toward the overall mean using only observed history."""
    mean = float(history.mean())
    if not seasonal:
        return np.full(len(dates), mean)
    grouped = history.groupby(history.index.dayofweek).agg(["mean", "count"])
    return np.array(
        [
            (
                grouped.loc[d.dayofweek, "mean"] * grouped.loc[d.dayofweek, "count"]
                + 3 * mean
            )
            / (grouped.loc[d.dayofweek, "count"] + 3)
            if d.dayofweek in grouped.index
            else mean
            for d in dates
        ]
    )


def run_pair(
    demand: pd.Series,
    opening: float,
    item: Item,
    start: pd.Timestamp,
    config: Config,
    policy: Literal["static", "adaptive"],
) -> pd.DataFrame:
    """Receipts/expiry -> order decision -> demand -> FEFO fulfilment -> closing ledger."""
    if policy not in {"static", "adaptive"}:
        raise ValueError("Unknown policy")
    if not np.isfinite(opening) or opening < 0:
        raise ValueError("Opening inventory must be finite and nonnegative")
    demand = demand.sort_index()
    if (
        demand.index.has_duplicates
        or not np.isfinite(demand).all()
        or (demand < 0).any()
    ):
        raise ValueError("Demand must be unique, finite and nonnegative")
    dates = pd.date_range(start, periods=config.days)
    if not dates.isin(demand.index).all():
        raise ValueError(
            "Missing evaluation dates; absent demand is not assumed to be zero"
        )
    initial = demand.loc[demand.index < start].tail(config.training_days)
    if len(initial) < config.minimum_history:
        raise ValueError("Insufficient pre-start history")
    if not initial.index.equals(
        pd.date_range(initial.index.min(), initial.index.max())
    ):
        raise ValueError("Training history has missing dates")
    # Initial inventory age is unavailable in the case data: assume fresh at start.
    lots = (
        [Lot(float(opening), start + pd.Timedelta(days=item.shelf))] if opening else []
    )
    pipeline: list[tuple[pd.Timestamp, float]] = []
    rows = []
    z = NormalDist().inv_cdf(item.service)
    for day in dates:
        prior_close = sum(lot.units for lot in lots)
        expired = sum(lot.units for lot in lots if lot.expires <= day)
        lots = [lot for lot in lots if lot.expires > day]
        received = sum(qty for due, qty in pipeline if due <= day)
        pipeline = [(due, qty) for due, qty in pipeline if due > day]
        if received:
            lots.append(Lot(received, day + pd.Timedelta(days=item.shelf)))
        stock = sum(lot.units for lot in lots)
        # The current day's demand is never visible to the policy.
        history = (
            initial
            if policy == "static"
            else demand.loc[demand.index < day].tail(config.training_days)
        )
        safety = z * float(history.std(ddof=1)) * sqrt(item.lead)
        horizon = item.lead + config.review_days
        future = pd.date_range(day, periods=max(horizon, item.shelf + item.lead))
        predicted = forecast(history, future, seasonal=policy == "adaptive")
        reorder_point = float(predicted[: item.lead].sum()) + safety
        inventory_position = stock + sum(qty for _, qty in pipeline)
        order = 0
        if inventory_position < reorder_point:
            if policy == "static":
                desired = float(history.mean()) * (7 if item.shelf < 60 else 14)
            else:
                target = float(predicted[:horizon].sum()) + safety
                desired = max(0, target - inventory_position)
            # Avoid ordering more than forecast demand over the new lot's usable life.
            shelf_capacity = max(
                0, float(predicted[: item.lead + item.shelf].sum()) - inventory_position
            )
            order = max(0, ceil(min(desired, shelf_capacity)))
            if order:
                pipeline.append((day + pd.Timedelta(days=item.lead), order))
        actual = float(demand.loc[day])
        remaining = actual
        for lot in sorted(lots, key=lambda lot: lot.expires):
            take = min(lot.units, remaining)
            lot.units -= take
            remaining -= take
        lots = [lot for lot in lots if lot.units > 1e-10]
        closing = sum(lot.units for lot in lots)
        sold = actual - remaining
        assert abs(prior_close + received - expired - sold - closing) < 1e-7
        rows.append(
            dict(
                date=day,
                policy=policy,
                opening=stock,
                received=received,
                expired=expired,
                demand=actual,
                sold=sold,
                lost=remaining,
                closing=closing,
                order=order,
                on_order=sum(q for _, q in pipeline),
                reorder_point=reorder_point,
                inventory_position=inventory_position,
                holding_cost=(stock + closing)
                / 2
                * item.cost
                * config.holding_rate_daily,
                ordering_cost=config.order_cost if order else 0,
                waste_cost=expired * item.cost,
                lost_sales_at_cost=remaining * item.cost,
            )
        )
    return pd.DataFrame(rows)


def summarize(rows: pd.DataFrame) -> pd.DataFrame:
    output = []
    for (policy, store, sku), frame in rows.groupby(
        ["policy", "store", "sku"], sort=True
    ):
        demand, sold = frame.demand.sum(), frame.sold.sum()
        average_inventory = ((frame.opening + frame.closing) / 2).mean()
        output.append(
            dict(
                policy=policy,
                store=store,
                sku=sku,
                demand_units=demand,
                sold_units=sold,
                lost_units=frame.lost.sum(),
                fill_rate=sold / demand if demand else 1.0,
                average_inventory_units=average_inventory,
                turnover=sold / average_inventory if average_inventory else None,
                waste_units=frame.expired.sum(),
                orders=int((frame.order > 0).sum()),
                holding_cost=frame.holding_cost.sum(),
                ordering_cost=frame.ordering_cost.sum(),
                waste_cost=frame.waste_cost.sum(),
                lost_sales_at_cost=frame.lost_sales_at_cost.sum(),
            )
        )
    return pd.DataFrame(output)


def load_case(directory):
    """Read the supplied case; never ingest workbook-derived forecasts or KPIs."""
    from pathlib import Path

    directory = Path(directory)
    sheets = pd.read_excel(directory / "SKU-Store Sales.xlsx", sheet_name=None)
    frames = []
    for name, frame in sheets.items():
        required = {"Date", "Demand", "Opening Stock"}
        if not required.issubset(frame):
            raise ValueError(f"Missing sales columns in {name}")
        store, sku = name.split("_")
        frame = frame.rename(
            columns={"Date": "date", "Demand": "demand", "Opening Stock": "opening"}
        )
        frame["date"] = pd.to_datetime(frame.date).dt.normalize()
        frame["store"], frame["sku"] = store, sku
        frames.append(frame[["date", "store", "sku", "demand", "opening"]])
    sales = pd.concat(frames, ignore_index=True)
    if sales.duplicated(["date", "store", "sku"]).any():
        raise ValueError("Duplicate store-SKU-date rows")
    master = pd.read_excel(
        directory / "Given Data.xlsx", sheet_name="SKU_master"
    ).set_index("sku_id")
    supplier = pd.read_excel(
        directory / "Given Data.xlsx", sheet_name="Supplier_data"
    ).set_index("sku_id")
    if master.index.has_duplicates or supplier.index.has_duplicates:
        raise ValueError("Duplicate master/supplier keys")
    items = {
        sku: Item(
            float(row.unit_cost),
            int(row.avg_lead_time),
            int(row.shelf_life_days),
            float(supplier.loc[sku, "service_level"]),
        )
        for sku, row in master.iterrows()
    }
    return sales, items


def evaluate(directory, start, config=Config()):
    sales, items = load_case(directory)
    start = pd.Timestamp(start).normalize()
    runs = []
    for (store, sku), frame in sales.groupby(["store", "sku"], sort=True):
        frame = frame.set_index("date").sort_index()
        if start not in frame.index:
            raise ValueError(f"Start date missing for {store}/{sku}")
        for policy in ["static", "adaptive"]:
            result = run_pair(
                frame.demand,
                frame.loc[start, "opening"],
                items[sku],
                start,
                config,
                policy,
            )
            result["store"], result["sku"] = store, sku
            runs.append(result)
    daily = pd.concat(runs, ignore_index=True)
    return daily, summarize(daily)
