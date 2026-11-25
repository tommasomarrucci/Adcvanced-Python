"""Tests for the replenishment policy classes."""

import numpy as np

from inventory_simulator.policies import (FixedQuantityPolicy, OrderUpToPolicy,
                                          ReplenishmentPolicy)
from tests.support import must_raise, run_tests


def test_fixed_quantity_orders_strictly_below_threshold():
    policy = FixedQuantityPolicy(threshold=20, quantity=40)
    stock = np.array([0, 19, 20, 21])
    assert policy.order_quantities(stock).tolist() == [40, 40, 0, 0]


def test_order_up_to_fills_to_target():
    policy = OrderUpToPolicy(threshold=20, target=60)
    stock = np.array([0, 19, 20, 55])
    assert policy.order_quantities(stock).tolist() == [60, 41, 0, 0]


def test_zero_threshold_never_orders():
    policy = FixedQuantityPolicy(threshold=0, quantity=5)
    assert policy.order_quantities(np.array([0, 3])).tolist() == [0, 0]


def test_invalid_parameters():
    must_raise(ValueError, FixedQuantityPolicy, -1, 5)   # negative threshold
    must_raise(ValueError, FixedQuantityPolicy, 5, 0)    # quantity not positive
    must_raise(ValueError, OrderUpToPolicy, 10, 9)       # target below threshold


def test_base_class_cannot_decide_quantities():
    policy = ReplenishmentPolicy(threshold=5)
    must_raise(NotImplementedError, policy.order_quantities, np.array([1]))


def test_str_shows_name_and_parameters():
    assert str(OrderUpToPolicy(20, 60)) == "order_up_to(threshold=20, target=60)"


TESTS = [
    test_fixed_quantity_orders_strictly_below_threshold,
    test_order_up_to_fills_to_target,
    test_zero_threshold_never_orders,
    test_invalid_parameters,
    test_base_class_cannot_decide_quantities,
    test_str_shows_name_and_parameters,
]

if __name__ == "__main__":
    run_tests(TESTS)
