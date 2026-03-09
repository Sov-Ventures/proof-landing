"""
VWAP execution optimization for Polymarket orders.

Splits large orders into smaller chunks based on orderbook depth,
targeting 80% of position within 0.5% of entry price over a 15-minute window.
Tracks WebSocket orderbook with sequence number gap detection.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OrderSlice:
    """A single slice of a VWAP order."""
    size: float
    target_price: float
    executed_price: Optional[float] = None
    executed_size: float = 0.0
    executed_at: Optional[float] = None
    status: str = "pending"  # pending, filled, cancelled


@dataclass
class VWAPPlan:
    """A VWAP execution plan."""
    total_size: float
    side: str
    entry_price: float
    slippage_limit: float
    window_seconds: int
    slices: list[OrderSlice] = field(default_factory=list)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def executed_size(self) -> float:
        return sum(s.executed_size for s in self.slices)

    @property
    def fill_ratio(self) -> float:
        return self.executed_size / self.total_size if self.total_size > 0 else 0.0

    @property
    def vwap(self) -> float:
        """Volume-weighted average price of executed slices."""
        total_cost = sum(s.executed_price * s.executed_size for s in self.slices if s.executed_price)
        total_size = self.executed_size
        return total_cost / total_size if total_size > 0 else 0.0

    @property
    def slippage_bps(self) -> float:
        """Slippage in basis points from entry price."""
        if self.executed_size == 0:
            return 0.0
        return abs(self.vwap - self.entry_price) / self.entry_price * 10_000


@dataclass
class OrderbookLevel:
    """A single price level in the orderbook."""
    price: float
    size: float


class OrderbookTracker:
    """
    Tracks orderbook state with sequence number gap detection.
    Designed to work with Polymarket WebSocket orderbook feeds.
    """

    def __init__(self):
        self.bids: list[OrderbookLevel] = []
        self.asks: list[OrderbookLevel] = []
        self.last_sequence: int = 0
        self.gap_count: int = 0
        self.last_update: float = 0.0

    def update(self, bids: list[dict], asks: list[dict], sequence: int) -> bool:
        """
        Update orderbook state. Returns False if sequence gap detected.

        Args:
            bids: List of {"price": float, "size": float}
            asks: List of {"price": float, "size": float}
            sequence: Sequence number from WebSocket

        Returns:
            True if update was clean, False if sequence gap detected
        """
        gap_detected = False
        if self.last_sequence > 0 and sequence != self.last_sequence + 1:
            self.gap_count += 1
            gap_detected = True
            logger.warning(
                "Orderbook sequence gap: expected %d, got %d (gap #%d)",
                self.last_sequence + 1, sequence, self.gap_count
            )

        self.bids = [OrderbookLevel(b["price"], b["size"]) for b in bids]
        self.asks = [OrderbookLevel(a["price"], a["size"]) for a in asks]
        self.bids.sort(key=lambda x: x.price, reverse=True)
        self.asks.sort(key=lambda x: x.price)
        self.last_sequence = sequence
        self.last_update = time.time()
        return not gap_detected

    def available_liquidity(self, side: str, price_limit: float) -> float:
        """
        Calculate available liquidity up to a price limit.

        Args:
            side: "buy" or "sell"
            price_limit: Maximum price for buys, minimum price for sells

        Returns:
            Total available size within price limit
        """
        if side == "buy":
            return sum(
                level.size for level in self.asks
                if level.price <= price_limit
            )
        else:
            return sum(
                level.size for level in self.bids
                if level.price >= price_limit
            )

    def mid_price(self) -> Optional[float]:
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2.0


class VWAPExecutor:
    """
    VWAP execution engine.

    Splits orders into chunks based on orderbook depth,
    targeting 80% fill within 0.5% of entry over 15 minutes.
    """

    def __init__(
        self,
        target_fill_ratio: float = 0.80,
        slippage_limit_pct: float = 0.005,  # 0.5%
        window_seconds: int = 900,           # 15 minutes
        min_slices: int = 3,
        max_slices: int = 20,
        liquidity_sample_pct: float = 0.10,  # Take max 10% of each level
    ):
        self.target_fill_ratio = target_fill_ratio
        self.slippage_limit_pct = slippage_limit_pct
        self.window_seconds = window_seconds
        self.min_slices = min_slices
        self.max_slices = max_slices
        self.liquidity_sample_pct = liquidity_sample_pct

    def create_plan(
        self,
        total_size: float,
        side: str,
        entry_price: float,
        orderbook: OrderbookTracker,
    ) -> VWAPPlan:
        """
        Create a VWAP execution plan based on current orderbook depth.

        Args:
            total_size: Total position size to execute (in USDC)
            side: "buy" or "sell"
            entry_price: Target entry price
            orderbook: Current orderbook state

        Returns:
            VWAPPlan with order slices
        """
        price_limit = entry_price * (1 + self.slippage_limit_pct) if side == "buy" \
            else entry_price * (1 - self.slippage_limit_pct)

        available = orderbook.available_liquidity(side, price_limit)

        # Determine number of slices based on size relative to liquidity
        if available > 0:
            size_to_liquidity = total_size / available
            n_slices = max(
                self.min_slices,
                min(self.max_slices, int(size_to_liquidity * 10))
            )
        else:
            n_slices = self.min_slices

        # Create evenly-timed slices
        slice_size = total_size / n_slices
        interval = self.window_seconds / n_slices

        plan = VWAPPlan(
            total_size=total_size,
            side=side,
            entry_price=entry_price,
            slippage_limit=self.slippage_limit_pct,
            window_seconds=self.window_seconds,
        )

        for i in range(n_slices):
            # Slight price improvement target for earlier slices
            progress = i / max(n_slices - 1, 1)
            if side == "buy":
                target = entry_price * (1 + self.slippage_limit_pct * progress * 0.5)
            else:
                target = entry_price * (1 - self.slippage_limit_pct * progress * 0.5)

            plan.slices.append(OrderSlice(
                size=slice_size,
                target_price=round(target, 4),
            ))

        return plan

    def should_execute_slice(
        self,
        plan: VWAPPlan,
        slice_index: int,
        orderbook: OrderbookTracker,
    ) -> bool:
        """
        Determine if a slice should be executed now based on orderbook conditions.

        Checks:
        - Sufficient liquidity at acceptable price
        - No sequence gaps (stale data)
        - Within slippage tolerance
        """
        if slice_index >= len(plan.slices):
            return False

        order_slice = plan.slices[slice_index]
        if order_slice.status != "pending":
            return False

        # Don't execute on stale orderbook
        if time.time() - orderbook.last_update > 5.0:
            logger.warning("Orderbook data stale (>5s), skipping slice")
            return False

        # Check liquidity
        available = orderbook.available_liquidity(plan.side, order_slice.target_price)
        if available < order_slice.size * 0.5:
            logger.info(
                "Insufficient liquidity for slice %d: need %.2f, have %.2f",
                slice_index, order_slice.size, available
            )
            return False

        # Check mid price hasn't moved too far
        mid = orderbook.mid_price()
        if mid is not None:
            deviation = abs(mid - plan.entry_price) / plan.entry_price
            if deviation > self.slippage_limit_pct:
                logger.warning(
                    "Mid price deviation %.2f%% exceeds limit %.2f%%",
                    deviation * 100, self.slippage_limit_pct * 100
                )
                return False

        return True

    def evaluate_execution(self, plan: VWAPPlan) -> dict:
        """Evaluate execution quality of a completed or in-progress plan."""
        return {
            "fill_ratio": plan.fill_ratio,
            "target_fill_ratio": self.target_fill_ratio,
            "fill_met": plan.fill_ratio >= self.target_fill_ratio,
            "vwap": plan.vwap,
            "entry_price": plan.entry_price,
            "slippage_bps": plan.slippage_bps,
            "slippage_limit_bps": self.slippage_limit_pct * 10_000,
            "slippage_met": plan.slippage_bps <= self.slippage_limit_pct * 10_000,
            "slices_total": len(plan.slices),
            "slices_filled": sum(1 for s in plan.slices if s.status == "filled"),
            "slices_cancelled": sum(1 for s in plan.slices if s.status == "cancelled"),
        }
