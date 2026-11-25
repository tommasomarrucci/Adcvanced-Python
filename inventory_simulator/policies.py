"""Replenishment policies.

A policy looks at every product's end-of-day stock and decides how many units to
order for the next morning. The simulation engine only ever calls
order_quantities(), so it runs any subclass without knowing which one it has.
"""

import numpy as np


class ReplenishmentPolicy:
    """Base class: order when stock is strictly below a threshold.

    Subclasses decide *how much* to order by overriding order_quantities().
    """

    name = "base"

    def __init__(self, threshold: int) -> None:
        if threshold < 0:
            raise ValueError(f"{self.name}: threshold must be non-negative, got {threshold}")
        self.threshold = threshold

    def needs_order(self, stock: np.ndarray) -> np.ndarray:
        """Boolean mask, one entry per product: True where stock < threshold."""
        return stock < self.threshold

    def order_quantities(self, stock: np.ndarray) -> np.ndarray:
        """Units to order for each product, given its end-of-day stock."""
        raise NotImplementedError("subclasses must implement order_quantities()")

    def parameters(self) -> dict[str, int]:
        return {"threshold": self.threshold}

    def __str__(self) -> str:
        values = ", ".join(f"{key}={value}" for key, value in self.parameters().items())
        return f"{self.name}({values})"

    def __repr__(self) -> str:
        return str(self)


class FixedQuantityPolicy(ReplenishmentPolicy):
    """Below the threshold, order the same fixed quantity every time."""

    name = "fixed_quantity"

    def __init__(self, threshold: int, quantity: int) -> None:
        super().__init__(threshold)
        if quantity <= 0:
            raise ValueError(f"{self.name}: quantity must be positive, got {quantity}")
        self.quantity = quantity

    def order_quantities(self, stock: np.ndarray) -> np.ndarray:
        return np.where(self.needs_order(stock), self.quantity, 0)

    def parameters(self) -> dict[str, int]:
        return {"threshold": self.threshold, "quantity": self.quantity}


class OrderUpToPolicy(ReplenishmentPolicy):
    """Below the threshold, order exactly enough to bring stock back to the target."""

    name = "order_up_to"

    def __init__(self, threshold: int, target: int) -> None:
        super().__init__(threshold)
        if target < threshold:
            raise ValueError(
                f"{self.name}: target ({target}) must be at least the threshold ({threshold})"
            )
        self.target = target

    def order_quantities(self, stock: np.ndarray) -> np.ndarray:
        # Where an order is needed, stock < threshold <= target, so target - stock > 0.
        return np.where(self.needs_order(stock), self.target - stock, 0)

    def parameters(self) -> dict[str, int]:
        return {"threshold": self.threshold, "target": self.target}
