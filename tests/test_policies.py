import unittest

import numpy as np

from inventory_simulator.policies import (FixedQuantityPolicy, OrderUpToPolicy,
                                          ReplenishmentPolicy)


class PolicyTests(unittest.TestCase):
    def test_fixed_quantity_orders_strictly_below_threshold(self):
        policy = FixedQuantityPolicy(threshold=20, quantity=40)
        stock = np.array([0, 19, 20, 21])
        self.assertEqual(policy.order_quantities(stock).tolist(), [40, 40, 0, 0])

    def test_order_up_to_fills_to_target(self):
        policy = OrderUpToPolicy(threshold=20, target=60)
        stock = np.array([0, 19, 20, 55])
        self.assertEqual(policy.order_quantities(stock).tolist(), [60, 41, 0, 0])

    def test_zero_threshold_never_orders(self):
        policy = FixedQuantityPolicy(threshold=0, quantity=5)
        self.assertEqual(policy.order_quantities(np.array([0, 3])).tolist(), [0, 0])

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            FixedQuantityPolicy(threshold=-1, quantity=5)
        with self.assertRaises(ValueError):
            FixedQuantityPolicy(threshold=5, quantity=0)
        with self.assertRaises(ValueError):
            OrderUpToPolicy(threshold=10, target=9)

    def test_base_class_cannot_decide_quantities(self):
        with self.assertRaises(NotImplementedError):
            ReplenishmentPolicy(threshold=5).order_quantities(np.array([1]))

    def test_str_shows_name_and_parameters(self):
        self.assertEqual(str(OrderUpToPolicy(20, 60)), "order_up_to(threshold=20, target=60)")


if __name__ == "__main__":
    unittest.main()
