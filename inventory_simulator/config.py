"""Reading and validating the TOML configuration file."""

import json
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

from .money import to_cents
from .policies import FixedQuantityPolicy, OrderUpToPolicy, ReplenishmentPolicy

SUPPORTED_EXTENSIONS = {"", "storage"}  # "" means core only
ALLOCATION_RULES = ("product_id_ascending", "unit_margin_descending")

# Each section we accept, with the exact keys it must contain. Unknown sections and
# keys are rejected, so a typo like "treshold" is reported instead of ignored.
SECTION_KEYS = {
    "files": {"products", "historical_sales", "database", "output_directory"},
    "simulation": {"days", "seed", "currency"},
    "demand": {"model", "mean_source"},
    "costs": {"holding_per_unit_per_day", "fixed_per_product_order"},
    "extension": {"selected"},
    "storage": {"capacity_units", "allocation_rules"},
}
POLICY_KEYS = {
    "fixed_quantity": {"threshold", "quantity"},
    "order_up_to": {"threshold", "target"},
}


class ConfigError(ValueError):
    """The configuration file is missing, is not valid TOML, or has invalid values."""


class Settings(NamedTuple):
    """The validated configuration. Paths are absolute and money is in cents."""

    config_path: Path
    scenario: str  # the config file name without .toml, e.g. "storage"
    products_path: Path
    sales_path: Path
    database_path: Path
    output_dir: Path
    days: int
    seed: int
    holding_cost_cents: int
    order_cost_cents: int
    policies: tuple[ReplenishmentPolicy, ...]
    extension: str
    storage_capacity: int | None
    allocation_rules: tuple[str, ...]

    def to_json(self) -> str:
        """The effective configuration as JSON, stored with every simulation run."""
        return json.dumps(self._asdict(), default=str, sort_keys=True)


def load_config(path: str | Path) -> Settings:
    """Read, validate and return the settings in a TOML file.

    Relative paths inside the file are resolved against the file's own folder.
    """
    config_path = Path(path).expanduser().resolve()
    data = _read_toml(config_path)

    # Check the extension first: a promotion config should be told that the
    # extension is not implemented, not that [promotion] is an unknown section.
    extension = _table(data, "extension", SECTION_KEYS["extension"])["selected"]
    if extension not in SUPPORTED_EXTENSIONS:
        raise ConfigError(
            f"[extension] selected = {extension!r} is not implemented; "
            "use \"storage\" or \"\" (core only)"
        )

    unknown_sections = data.keys() - SECTION_KEYS.keys() - {"policies"}
    if unknown_sections:
        raise ConfigError(f"unknown section(s): {', '.join(sorted(unknown_sections))}")

    files = _table(data, "files", SECTION_KEYS["files"])
    simulation = _table(data, "simulation", SECTION_KEYS["simulation"])
    demand = _table(data, "demand", SECTION_KEYS["demand"])
    costs = _table(data, "costs", SECTION_KEYS["costs"])

    if _text(simulation, "simulation", "currency") != "EUR":
        raise ConfigError("[simulation] currency must be \"EUR\"")
    if _text(demand, "demand", "model") != "poisson":
        raise ConfigError("[demand] model must be \"poisson\"")
    if _text(demand, "demand", "mean_source") != "historical_daily_mean":
        raise ConfigError("[demand] mean_source must be \"historical_daily_mean\"")

    days = _integer(simulation, "simulation", "days")
    if days <= 0:
        raise ConfigError(f"[simulation] days must be positive, got {days}")
    seed = _integer(simulation, "simulation", "seed")
    if seed < 0:
        raise ConfigError(f"[simulation] seed must be non-negative, got {seed}")

    capacity = None
    rules: tuple[str, ...] = ("unlimited",)
    if extension == "storage":
        capacity, rules = _storage_settings(_table(data, "storage", SECTION_KEYS["storage"]))

    def resolve(key: str) -> Path:
        return (config_path.parent / _text(files, "files", key)).resolve()

    return Settings(
        config_path=config_path,
        scenario=config_path.stem,
        products_path=resolve("products"),
        sales_path=resolve("historical_sales"),
        database_path=resolve("database"),
        output_dir=resolve("output_directory"),
        days=days,
        seed=seed,
        holding_cost_cents=_cents(costs, "costs", "holding_per_unit_per_day"),
        order_cost_cents=_cents(costs, "costs", "fixed_per_product_order"),
        policies=_policies(data),
        extension=extension,
        storage_capacity=capacity,
        allocation_rules=rules,
    )


def output_dir_if_known(path: str | Path) -> Path | None:
    """Find the output folder of a config that may be invalid, or return None.

    Used only to decide where to write validation_report.txt when the
    configuration itself is rejected.
    """
    config_path = Path(path).expanduser().resolve()
    try:
        data = _read_toml(config_path)
    except ConfigError:
        return None
    files = data.get("files")
    if not isinstance(files, dict) or not isinstance(files.get("output_directory"), str):
        return None
    return (config_path.parent / files["output_directory"]).resolve()


# --- helpers ----------------------------------------------------------------


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path.name} is not valid TOML: {error}") from None


def _table(
    parent: dict[str, Any], key: str, expected: set[str], label: str | None = None
) -> dict[str, Any]:
    """Return parent[key] after checking it is a table with exactly the expected keys."""
    label = label or key
    table = parent.get(key)
    if not isinstance(table, dict):
        raise ConfigError(f"missing section [{label}]")
    missing = expected - table.keys()
    if missing:
        raise ConfigError(f"[{label}] is missing: {', '.join(sorted(missing))}")
    unknown = table.keys() - expected
    if unknown:
        raise ConfigError(f"[{label}] has unknown key(s): {', '.join(sorted(unknown))}")
    return table


def _integer(table: dict[str, Any], label: str, key: str) -> int:
    value = table[key]
    # bool is a subclass of int (True == 1), so "days = true" would otherwise pass.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"[{label}] {key} must be an integer, got {value!r}")
    return value


def _text(table: dict[str, Any], label: str, key: str) -> str:
    value = table[key]
    if not isinstance(value, str):
        raise ConfigError(f"[{label}] {key} must be a string, got {value!r}")
    return value


def _cents(table: dict[str, Any], label: str, key: str) -> int:
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"[{label}] {key} must be a number, got {value!r}")
    try:
        cents = to_cents(value)
    except ValueError as error:
        raise ConfigError(f"[{label}] {key} {error}") from None
    if cents < 0:
        raise ConfigError(f"[{label}] {key} must be non-negative, got {value!r}")
    return cents


def _policies(data: dict[str, Any]) -> tuple[ReplenishmentPolicy, ...]:
    policies = data.get("policies")
    if not isinstance(policies, dict):
        raise ConfigError("missing section [policies]")
    unknown = policies.keys() - POLICY_KEYS.keys()
    if unknown:
        raise ConfigError(f"unknown policy table(s): {', '.join(sorted(unknown))}")

    fixed = _table(
        policies, "fixed_quantity", POLICY_KEYS["fixed_quantity"], "policies.fixed_quantity"
    )
    up_to = _table(policies, "order_up_to", POLICY_KEYS["order_up_to"], "policies.order_up_to")
    fixed_threshold = _integer(fixed, "policies.fixed_quantity", "threshold")
    fixed_quantity = _integer(fixed, "policies.fixed_quantity", "quantity")
    up_to_threshold = _integer(up_to, "policies.order_up_to", "threshold")
    up_to_target = _integer(up_to, "policies.order_up_to", "target")
    try:
        # The policy classes check their own values (threshold >= 0 and so on),
        # so the rules live in one place.
        return (
            FixedQuantityPolicy(fixed_threshold, fixed_quantity),
            OrderUpToPolicy(up_to_threshold, up_to_target),
        )
    except ValueError as error:
        raise ConfigError(f"[policies] {error}") from None


def _storage_settings(storage: dict[str, Any]) -> tuple[int, tuple[str, ...]]:
    capacity = _integer(storage, "storage", "capacity_units")
    if capacity <= 0:
        raise ConfigError(f"[storage] capacity_units must be positive, got {capacity}")
    rules = storage["allocation_rules"]
    if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
        raise ConfigError("[storage] allocation_rules must be a list of strings")
    unknown = [rule for rule in rules if rule not in ALLOCATION_RULES]
    if unknown:
        raise ConfigError(
            f"[storage] unknown allocation rule(s) {unknown}; choose from {list(ALLOCATION_RULES)}"
        )
    if len(set(rules)) < 2:
        raise ConfigError("[storage] allocation_rules must list at least two different rules")
    return capacity, tuple(rules)
