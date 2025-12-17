# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import math
from typing import Optional

# Imports from Layers
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.trade_context import StrategyState, TradeContext
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.infrastructure.local_order_book import LocalOrderBook

logger = logging.getLogger("ADAPTIVE_STRAT")

class AdaptiveWallStrategy:
    """
    Стратегия 'Отскок от плотностей' с адаптивным трешхолдом.
    Принцип SOLID: Оркестратор. Делегирует хранение данных в TradeContext и LOB.
    """
    def __init__(self, executor: BybitExecutionHandler, cfg: StrategyParameters):
        # Dependencies
        self.exec = executor
        self.cfg = cfg
        
        # State & Data (Domain Layer)
        self.state = StrategyState.IDLE
        self.ctx: Optional[TradeContext] = None
        
        # Infrastructure
        self.lob = LocalOrderBook()
        self._lock = asyncio.Lock()
        
        # Internal Logic Vars
        self.tick_size = cfg.tick_size
        self.avg_vol = 0.0 
        self.initialized = False
        self._last_log_ts = 0

    def _update_metrics(self):
        """Обновляет EMA средней ликвидности на основе фонового объема"""
        bg_vol = self.lob.get_background_volume()
        
        if bg_vol <= 0: return

        if not self.initialized:
            self.avg_vol = bg_vol
            logger.info(f"📊 INIT BASELINE: {self.avg_vol:.1f} (Background Liquidity)")
            self.initialized = True
        else:
            alpha = self.cfg.vol_ema_alpha
            self.avg_vol = alpha * bg_vol + (1 - alpha) * self.avg_vol

    async def on_depth(self, snapshot):
        """Event Handler - точка входа событий"""
        if self._lock.locked(): return
        
        async with self._lock:
            try:
                # 1. Делегируем обновление стакана инфраструктуре
                self.lob.apply_update(snapshot)
                
                # Если данных мало - выходим
                if not self.lob.bids or not self.lob.asks: return

                # 2. Обновляем аналитику
                self._update_metrics()

                # 3. Достаем данные для принятия решений
                best_bid_p = self.lob.get_best("Buy")
                best_ask_p = self.lob.get_best("Sell")
                
                best_bid_v = self.lob.get_volume("Buy", best_bid_p)
                best_ask_v = self.lob.get_volume("Sell", best_ask_p)

                # 4. Роутинг по машине состояний
                if self.state == StrategyState.IDLE:
                    await self._handle_idle(best_bid_p, best_bid_v, best_ask_p, best_ask_v)
                
                elif self.state == StrategyState.ORDER_PLACED:
                    await self._handle_order_placed()
                
                elif self.state == StrategyState.IN_POSITION:
                    await self._handle_in_position(best_bid_p, best_ask_p)
                    
            except Exception as e:
                logger.error(f"💥 Loop Error: {e}", exc_info=True)

    # --- STATE HANDLERS (Business Logic) ---

    async def _handle_idle(self, bid_p, bid_v, ask_p, ask_v):
        threshold = self.avg_vol * self.cfg.wall_ratio_threshold
        
        # Rate-limited logging
        now = asyncio.get_running_loop().time()
        if now - self._last_log_ts > 5.0:
            logger.info(
                f"👀 SCAN: Bg={self.avg_vol:.0f} | Thr={threshold:.0f} | "
                f"Bid={bid_v:.0f} vs Ask={ask_v:.0f}"
            )
            self._last_log_ts = now

        # Logic: Entry Signal
        # Long
        if bid_v > threshold and (bid_v * bid_p > self.cfg.min_wall_value_usdt):
            await self._place_entry_order("Buy", bid_p, bid_p + self.tick_size)
            return

        # Short
        if ask_v > threshold and (ask_v * ask_p > self.cfg.min_wall_value_usdt):
            await self._place_entry_order("Sell", ask_p, ask_p - self.tick_size)

    async def _handle_order_placed(self):
        # 1. Валидация условия входа (Стена все еще там?)
        if not self._check_wall_integrity():
            vol = self.lob.get_volume(self.ctx.side, self.ctx.wall_price)
            logger.warning(f"💨 Wall vanished! Vol={vol:.1f}. Cancelling...")
            await self.exec.cancel_order(self.ctx.order_id)
            self._reset_state()
            return

        # 2. Проверка исполнения (Интеграция с Execution)
        real_pos = await self.exec.get_position()
        
        # Если позиция набрана на 90%+
        if (self.ctx.side == "Buy" and real_pos >= self.ctx.quantity * 0.9) or \
           (self.ctx.side == "Sell" and real_pos <= -self.ctx.quantity * 0.9):
             
             logger.info(f"✅ FILLED ({self.ctx.side}). Pos: {real_pos}")
             self.state = StrategyState.IN_POSITION
             await self._place_take_profit()

    async def _handle_in_position(self, best_bid, best_ask):
        # 1. Проверка фундамента сделки (Стена)
        if not self._check_wall_integrity():
            logger.warning("⚠️ Wall COLLAPSED! PANIC EXIT.")
            await self._panic_exit()
            return

        # 2. Риск-менеджмент (Stop Loss)
        curr_price = best_bid if self.ctx.side == "Buy" else best_ask
        pnl = (curr_price - self.ctx.entry_price) if self.ctx.side == "Buy" else (self.ctx.entry_price - curr_price)
        pnl_ticks = pnl / self.tick_size
        
        if pnl_ticks <= -self.cfg.stop_loss_ticks:
            logger.warning(f"🛑 STOP LOSS ({pnl_ticks:.1f} ticks).")
            await self._panic_exit()
            return

        # 3. Проверка выхода (Take Profit)
        real_pos = await self.exec.get_position()
        if abs(real_pos) < self.ctx.quantity * 0.1:
            logger.info("💰 TP EXECUTED.")
            self._reset_state()

    # --- PRIVATE HELPERS ---

    def _check_wall_integrity(self) -> bool:
        """Стена считается живой, если осталось >50% от порога входа"""
        current_vol = self.lob.get_volume(self.ctx.side, self.ctx.wall_price)
        threshold = self.avg_vol * self.cfg.wall_ratio_threshold * 0.5
        return current_vol > threshold

    async def _place_entry_order(self, side: str, wall_price: float, entry_price: float):
        raw_qty = self.cfg.order_amount_usdt / entry_price
        qty = self._round_qty(raw_qty)
        price = self._round_price(entry_price)

        if qty * price < 5.0: return # Min order filter

        logger.info(f"🧱 WALL FOUND: {side} {self.lob.get_volume(side, wall_price):.0f} @ {wall_price}. Order @ {price}")
        
        oid = await self.exec.place_limit_maker(side, price, qty)
        if oid:
            self.state = StrategyState.ORDER_PLACED
            self.ctx = TradeContext(side, wall_price, price, qty, oid)

    async def _place_take_profit(self):
        tp_ticks = self.cfg.take_profit_ticks
        tp_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        
        sign = 1 if self.ctx.side == "Buy" else -1
        tp_price = self.ctx.entry_price + (sign * tp_ticks * self.tick_size)
        tp_price = self._round_price(tp_price)
        
        logger.info(f"🎯 TP @ {tp_price}")
        oid = await self.exec.place_limit_maker(tp_side, tp_price, self.ctx.quantity)
        self.ctx.tp_order_id = oid

    async def _panic_exit(self):
        if self.ctx.tp_order_id:
            await self.exec.cancel_order(self.ctx.tp_order_id)
        
        exit_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        await self.exec.place_market_order(exit_side, self.ctx.quantity)
        self._reset_state()

    def _reset_state(self):
        self.state = StrategyState.IDLE
        self.ctx = None

    def _round_price(self, price: float) -> float:
        if self.tick_size == 0: return price
        return round(price / self.tick_size) * self.tick_size

    def _round_qty(self, qty: float) -> float:
        if self.cfg.lot_size == 0: return qty
        step = self.cfg.lot_size
        return math.floor(qty / step) * step