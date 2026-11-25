import tempfile
import unittest
from pathlib import Path

from inventory_simulator.config import ConfigError, load_config
from inventory_simulator.policies import FixedQuantityPolicy, OrderUpToPolicy

from support import SAMPLES, VALIDATION, write_config


class SuppliedConfigTests(unittest.TestCase):
    def test_storage_config_is_read_with_paths_relative_to_the_file(self):
        settings = load_config(SAMPLES / "config" / "storage.toml")
        self.assertEqual(settings.extension, "storage")
        self.assertEqual(settings.storage_capacity, 300)
        self.assertEqual(settings.days, 60)
        self.assertEqual(settings.holding_cost_cents, 2)
        self.assertEqual(settings.order_cost_cents, 100)
        self.assertEqual(settings.products_path, SAMPLES / "data" / "products.csv")
        self.assertIsInstance(settings.policies[0], FixedQuantityPolicy)
        self.assertIsInstance(settings.policies[1], OrderUpToPolicy)

    def test_core_config_has_no_storage_limit(self):
        settings = load_config(SAMPLES / "config" / "core.toml")
        self.assertEqual(settings.extension, "")
        self.assertIsNone(settings.storage_capacity)
        self.assertEqual(settings.allocation_rules, ("unlimited",))

    def test_supplied_invalid_config_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "days must be positive"):
            load_config(VALIDATION / "invalid_config.toml")

    def test_other_extensions_are_rejected(self):
        for name in ("promotion.toml", "policy_tuning.toml"):
            with self.subTest(name=name), self.assertRaisesRegex(ConfigError, "not implemented"):
                load_config(SAMPLES / "config" / name)


class InvalidValueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def assertRejected(self, pattern, **changes):
        path = write_config(self.folder, **changes)
        with self.assertRaisesRegex(ConfigError, pattern):
            load_config(path)

    def test_bad_values(self):
        cases = [
            ("days must be positive", {"days": 0}),
            ("days must be an integer", {"days": 1.5}),
            ("days must be an integer", {"days": "true"}),  # TOML boolean
            ("seed must be non-negative", {"seed": -1}),
            ("holding_per_unit_per_day must be non-negative", {"holding": -0.02}),
            ("at most two decimal places", {"holding": 0.005}),
            ("threshold must be non-negative", {"fixed_threshold": -1}),
            ("quantity must be positive", {"fixed_quantity": 0}),
            ("target .* must be at least the threshold", {"up_to_target": 19}),
            ("capacity_units must be positive", {"capacity": 0}),
        ]
        for pattern, changes in cases:
            with self.subTest(changes=changes):
                self.assertRejected(pattern, **changes)

    def test_order_up_to_target_equal_to_threshold_is_allowed(self):
        settings = load_config(write_config(self.folder, up_to_threshold=20, up_to_target=20))
        self.assertEqual(settings.policies[1].target, 20)

    def test_unknown_and_missing_keys(self):
        path = write_config(self.folder)
        text = path.read_text(encoding="utf-8")

        path.write_text(text.replace("threshold = 20\nquantity", "treshold = 20\nquantity"),
                        encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "missing: threshold"):
            load_config(path)

        path.write_text(text + "\n[extra]\nvalue = 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "unknown section"):
            load_config(path)

        path.write_text(text.replace('currency = "EUR"', 'currency = "EUR"\nweeks = 3'),
                        encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "unknown key.*weeks"):
            load_config(path)

    def test_missing_file_and_broken_toml(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(self.folder / "nope.toml")
        broken = self.folder / "broken.toml"
        broken.write_text("[simulation\ndays = 3", encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "not valid TOML"):
            load_config(broken)


if __name__ == "__main__":
    unittest.main()
