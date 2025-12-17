# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import math  # Обязательно для округления
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict

from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.domain.strategy_config import StrategyParameters

# Пытаемся импортировать типы для аннотаций
try:
    from hft_core import OrderBookSnapshot
except ImportError:
    pass

logger = logging.getLogger("ADAPTIVE_STRAT")

class State(Enum):
    IDLE = 0
    ENTRY_SENT = 1
    IN_POSITION = 2
    EXIT_SENT = 3

@dataclass
class ActiveTrade:
    side: str
    entry_price: float
    size: float
    wall_price: float
    entry_oid: Optional[str] = None
    tp_oid: Optional[str] = None

class AdaptiveWallStrategy:
    def __init__(self, executor: BybitExecutionHandler, cfg: StrategyParameters):
        self.exec = executor
        self.cfg = cfg
        
        self.state = State.IDLE
        self.trade: Optional[ActiveTrade] = None
        
        # Metrics
        self.avg_bid_vol = 0.0
        self.avg_ask_vol = 0.0
        self.initialized = False

    def _round_to_step(self, value: float, step: float) -> float:
        """Корректное округление до шага (lot_size или tick_size)"""
        if step == 0: return value
        inverse = 1.0 / step
        return math.floor(value * inverse + 0.0001) / inverse

    async def on_depth(self, snapshot):
        if not snapshot.bids or not snapshot.asks:
            return

        best_bid = snapshot.bids[0]
        best_ask = snapshot.asks[0]

        # 1. EMA Learning (Обучение средней)
        if not self.initialized:
            self.avg_bid_vol = best_bid.quantity
            self.avg_ask_vol = best_ask.quantity
            self.initialized = True
        else:
            alpha = self.cfg.vol_ema_alpha
            self.avg_bid_vol = alpha * best_bid.quantity + (1 - alpha) * self.avg_bid_vol
            self.avg_ask_vol = alpha * best_ask.quantity + (1 - alpha) * self.avg_ask_vol

        # 2. State Machine
        if self.state == State.IDLE:
            await self._check_entry_signal(best_bid, best_ask)
        elif self.state == State.IN_POSITION:
            await self._check_exit_conditions(snapshot)

    async def _check_entry_signal(self, best_bid, best_ask):
        # LONG (Bid Wall)
        # Условие: Объем > Среднего * K
        is_bid_wall = (best_bid.quantity > self.avg_bid_vol * self.cfg.wall_ratio_threshold)
        # Доп. условие: Стена должна стоить денег (фильтр дешевых стен)
        wall_val_usdt = best_bid.quantity * best_bid.price
        
        if is_bid_wall and wall_val_usdt > self.cfg.min_wall_value_usdt:
            logger.info(f"🧱 BID WALL: {best_bid.quantity:.0f} (${wall_val_usdt:.0f}) @ {best_bid.price}")
            entry_price = best_bid.price + (self.cfg.tick_size * self.cfg.entry_delta_ticks)
            await self._enter_position("Buy", entry_price, wall_price=best_bid.price)
            return

        # SHORT (Ask Wall)
        is_ask_wall = (best_ask.quantity > self.avg_ask_vol * self.cfg.wall_ratio_threshold)
        wall_val_usdt = best_ask.quantity * best_ask.price

        if is_ask_wall and wall_val_usdt > self.cfg.min_wall_value_usdt:
            logger.info(f"🧱 ASK WALL: {best_ask.quantity:.0f} (${wall_val_usdt:.0f}) @ {best_ask.price}")
            entry_price = best_ask.price - (self.cfg.tick_size * self.cfg.entry_delta_ticks)
            await self._enter_position("Sell", entry_price, wall_price=best_ask.price)

    async def _enter_position(self, side: str, price: float, wall_price: float):
        # 1. Считаем QTY от USDT
        if self.cfg.order_amount_usdt <= 0:
            logger.error("❌ Order Amount USDT is 0! Check config.py")
            return

        # Qty = $50 / 0.0411 = 1216.54
        raw_qty = self.cfg.order_amount_usdt / price
        
        # Округляем до лота (например, до 1) -> 1216
        qty = self._round_to_step(raw_qty, self.cfg.lot_size)
        
        # Округляем цену до тика
        price = self._round_to_step(price, self.cfg.tick_size)

        # 2. Проверка на минимальный размер ордера (Bybit Limit ~5 USDT)
        order_value = qty * price
        if order_value < 5.5: # Берем с запасом
            logger.warning(f"⚠️ Order Value ${order_value:.2f} too small (Min $5). Skipping.")
            return

        self.state = State.ENTRY_SENT
        logger.info(f"🚀 ENTERING {side}: {qty} @ {price:.5f} (${order_value:.2f})")
        
        oid = await self.exec.place_limit_maker(side, price, qty)
        
        if oid:
            self.state = State.IN_POSITION
            self.trade = ActiveTrade(side, price, qty, wall_price, entry_oid=oid)
            await self._place_take_profit(side, price, qty)
        else:
            self.state = State.IDLE

    async def _place_take_profit(self, entry_side: str, entry_price: float, qty: float):
        tp_side = "Sell" if entry_side == "Buy" else "Buy"
        ticks = self.cfg.take_profit_ticks
        
        if entry_side == "Buy":
            tp_price = entry_price + (ticks * self.cfg.tick_size)
        else:
            tp_price = entry_price - (ticks * self.cfg.tick_size)
            
        tp_price = self._round_to_step(tp_price, self.cfg.tick_size)
        
        tp_oid = await self.exec.place_limit_maker(tp_side, tp_price, qty)
        if tp_oid:
            self.trade.tp_oid = tp_oid
            logger.info(f"🎯 TP Placed @ {tp_price}")

    async def _check_exit_conditions(self, snapshot):
        """Проверка условий выхода: Исчезновение стены или Стоп-лосс"""
        if not self.trade: return

        # 1. ПРОВЕРКА СТЕНЫ (Wall Collapse)
        search_side = snapshot.bids if self.trade.side == "Buy" else snapshot.asks
        
        current_wall_vol = 0.0
        # Ищем в топ-5 уровнях
        for i in range(min(5, len(search_side))):
            level = search_side[i]
            # Сравниваем float с эпсилоном
            if abs(level.price - self.trade.wall_price) < 1e-9:
                current_wall_vol = level.quantity
                break
        
        # Порог паники: если объем упал ниже 50% от "триггера"
        baseline = self.avg_bid_vol if self.trade.side == "Buy" else self.avg_ask_vol
        collapse_threshold = baseline * self.cfg.wall_ratio_threshold * 0.5
        
        if current_wall_vol < collapse_threshold:
            logger.warning(f"⚠️ WALL COLLAPSED! Cur: {current_wall_vol:.1f} < {collapse_threshold:.1f}. PANIC EXIT!")
            await self._panic_exit(reason="WallCollapse")
            return

        # 2. ВИРТУАЛЬНЫЙ СТОП-ЛОСС
        market_price = snapshot.asks[0].price if self.trade.side == "Buy" else snapshot.bids[0].price
        
        pnl_ticks = (market_price - self.trade.entry_price) / self.cfg.tick_size
        if self.trade.side == "Sell": 
            pnl_ticks = -pnl_ticks
        
        if pnl_ticks <= -self.cfg.stop_loss_ticks:
            logger.warning(f"🛑 STOP LOSS HIT: {pnl_ticks:.1f} ticks. PANIC EXIT!")
            await self._panic_exit(reason="StopLoss")

    async def _panic_exit(self, reason: str):
        """Экстренный выход по рынку"""
        if self.state == State.EXIT_SENT:
            return # Уже выходим
            
        self.state = State.EXIT_SENT
        
        # 1. Отменяем TP, если он есть
        if self.trade.tp_oid:
            await self.exec.cancel_order(self.trade.tp_oid)
            
        # 2. Бьем по рынку
        exit_side = "Sell" if self.trade.side == "Buy" else "Buy"
        await self.exec.place_market_order(exit_side, self.trade.size)
        
        logger.info(f"🏳️ POSITION CLOSED ({reason})")
        
        # Сброс
        self.trade = None
        self.state = State.IDLE