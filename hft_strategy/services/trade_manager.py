# hft_strategy/services/trade_manager.py
import asyncio
import logging
import time
import uuid
from typing import Optional
from hft_strategy.domain.trade_context import TradeContext, StrategyState
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.interfaces import IExecutionHandler

# Защита импорта C++
try:
    from hft_core import OrderGateway
except ImportError:
    OrderGateway = object

logger = logging.getLogger("TRADE_MGR")

class TradeManager:
    """
    Отвечает за исполнение ордеров, управление позицией и экстренные выходы.
    Инкапсулирует состояние StrategyState и TradeContext.
    """
    def __init__(self, executor: IExecutionHandler, cfg: StrategyParameters, gateway: Optional[OrderGateway] = None):
        self.exec = executor
        self.gateway = gateway
        self.cfg = cfg
        
        self.state = StrategyState.IDLE
        self.ctx: Optional[TradeContext] = None
        
        # Блокировки для предотвращения Race Conditions
        self._tp_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

    def is_idle(self) -> bool:
        return self.state == StrategyState.IDLE

    # --- ВХОД В ПОЗИЦИЮ ---
    async def open_position(self, side: str, wall_price: float, entry_price: float, qty: float):
        """Выставляет лимитный ордер на вход"""
        async with self._state_lock:
            if self.state != StrategyState.IDLE: return

            client_oid = str(uuid.uuid4())
            logger.info(f"🚀 [ENTRY] Sending {side} @ {entry_price} for {self.cfg.symbol}")

            # Попытка через быстрый шлюз C++ (с новыми параметрами из Шага 1)
            if self.gateway:
                try:
                    self.gateway.send_order(
                        symbol=self.cfg.symbol,
                        side=side,
                        qty=float(qty),
                        price=float(entry_price),
                        order_link_id=client_oid,
                        order_type="Limit",
                        time_in_force="PostOnly",
                        reduce_only=False
                    )
                except Exception as e:
                    logger.error(f"❌ Gateway Entry Error: {e}")

            # Резервный/основной лимит через REST (для получения ID, если GW не вернул)
            oid = await self.exec.place_limit_maker(
                self.cfg.symbol, side, entry_price, qty, 
                reduce_only=False, order_link_id=client_oid
            )

            if oid or self.gateway:
                self.state = StrategyState.ORDER_PLACED
                self.ctx = TradeContext(
                    side=side,
                    wall_price=wall_price,
                    entry_price=entry_price,
                    quantity=qty,
                    order_id=oid or client_oid,
                    filled_qty=0.0,
                    placed_ts=time.time()
                )

    # --- ОБРАБОТКА ИСПОЛНЕНИЙ (PUSH) ---
    async def handle_execution(self, event):
        """Реактивная обработка Fill событий из WebSocket"""
        async with self._state_lock:
            if not self.ctx: return

            # Исполнение входа
            if event.order_id == self.ctx.order_id or event.order_id.startswith("sim_"):
                self.ctx.filled_qty += event.exec_qty
                logger.info(f"⚡ [FILL] {self.cfg.symbol} +{event.exec_qty} (Total: {self.ctx.filled_qty})")
                
                if self.state == StrategyState.ORDER_PLACED:
                    self.state = StrategyState.IN_POSITION
                
                await self.sync_take_profit()

            # Исполнение выхода (TP)
            elif self.ctx.tp_order_id and event.order_id == self.ctx.tp_order_id:
                self.ctx.filled_qty -= event.exec_qty
                if self.ctx.filled_qty <= 1e-9:
                    logger.info(f"💰 [TP DONE] Fully closed {self.cfg.symbol}")
                    self.reset()
                else:
                    logger.info(f"📉 [TP PARTIAL] Remaining: {self.ctx.filled_qty}")

    # --- УПРАВЛЕНИЕ ВЫХОДОМ ---
    async def sync_take_profit(self):
        """Синхронизирует Тейк-Профит с реально набранным объемом (Шаг 2)"""
        if not self.ctx or self.ctx.filled_qty <= 1e-9: return

        async with self._tp_lock:
            tp_price = self._calculate_tp_price()
            tp_side = "Sell" if self.ctx.side == "Buy" else "Buy"
            tp_link_id = f"tp_{self.ctx.order_id}"

            if not self.ctx.tp_order_id:
                oid = await self.exec.place_limit_maker(
                    self.cfg.symbol, tp_side, tp_price, self.ctx.filled_qty,
                    reduce_only=True, order_link_id=tp_link_id
                )
                if oid: self.ctx.tp_order_id = oid
            else:
                await self.exec.amend_order(self.cfg.symbol, self.ctx.tp_order_id, self.ctx.filled_qty)

    async def cancel_entry(self):
        """Безопасная отмена входа с проверкой проскальзывания исполнений"""
        if self.state != StrategyState.ORDER_PLACED or not self.ctx: return
        
        logger.info(f"🚫 [CANCEL] Entry for {self.cfg.symbol}")
        await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
        
        # Если за время запроса успело налиться — переходим в позицию, иначе сброс
        if self.ctx.filled_qty > 1e-9:
            self.state = StrategyState.IN_POSITION
            await self.sync_take_profit()
        else:
            self.reset()

    async def panic_exit(self):
        """Экстренный рыночный выход (Шаг 3)"""
        if not self.ctx or self.ctx.filled_qty <= 1e-9:
            self.reset()
            return

        async with self._tp_lock:
            if self.ctx.tp_order_id:
                await self.exec.cancel_order(self.cfg.symbol, self.ctx.tp_order_id)
                self.ctx.tp_order_id = None

        exit_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        p_id = f"panic_{int(time.time())}"
        
        logger.warning(f"🚨 [PANIC] Market {exit_side} for {self.cfg.symbol}")
        
        if self.gateway:
            try:
                self.gateway.send_order(
                    self.cfg.symbol, exit_side, float(self.ctx.filled_qty), 0.0,
                    order_link_id=p_id, order_type="Market", time_in_force="IOC", reduce_only=True
                )
            except: pass

        await self.exec.place_market_order(self.cfg.symbol, exit_side, self.ctx.filled_qty, reduce_only=True)
        self.reset()

    def reset(self):
        self.state = StrategyState.IDLE
        self.ctx = None

    def _calculate_tp_price(self) -> float:
        # Здесь будет ваша логика расчета цены (фиксированная или динамическая из Analytics)
        # Для начала используем фиксированные тики
        sign = 1 if self.ctx.side == "Buy" else -1
        return self.ctx.entry_price + (sign * self.cfg.fixed_tp_ticks * self.cfg.tick_size)