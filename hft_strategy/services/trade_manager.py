# hft_strategy/services/trade_manager.py
import asyncio
import logging
import time
import uuid
from typing import Optional
from hft_strategy.domain.trade_context import TradeContext, StrategyState
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.interfaces import IExecutionHandler

try:
    from hft_core import OrderGateway
except ImportError:
    OrderGateway = object

logger = logging.getLogger("TRADE_MGR")

class TradeManager:
    def __init__(self, executor: IExecutionHandler, cfg: StrategyParameters, gateway: Optional[OrderGateway] = None):
        self.exec = executor
        self.gateway = gateway
        self.cfg = cfg
        
        self.state = StrategyState.IDLE
        self.ctx: Optional[TradeContext] = None
        self._tp_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

    # --- АТОМАРНЫЙ ВХОД ---
    async def open_position(self, side: str, wall_price: float, entry_price: float, qty: float, stop_loss: float, take_profit: float):
        """Выставляет лимитный ордер СРАЗУ с TP и SL"""
        async with self._state_lock:
            if self.state != StrategyState.IDLE: return

            client_oid = str(uuid.uuid4())
            logger.info(f"🚀 [ENTRY] {side} {qty} @ {entry_price} | TP: {take_profit} | SL: {stop_loss}")

            # 1. C++ Gateway (Быстро)
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
                        reduce_only=False,
                        stop_loss=float(stop_loss),   # <--- Атомарный SL
                        take_profit=float(take_profit) # <--- Атомарный TP
                    )
                except Exception as e:
                    logger.error(f"❌ Gateway Entry Error: {e}")

            # 2. REST Fallback (Медленно, но надежно)
            oid = await self.exec.place_limit_maker(
                self.cfg.symbol, side, entry_price, qty, 
                reduce_only=False, order_link_id=client_oid,
                stop_loss=float(stop_loss),
                take_profit=float(take_profit)
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

    # --- ОБРАБОТКА ИСПОЛНЕНИЙ ---
    async def handle_execution(self, event):
        async with self._state_lock:
            # Сценарий 1: Исполнение входа
            if self.ctx and (event.order_id == self.ctx.order_id or event.order_id.startswith("sim_")):
                self.ctx.filled_qty += event.exec_qty
                logger.info(f"⚡ [FILL] {self.cfg.symbol} +{event.exec_qty} (Total: {self.ctx.filled_qty})")
                
                if self.state == StrategyState.ORDER_PLACED:
                    self.state = StrategyState.IN_POSITION
                
                # [ВАЖНО] Мы НЕ вызываем sync_take_profit, так как TP уже заложен в ордере

            # Сценарий 2: Закрытие (TP или SL сработал на бирже)
            # В режиме Partial TP/SL создаются отдельные ордера, поэтому ID может отличаться.
            # Смотрим на уменьшение позиции.
            elif self.ctx and self.state == StrategyState.IN_POSITION:
                is_closing = (self.ctx.side == "Buy" and event.side == "Sell") or \
                             (self.ctx.side == "Sell" and event.side == "Buy")
                
                if is_closing:
                    self.ctx.filled_qty -= event.exec_qty
                    logger.info(f"📉 [EXIT] Closed {event.exec_qty}. Remaining: {self.ctx.filled_qty}")
                    
                    if self.ctx.filled_qty <= 1e-9:
                        logger.info(f"💰 Position fully closed. Resetting.")
                        self.reset()

            # Сценарий 3: Сирота (Orphan Fill)
            elif self.state == StrategyState.IDLE and event.exec_qty > 0:
                 # Логика подхвата (опционально, если нужно)
                 pass

    # --- ОТМЕНА И ВЫХОД ---
    async def cancel_entry(self):
        """Спекулятивная отмена без задержек"""
        if self.state != StrategyState.ORDER_PLACED or not self.ctx: return
        
        logger.info(f"🚫 [CANCEL] Attempting to cancel {self.cfg.symbol}...")
        try:
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
            
            if self.ctx.filled_qty <= 1e-9:
                self.reset()
            else:
                # Если успело налить - переходим в позицию (TP уже стоит!)
                self.state = StrategyState.IN_POSITION

        except Exception as e:
            err_str = str(e)
            # Если ордер исчез — считаем, что он исполнился (Гонка)
            if "110001" in err_str or "Order not exists" in err_str:
                logger.warning(f"🏎️ RACE CONDITION! Speculative fill for {self.cfg.symbol}")
                self.state = StrategyState.IN_POSITION
                if self.ctx.filled_qty <= 1e-9:
                    self.ctx.filled_qty = self.ctx.quantity
            else:
                logger.error(f"❌ Cancel Failed: {e}")

    async def panic_exit(self):
        """Экстренный выход по рынку (если стену проели)"""
        if not self.ctx or self.ctx.filled_qty <= 1e-9:
            self.reset()
            return

        exit_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        p_id = f"panic_{int(time.time())}"
        
        logger.warning(f"🚨 [PANIC] Market {exit_side} {self.ctx.filled_qty}!")
        
        # 1. WebSocket IOC (Быстро)
        if self.gateway:
            try:
                self.gateway.send_order(
                    self.cfg.symbol, exit_side, float(self.ctx.filled_qty), 0.0,
                    order_link_id=p_id, order_type="Market", time_in_force="IOC", reduce_only=True
                )
            except: pass

        # 2. REST Backup
        await self.exec.place_market_order(self.cfg.symbol, exit_side, self.ctx.filled_qty, reduce_only=True)
        self.reset()

    def reset(self):
        self.state = StrategyState.IDLE
        self.ctx = None