"""Configuration loading and validation."""

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


@dataclass(frozen=True)
class Settings:
    config_path: Path
    products_path: Path
    sales_path: Path
    database_path: Path
    output_path: Path
    days: int
    seed: int
    holding_cost: float
    fixed_order_cost: float
    fixed_threshold: int
    fixed_quantity: int
    up_to_threshold: int
    up_to_target: int
    extension: str
    capacity: int


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section [{name}] is required")
    return value


def load_config(path: str | Path) -> Settings:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as stream:
        data = tomllib.load(stream)
    files = _section(data, "files")
    simulation = _section(data, "simulation")
    costs = _section(data, "costs")
    policies = _section(data, "policies")
    fixed = _section(policies, "fixed_quantity")
    up_to = _section(policies, "order_up_to")
    extension_cfg = _section(data, "extension")
    extension = extension_cfg.get("selected", "")
    if extension not in {"", "storage"}:
        raise ValueError("This implementation supports core mode or the storage extension")
    storage = data.get("storage", {})
    if extension == "storage" and not isinstance(storage, dict):
        raise ValueError("[storage] must be a table when selected")
    settings = Settings(
        config_path=config_path,
        products_path=(config_path.parent / files["products"]).resolve(),
        sales_path=(config_path.parent / files["historical_sales"]).resolve(),
        database_path=(config_path.parent / files["database"]).resolve(),
        output_path=(config_path.parent / files["output_directory"]).resolve(),
        days=simulation["days"], seed=simulation["seed"],
        holding_cost=costs["holding_per_unit_per_day"],
        fixed_order_cost=costs["fixed_per_product_order"],
        fixed_threshold=fixed["threshold"], fixed_quantity=fixed["quantity"],
        up_to_threshold=up_to["threshold"], up_to_target=up_to["target"],
        extension=extension,
        capacity=storage.get("capacity_units", 0),
    )
    if type(settings.days) is not int or settings.days <= 0:
        raise ValueError("simulation.days must be a positive integer")
    if type(settings.seed) is not int:
        raise ValueError("simulation.seed must be an integer")
    if settings.holding_cost < 0 or settings.fixed_order_cost < 0:
        raise ValueError("Costs must be non-negative")
    if type(settings.fixed_threshold) is not int or settings.fixed_threshold < 0:
        raise ValueError("Fixed quantity threshold must be a non-negative integer")
    if type(settings.fixed_quantity) is not int or settings.fixed_quantity <= 0:
        raise ValueError("Fixed order quantity must be a positive integer")
    if type(settings.up_to_threshold) is not int or settings.up_to_threshold < 0:
        raise ValueError("Order-up-to threshold must be a non-negative integer")
    if type(settings.up_to_target) is not int or settings.up_to_target < settings.up_to_threshold:
        raise ValueError("Order-up-to target must be at least its threshold")
    if settings.extension == "storage" and (type(settings.capacity) is not int or settings.capacity <= 0):
        raise ValueError("storage.capacity_units must be a positive integer")
    return settings
