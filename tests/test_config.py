"""Tests for reading and validating the TOML configuration."""

from pathlib import Path
from tempfile import TemporaryDirectory

from inventory_simulator.config import ConfigError, load_config
from inventory_simulator.policies import FixedQuantityPolicy, OrderUpToPolicy
from tests.support import SAMPLES, VALIDATION, must_raise, run_tests, write_config


def test_storage_config_is_read_with_paths_relative_to_the_file():
    settings = load_config(SAMPLES / "config" / "storage.toml")
    assert settings.extension == "storage"
    assert settings.storage_capacity == 300
    assert settings.days == 60
    assert settings.holding_cost_cents == 2
    assert settings.order_cost_cents == 100
    assert settings.products_path == SAMPLES / "data" / "products.csv"
    assert isinstance(settings.policies[0], FixedQuantityPolicy)
    assert isinstance(settings.policies[1], OrderUpToPolicy)


def test_core_config_has_no_storage_limit():
    settings = load_config(SAMPLES / "config" / "core.toml")
    assert settings.extension == ""
    assert settings.storage_capacity is None
    assert settings.allocation_rules == ("unlimited",)


def test_supplied_invalid_config_is_rejected():
    error = must_raise(ConfigError, load_config, VALIDATION / "invalid_config.toml")
    assert "days must be positive" in str(error)


def test_other_extensions_are_rejected():
    for name in ("promotion.toml", "policy_tuning.toml"):
        error = must_raise(ConfigError, load_config, SAMPLES / "config" / name)
        assert "not implemented" in str(error), name


def test_bad_values():
    cases = [
        ("days must be positive", {"days": 0}),
        ("days must be an integer", {"days": 1.5}),
        ("days must be an integer", {"days": "true"}),  # TOML boolean
        ("seed must be non-negative", {"seed": -1}),
        ("holding_per_unit_per_day must be non-negative", {"holding": -0.02}),
        ("at most two decimal places", {"holding": 0.005}),
        ("threshold must be non-negative", {"fixed_threshold": -1}),
        ("quantity must be positive", {"fixed_quantity": 0}),
        ("must be at least the threshold", {"up_to_target": 19}),
        ("capacity_units must be positive", {"capacity": 0}),
    ]
    with TemporaryDirectory() as name:
        folder = Path(name)
        for expected, changes in cases:
            path = write_config(folder, **changes)
            error = must_raise(ConfigError, load_config, path)
            assert expected in str(error), (changes, str(error))


def test_order_up_to_target_equal_to_threshold_is_allowed():
    with TemporaryDirectory() as name:
        path = write_config(Path(name), up_to_threshold=20, up_to_target=20)
        settings = load_config(path)
    assert settings.policies[1].target == 20


def test_unknown_and_missing_keys():
    with TemporaryDirectory() as name:
        path = write_config(Path(name))
        text = path.read_text(encoding="utf-8")

        path.write_text(text.replace("threshold = 20\nquantity", "treshold = 20\nquantity"),
                        encoding="utf-8")
        assert "missing: threshold" in str(must_raise(ConfigError, load_config, path))

        path.write_text(text + "\n[extra]\nvalue = 1\n", encoding="utf-8")
        assert "unknown section" in str(must_raise(ConfigError, load_config, path))

        path.write_text(text.replace('currency = "EUR"', 'currency = "EUR"\nweeks = 3'),
                        encoding="utf-8")
        assert "unknown key(s): weeks" in str(must_raise(ConfigError, load_config, path))


def test_missing_file_and_broken_toml():
    with TemporaryDirectory() as name:
        folder = Path(name)
        error = must_raise(ConfigError, load_config, folder / "nope.toml")
        assert "not found" in str(error)

        broken = folder / "broken.toml"
        broken.write_text("[simulation\ndays = 3", encoding="utf-8")
        error = must_raise(ConfigError, load_config, broken)
        assert "not valid TOML" in str(error)


TESTS = [
    test_storage_config_is_read_with_paths_relative_to_the_file,
    test_core_config_has_no_storage_limit,
    test_supplied_invalid_config_is_rejected,
    test_other_extensions_are_rejected,
    test_bad_values,
    test_order_up_to_target_equal_to_threshold_is_allowed,
    test_unknown_and_missing_keys,
    test_missing_file_and_broken_toml,
]

if __name__ == "__main__":
    run_tests(TESTS)
