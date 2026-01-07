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
                 gateway: Optional[object] = None):
        
        self.cfg = cfg
        self.lob = LocalOrderBook()
        self._lock = asyncio.Lock()
        
        self.analytics = MarketAnalytics(executor, cfg)
        self.detector = WallDetector(cfg)
        self.trade_manager = TradeManager(executor, cfg, gateway)
        
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
            # 1. Расчет объема с округлением до лота (Fix ErrCode 10001)
            step_size = self.cfg.lot_size if self.cfg.lot_size > 0 else 1.0
            raw_qty = self.cfg.order_amount_usdt / signal["entry_price"]
            # Округляем вниз до ближайшего шага
            qty_final = round(int(raw_qty / step_size) * step_size, 8)

            if qty_final < self.cfg.min_qty: return

            # 2. Получаем Атомарные уровни TP/SL из аналитики
            tp_price, sl_price = self.analytics.calculate_exits(
                side=signal["side"],
                entry_price=signal["entry_price"],
                wall_price=signal["wall_price"]
            )

            # 3. Отправляем Атомарный ордер (Вход + Страховка)
            await self.trade_manager.open_position(
                side=signal["side"],
                wall_price=signal["wall_price"],
                entry_price=signal["entry_price"],
                qty=qty_final,
                stop_loss=sl_price,
                take_profit=tp_price
            )

    async def _process_order_placed(self):
        ctx = self.trade_manager.ctx
        if not ctx: return

        current_wall_v = self.lob.get_volume(ctx.side, ctx.wall_price)
        threshold = self.analytics.avg_background_vol * self.cfg.wall_ratio_threshold * 0.5
        
        wall_gone = current_wall_v < threshold
        timed_out = (time.time() - ctx.placed_ts) > 15.0

        if wall_gone or timed_out:
            reason = "Wall collapsed" if wall_gone else "Timeout"
            logger.debug(f"🧱 {reason}. Cancelling entry...")
            await self.trade_manager.cancel_entry()

    async def _process_in_position(self):
        ctx = self.trade_manager.ctx
        if not ctx or ctx.filled_qty <= 1e-9: return

        best_bid = self.lob.get_best("Buy")
        best_ask = self.lob.get_best("Sell")
        
        exit_price = best_bid if ctx.side == "Buy" else best_ask
        
        # Условия Panic Exit (как второй слой защиты, если Hard SL не сработал или для скорости)
        wall_broken = (exit_price < ctx.wall_price) if ctx.side == "Buy" else (exit_price > ctx.wall_price)
        
        delta = (exit_price - ctx.entry_price) if ctx.side == "Buy" else (ctx.entry_price - exit_price)
        pnl_ticks = delta / self.cfg.tick_size
        stop_hit = pnl_ticks <= -self.cfg.stop_loss_ticks

        if wall_broken or stop_hit:
            reason = "WALL BREACH" if wall_broken else "STOP LOSS"
            logger.warning(f"🚨 {reason} ({pnl_ticks:.1f} ticks). Panic Exiting!")
            await self.trade_manager.panic_exit()