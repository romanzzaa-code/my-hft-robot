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
                 notifier: Optional[object] = None):
        self.cfg = cfg
        self.lob = LocalOrderBook()
        self._lock = asyncio.Lock()
        self.analytics = MarketAnalytics(executor, cfg)
        self.detector = WallDetector(cfg)
        self.trade_manager = TradeManager(executor, cfg, gateway, notifier)
        asyncio.create_task(self.analytics.start())

    async def on_execution(self, event):
        """Обработка исполнений (ExecutionReport) всегда в приоритете."""
        await self.trade_manager.handle_execution(event)

    def on_tick(self, tick):
        """
        FAST PATH: Обработка тиков без блокировок.
        Если видим сделку, пробивающую нашу стену -> мгновенная отмена.
        """
        ctx = self.trade_manager.ctx
        state = self.trade_manager.state
        if state == StrategyState.ORDER_PLACED and ctx:
            # Проверка пробоя стены тиком
            is_break = False
            if ctx.side == "Buy":
                # [FIX] Теперь строго меньше, чтобы не отменять на касании
                if tick.price < ctx.wall_price:
                    is_break = True
            else: # Sell
                # [FIX] Теперь строго больше
                if tick.price > ctx.wall_price:
                    is_break = True

            if is_break:
                # Используем fire-and-forget, чтобы не блочить поток WebSocket
                # Важно: cancel_entry внутри защищен от повторных вызовов
                asyncio.create_task(
                    self.trade_manager.cancel_entry(reason=f"⚡ Tick Break {tick.price}")
                )

    async def on_depth(self, snapshot):
        """
        SLOW PATH: Анализ стакана.
        Разделяем обновление данных и логику принятия решений.
        """
        # 1. ALWAYS UPDATE DATA (Critical)
        # Стакан должен быть свежим, даже если мы заняты расчетами.
        if hasattr(snapshot, 'bids') and not isinstance(snapshot.bids, dict):
            self.lob.apply_snapshot(snapshot)
        else:
            self.lob.apply_update(snapshot)

        # 2. LOAD SHEDDING (Logic Skip)
        # Если стратегия занята предыдущим тиком/расчетом -> пропускаем логику,
        # но данные мы уже обновили выше!
        if self._lock.locked(): 
            return

        # 3. STRATEGY LOGIC
        async with self._lock:
            if not self.lob.bids or not self.lob.asks: return

            # Обновляем метрики фонового объема (для детектора стен)
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
        # Ищем новую стену
        signal = self.detector.detect_signal(
            self.lob, 
            self.analytics.avg_background_vol
        )
        if signal:
            step_size = self.cfg.lot_size if self.cfg.lot_size > 0 else 1.0
            # Расчет объема в монетах на основе USDT
            raw_qty = self.cfg.order_amount_usdt / signal["entry_price"]
            qty_final = round(int(raw_qty / step_size) * step_size, 8)
            if qty_final < self.cfg.min_qty: return

            # Динамический расчет TP/SL
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

    async def _process_order_placed(self):
        """Проверяем, жива ли стена, пока наш ордер висит."""
        ctx = self.trade_manager.ctx
        if not ctx: return

        best_bid_p = self.lob.get_best("Buy")
        best_ask_p = self.lob.get_best("Sell")

        # Проверяем объем стены (сумма объемов на уровнях рядом с wall_price)
        current_wall_v = 0.0
        for t in range(-2, 3):
            check_p = ctx.wall_price + (t * self.cfg.tick_size)
            current_wall_v = max(current_wall_v, self.lob.get_volume(ctx.side, check_p))

        # Порог разрушения стены (40% от средней стены)
        threshold = self.analytics.avg_background_vol * self.cfg.wall_ratio_threshold * 0.4 
        wall_collapsed = current_wall_v < threshold

        # Цена ушла без нас?
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
        """Управление открытой позицией (если TP/SL на бирже не сработали)."""
        ctx = self.trade_manager.ctx
        if not ctx or ctx.filled_qty <= 1e-9: return

        best_bid = self.lob.get_best("Buy")
        best_ask = self.lob.get_best("Sell")

        # Цена выхода сейчас (Market)
        exit_price = best_bid if ctx.side == "Buy" else best_ask

        # Пробой уровня поддержки (с учетом толерантности)
        # Если лонг: выход если Best Bid < wall_price - tolerance
        limit_p = ctx.wall_price - (self.cfg.exit_wall_tolerance_ticks * self.cfg.tick_size)
        if ctx.side == "Buy":
            wall_broken = exit_price < limit_p
        else: # Sell
            limit_p = ctx.wall_price + (self.cfg.exit_wall_tolerance_ticks * self.cfg.tick_size)
            wall_broken = exit_price > limit_p

        delta = (exit_price - ctx.entry_price) if ctx.side == "Buy" else (ctx.entry_price - exit_price)
        pnl_ticks = delta / self.cfg.tick_size
        stop_hit = pnl_ticks <= -self.cfg.stop_loss_ticks

        if wall_broken or stop_hit:
            reason = f"Wall Broken (Price: {exit_price})" if wall_broken else f"Hard Stop Hit ({pnl_ticks:.1f} ticks)"
            logger.warning(f"🚨 {reason} ({pnl_ticks:.1f} ticks). Panic Exiting!")
            await self.trade_manager.panic_exit(reason=reason)

    def set_graceful_stop(self):
        self.trade_manager.request_stop()

    @property
    def can_be_deleted(self) -> bool:
        return self.trade_manager.can_be_deleted