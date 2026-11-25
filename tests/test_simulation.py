"""Tests for demand generation, storage allocation and the simulation engine."""

import numpy as np

from inventory_simulator.policies import FixedQuantityPolicy, OrderUpToPolicy
from inventory_simulator.simulation import (Catalogue, StorageLimit, allocate_capacity,
                                            allocation_priority, generate_demand, simulate)
from tests.support import must_raise, run_tests

HOLDING = 10  # cents per unit per day
ORDER_COST = 100  # cents per product order


def one_product(initial_stock: int = 5) -> Catalogue:
    # Price 2.00, cost 1.00, so each unit sold gives 1.00 gross profit.
    return Catalogue(["A"], [200], [100], [initial_stock], [3.0])


def three_products() -> Catalogue:
    return Catalogue(["A", "B", "C"], [250, 80, 900], [120, 30, 400],
                     [40, 100, 12], [8.0, 15.0, 1.5])


# --- a 4-day example worked out on paper -----------------------------------------
#
# Fixed quantity, threshold 3, quantity 4, initial stock 5, demand 3, 3, 5, 0:
#   day  start  sold  lost  end  order
#    1     5     3     0     2    4    (2 < 3)
#    2     6     3     0     3    0    (3 is not < 3)
#    3     3     3     2     0    4
#    4     4     0     0     4    0
# Revenue 9 * 2.00 = 18.00, COGS 9.00, holding (2+3+0+4) * 0.10 = 0.90,
# ordering 2 * 1.00 = 2.00, operating result 18 - 9 - 0.90 - 2 = 6.10.

HAND_DEMAND = np.array([[3], [3], [5], [0]])


def test_hand_example_fixed_quantity():
    result = simulate(one_product(), HAND_DEMAND, FixedQuantityPolicy(3, 4), HOLDING, ORDER_COST)
    assert result.stock_start[:, 0].tolist() == [5, 6, 3, 4]
    assert result.units_sold[:, 0].tolist() == [3, 3, 3, 0]
    assert result.lost_sales[:, 0].tolist() == [0, 0, 2, 0]
    assert result.stock_end[:, 0].tolist() == [2, 3, 0, 4]
    assert result.orders[:, 0].tolist() == [4, 0, 4, 0]
    assert int(result.revenue_cents.sum()) == 1800
    assert int(result.cogs_cents.sum()) == 900
    assert int(result.holding_cost_cents.sum()) == 90
    assert int(result.ordering_cost_cents.sum()) == 200
    assert result.total_operating_result_cents() == 610


def test_hand_example_order_up_to():
    # Same days, but on day 3 it orders 6 - 0 = 6, so day 4 ends with 6 units.
    # Holding (2+3+0+6) * 0.10 = 1.10, operating result 18 - 9 - 1.10 - 2 = 5.90.
    result = simulate(one_product(), HAND_DEMAND, OrderUpToPolicy(3, 6), HOLDING, ORDER_COST)
    assert result.orders[:, 0].tolist() == [4, 0, 6, 0]
    assert result.stock_end[:, 0].tolist() == [2, 3, 0, 6]
    assert result.total_operating_result_cents() == 590


def test_final_day_order_is_charged_and_outstanding():
    demand = np.array([[3], [3], [5], [2]])  # day 4 ends with 2 < 3, so it orders
    result = simulate(one_product(), demand, FixedQuantityPolicy(3, 4), HOLDING, ORDER_COST)
    assert result.orders[-1, 0] == 4
    assert result.stock_end[-1, 0] == 2  # the 4 units are not on hand
    assert int(result.ordering_cost_cents.sum()) == 300


# --- stock rules -------------------------------------------------------------------


def test_orders_arrive_the_next_morning():
    catalogue = three_products()
    demand = generate_demand(catalogue.mean_demand, 60, seed=7)
    result = simulate(catalogue, demand, FixedQuantityPolicy(20, 40), 2, 100)
    # Start of day d+1 = end of day d + what was ordered on day d.
    expected = result.stock_end[:-1] + result.orders[:-1]
    assert (result.stock_start[1:] == expected).all()
    assert (result.stock_start[0] == catalogue.initial_stock).all()


def test_stock_is_conserved_and_never_negative():
    catalogue = three_products()
    demand = generate_demand(catalogue.mean_demand, 60, seed=7)
    for policy in (FixedQuantityPolicy(20, 40), OrderUpToPolicy(20, 60)):
        result = simulate(catalogue, demand, policy, 2, 100)
        received = result.orders[:-1].sum(axis=0)  # last day's orders never arrive
        final = catalogue.initial_stock + received - result.units_sold.sum(axis=0)
        assert (final == result.stock_end[-1]).all(), str(policy)
        assert (result.stock_end >= 0).all(), str(policy)
        assert (result.units_sold + result.lost_sales == demand).all(), str(policy)


def test_zero_demand_means_no_sales_and_no_orders_above_threshold():
    demand = np.zeros((10, 3), dtype=np.int64)
    result = simulate(three_products(), demand, FixedQuantityPolicy(5, 10), 2, 100)
    assert int(result.units_sold.sum()) == 0
    assert int(result.lost_sales.sum()) == 0
    assert int(result.orders.sum()) == 0  # every product starts above 5
    assert int(result.revenue_cents.sum()) == 0


def test_demand_shape_must_match_catalogue():
    must_raise(ValueError, simulate, three_products(), np.zeros((5, 2)),
               FixedQuantityPolicy(5, 10), 2, 100)


# --- demand ------------------------------------------------------------------------

MEANS = np.array([8.0, 15.0, 0.0])


def test_same_seed_same_demand():
    first = generate_demand(MEANS, 60, seed=2026)
    second = generate_demand(MEANS, 60, seed=2026)
    assert (first == second).all()


def test_different_seed_different_demand():
    assert not (generate_demand(MEANS, 60, 1) == generate_demand(MEANS, 60, 2)).all()


def test_shape_values_and_long_run_mean():
    demand = generate_demand(MEANS, 20_000, seed=3)
    assert demand.shape == (20_000, 3)
    assert (demand >= 0).all()
    assert (demand[:, 2] == 0).all()  # a zero mean gives zero demand
    assert (abs(demand.mean(axis=0) - MEANS) <= 0.1).all()


# --- storage extension ---------------------------------------------------------------


def two_products() -> Catalogue:
    # B has the higher unit margin (3.00 against 2.00), A the lower product id.
    return Catalogue(["A", "B"], [300, 400], [100, 100], [5, 5], [5.0, 5.0])


def test_priority_orders():
    assert allocation_priority(two_products(), "product_id_ascending") == [0, 1]
    assert allocation_priority(two_products(), "unit_margin_descending") == [1, 0]


def test_equal_margins_fall_back_to_product_id():
    catalogue = Catalogue(["B", "A"], [300, 300], [100, 100], [0, 0], [1.0, 1.0])
    assert allocation_priority(catalogue, "unit_margin_descending") == [1, 0]


def test_allocation_never_exceeds_request_or_space():
    requested = np.array([8, 8])
    assert allocate_capacity(requested, 12, [0, 1]).tolist() == [8, 4]
    assert allocate_capacity(requested, 12, [1, 0]).tolist() == [4, 8]
    assert allocate_capacity(requested, 16, [0, 1]).tolist() == [8, 8]  # exact fit
    assert allocate_capacity(requested, 100, [0, 1]).tolist() == [8, 8]
    assert allocate_capacity(requested, 0, [0, 1]).tolist() == [0, 0]


def test_rules_change_who_gets_the_space():
    demand = np.array([[5, 5], [0, 0]])
    policy = FixedQuantityPolicy(threshold=1, quantity=8)
    by_id = simulate(two_products(), demand, policy, 2, 100,
                     StorageLimit(12, "product_id_ascending"))
    by_margin = simulate(two_products(), demand, policy, 2, 100,
                         StorageLimit(12, "unit_margin_descending"))
    assert by_id.orders[0].tolist() == [8, 4]
    assert by_margin.orders[0].tolist() == [4, 8]


def test_initial_stock_equal_to_capacity_is_allowed_one_more_is_not():
    demand = np.zeros((3, 2), dtype=np.int64)
    policy = FixedQuantityPolicy(1, 8)
    simulate(two_products(), demand, policy, 2, 100, StorageLimit(10, "product_id_ascending"))
    must_raise(ValueError, simulate, two_products(), demand, policy, 2, 100,
               StorageLimit(9, "product_id_ascending"))


def test_capacity_is_respected_every_day():
    catalogue = three_products()
    demand = generate_demand(catalogue.mean_demand, 60, seed=11)
    for rule in ("product_id_ascending", "unit_margin_descending"):
        result = simulate(catalogue, demand, OrderUpToPolicy(30, 90), 2, 100,
                          StorageLimit(160, rule))
        # Units held tonight plus units arriving tomorrow morning.
        assert ((result.stock_end + result.orders).sum(axis=1) <= 160).all(), rule
        assert (result.stock_start.sum(axis=1) <= 160).all(), rule


TESTS = [
    test_hand_example_fixed_quantity,
    test_hand_example_order_up_to,
    test_final_day_order_is_charged_and_outstanding,
    test_orders_arrive_the_next_morning,
    test_stock_is_conserved_and_never_negative,
    test_zero_demand_means_no_sales_and_no_orders_above_threshold,
    test_demand_shape_must_match_catalogue,
    test_same_seed_same_demand,
    test_different_seed_different_demand,
    test_shape_values_and_long_run_mean,
    test_priority_orders,
    test_equal_margins_fall_back_to_product_id,
    test_allocation_never_exceeds_request_or_space,
    test_rules_change_who_gets_the_space,
    test_initial_stock_equal_to_capacity_is_allowed_one_more_is_not,
    test_capacity_is_respected_every_day,
]

if __name__ == "__main__":
    run_tests(TESTS)
