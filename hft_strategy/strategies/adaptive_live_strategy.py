# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import time
from typing import Optional

from hft_strategy.infrastructure.local_order_book import LocalOrderBook
from hft_strategy.domain.trade_context import StrategyState
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.interfaces import IExecutionHandler

from hft_strategy.services.analytics import MarketAnalytics
from hft_strategy.services.wall_detector import WallDetector
from hft_strategy.services.trade_manager import TradeManager

logger = logging.getLogger("ORCHESTRATOR")

class AdaptiveWallStrategy:
    def __init__(self, 
                 executor: IExecutionHandler, 
                 cfg: StrategyParameters,
                 gateway: Optional[object] = None,
                 notifier: Optional[object] = None): # [FIX] Added notifier
        
        self.cfg = cfg
        self.lob = LocalOrderBook()
        self._lock = asyncio.Lock()
        
        self.analytics = MarketAnalytics(executor, cfg)
        self.detector = WallDetector(cfg)
        # [FIX] Pass notifier to TradeManager
        self.trade_manager = TradeManager(executor, cfg, gateway, notifier)
        
        asyncio.create_task(self.analytics.start())

    async def on_execution(self, event):
        await self.trade_manager.handle_execution(event)

    def on_tick(self, tick):
        pass

    async def on_depth(self, snapshot):
        if self._lock.locked(): return
        
        async with self._lock:
            if hasattr(snapshot, 'bids') and not isinstance(snapshot.bids, dict):
                self.lob.apply_snapshot(snapshot)
            else:
                self.lob.apply_update(snapshot)
            
            if not self.lob.bids or not self.lob.asks: return

            bg_vol = self.lob.get_background_volume()
            self.analytics.update_background_volume(bg_vol)

            state = self.trade_manager.state

            if state == StrategyState.IDLE:
                await self._process_idle()

            elif state == StrategyState.ORDER_PLACED:
                await self._process_order_placed()

            elif state == StrategyState.IN_POSITION:
                await self._process_in_position()

    async def _process_idle(self):
        signal = self.detector.detect_signal(
            self.lob, 
            self.analytics.avg_background_vol
        )
        
        if signal:
            step_size = self.cfg.lot_size if self.cfg.lot_size > 0 else 1.0
            raw_qty = self.cfg.order_amount_usdt / signal["entry_price"]
            qty_final = round(int(raw_qty / step_size) * step_size, 8)

            if qty_final < self.cfg.min_qty: return

            tp_price, sl_price = self.analytics.calculate_exits(
                side=signal["side"],
                entry_price=signal["entry_price"],
                wall_price=signal["wall_price"]
            )

            await self.trade_manager.open_position(
                side=signal["side"],
                wall_price=signal["wall_price"],
                entry_price=signal["entry_price"],
                qty=qty_final,
                stop_loss=sl_price,
                take_profit=tp_price
            )
            
    def set_graceful_stop(self):
        """Вызывается оркестратором, когда монета вылетает из топа."""
        self.trade_manager.request_stop()
    
    @property
    def can_be_deleted(self) -> bool:
        """Спрашиваем у менеджера, все ли дела завершены."""
        return self.trade_manager.can_be_deleted

    # [FIX] Correct indentation for these methods:
    
    async def _process_order_placed(self):
        ctx = self.trade_manager.ctx
        if not ctx: return

        best_bid_p = self.lob.get_best("Buy")
        best_ask_p = self.lob.get_best("Sell")
        
        current_wall_v = 0.0
        for t in range(-2, 3):
            check_p = ctx.wall_price + (t * self.cfg.tick_size)
            current_wall_v = max(current_wall_v, self.lob.get_volume(ctx.side, check_p))

        threshold = self.analytics.avg_background_vol * self.cfg.wall_ratio_threshold * 0.4 
        
        wall_collapsed = current_wall_v < threshold
        
        price_ran_away = False
        if ctx.side == "Buy":
            price_ran_away = best_bid_p > (ctx.entry_price + 5 * self.cfg.tick_size)
        else:
            price_ran_away = best_ask_p < (ctx.entry_price - 5 * self.cfg.tick_size)

        timed_out = (time.time() - ctx.placed_ts) > 30.0 

        if wall_collapsed or price_ran_away or timed_out:
            reason = "Wall Collapsed" if wall_collapsed else ("Price Runaway" if price_ran_away else "Timeout 30s")
            logger.info(f"🧱 {reason} (Vol: {current_wall_v:.1f}). Cancelling entry...")
            await self.trade_manager.cancel_entry(reason=reason)

    async def _process_in_position(self):
        ctx = self.trade_manager.ctx
        if not ctx or ctx.filled_qty <= 1e-9: return

        best_bid = self.lob.get_best("Buy")
        best_ask = self.lob.get_best("Sell")

        exit_price = best_bid if ctx.side == "Buy" else best_ask
        
        wall_broken = (exit_price < ctx.wall_price) if ctx.side == "Buy" else (exit_price > ctx.wall_price)
        
        delta = (exit_price - ctx.entry_price) if ctx.side == "Buy" else (ctx.entry_price - exit_price)
        pnl_ticks = delta / self.cfg.tick_size
        stop_hit = pnl_ticks <= -self.cfg.stop_loss_ticks

        if wall_broken or stop_hit:
            reason = f"Wall Broken (Price: {exit_price})" if wall_broken else f"Hard Stop Hit ({pnl_ticks:.1f} ticks)"
            logger.warning(f"🚨 {reason} ({pnl_ticks:.1f} ticks). Panic Exiting!")
            await self.trade_manager.panic_exit(reason=reason)