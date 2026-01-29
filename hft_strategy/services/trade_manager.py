# hft_strategy/services/trade_manager.py
import asyncio
import logging
import time
import uuid
from typing import Optional

# [FIX] Добавлен импорт TradeSignal, иначе упадет
from hft_strategy.domain.events import TradeSignal 
from hft_strategy.domain.trade_context import TradeContext, StrategyState
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.interfaces import IExecutionHandler

try:
    from hft_core import OrderGateway
except ImportError:
    OrderGateway = object

logger = logging.getLogger("TRADE_MGR")

class TradeManager:
    def __init__(self, executor: IExecutionHandler, cfg: StrategyParameters, gateway: Optional[OrderGateway] = None, notifier=None):
        self.exec = executor
        self.gateway = gateway
        self.cfg = cfg
        self.notifier = notifier
        self._stop_requested = False 
        self.state = StrategyState.IDLE
        self.ctx: Optional[TradeContext] = None
        self._tp_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        # [FIX] symbol -> cfg.symbol (symbol не был определен)
        self.logger = logging.getLogger(f"TradeManager-{cfg.symbol}")
    
    @property
    def can_be_deleted(self) -> bool:
        return self._stop_requested and self.state == StrategyState.IDLE
    
    def request_stop(self):
        self._stop_requested = True
        logger.info(f"⚠️ {self.cfg.symbol} switching to DRAIN MODE. No new entries allowed.")
 

    # --- АТОМАРНЫЙ ВХОД ---

    async def open_position(self, side: str, wall_price: float, entry_price: float, qty: float, stop_loss: float, take_profit: float):
        """Выставляет лимитный ордер СРАЗУ с TP и SL"""
        async with self._state_lock:
            if self._stop_requested:
                logger.debug(f"🛑 Entry ignored for {self.cfg.symbol} (Stopping)")
                return
                
            if self.state != StrategyState.IDLE: return

            client_oid = str(uuid.uuid4())
            logger.info(f"📡 [SIGNAL] Submitting Limit {side} {qty} @ {entry_price} | TP: {take_profit} | SL: {stop_loss}")
            
            # [FIX] Исправлена логика нотификации (IndentationError + NameErrors)
            if self.notifier:
                try:
                    signal = TradeSignal(
                        symbol=self.cfg.symbol, # [FIX] self.symbol -> self.cfg.symbol
                        side=side,
                        price=entry_price,      # [FIX] price -> entry_price
                        qty=qty,
                        reason="Strategy Signal"
                    )
                    # status="OPEN" значит, что мы открываем сделку
                    self.notifier.send_trade(signal, status="OPEN") 
                except Exception as e:
                    self.logger.error(f"Failed to send notification: {e}")

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
            # --- ВХОД (Entry) ---
            if self.ctx and (event.order_id == self.ctx.order_id or event.order_id.startswith("sim_")):
                self.ctx.filled_qty += event.exec_qty
                logger.info(f"🔵 [ENTRY] {self.cfg.symbol} | +{event.exec_qty} шт. по {event.exec_price}")
                
                if self.state == StrategyState.ORDER_PLACED:
                    self.state = StrategyState.IN_POSITION
                    
                # Уведомление о частичном или полном входе (опционально, чтобы не спамить)
                # Если нужно - раскомментируйте:
                if self.notifier:
                    sig = TradeSignal(self.cfg.symbol, event.side, event.exec_price, event.exec_qty, reason="Filled")
                    self.notifier.send_trade(sig, status="FILLED")

            # --- ВЫХОД (Exit) ---
            elif self.ctx and self.state == StrategyState.IN_POSITION:
                is_closing = (self.ctx.side == "Buy" and event.side == "Sell") or \
                             (self.ctx.side == "Sell" and event.side == "Buy")
                
                if is_closing:
                    # Расчет PnL
                    price_diff = (event.exec_price - self.ctx.entry_price) if self.ctx.side == "Buy" else (self.ctx.entry_price - event.exec_price)
                    realized_pnl = price_diff * event.exec_qty
                    
                    self.ctx.filled_qty -= event.exec_qty
                    
                    # Логгирование
                    log_emoji = "✅" if realized_pnl > 0 else "❌"
                    logger.info(
                        f"{log_emoji} {self.cfg.symbol} | PnL: {realized_pnl:.4f} USDT | "
                        f"Price: {event.exec_price} | Остаток: {self.ctx.filled_qty:.4f}"
                    )
                    
                    # [FIX] ОТПРАВКА УВЕДОМЛЕНИЯ В TELEGRAM
                    if self.notifier:
                        status = "PROFIT" if realized_pnl > 0 else "LOSS"
                        # Создаем объект сигнала для красивого форматирования
                        sig = TradeSignal(
                            symbol=self.cfg.symbol,
                            side=event.side,       # Sell (если закрыли лонг)
                            price=event.exec_price,
                            qty=event.exec_qty,
                            reason="Exit"
                        )
                        self.notifier.send_trade(sig, status=status, pnl=realized_pnl)
                    
                    # Если позиция закрыта полностью - сброс
                    if self.ctx.filled_qty <= 1e-9:
                        logger.info(f"🏁 Сделка закрыта полностью. Жду новый сигнал.")
                        self.reset()

    # --- ОТМЕНА И ВЫХОД ---
    async def cancel_entry(self, reason: str = "Unknown"):
        """Добавлен аргумент reason"""
        if self.state != StrategyState.ORDER_PLACED or not self.ctx: return

        if self.notifier:
             # [FIX] Использование правильного self.cfg.symbol
             self.notifier.send_trade(
                 TradeSignal(self.cfg.symbol, "None", 0, 0, reason="Timeout/Cancel"), 
                 status="CANCEL"
             )
        
        # Теперь мы видим ПОЧЕМУ мы отменяем
        logger.info(f"🚫 [CANCEL] {self.cfg.symbol} | Reason: {reason} | ID: {self.ctx.order_id}")
        
        try:
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
        except Exception as e:
            err_str = str(e)
            # Если ордера нет - считаем, что мы вышли в кэш.
            # Если он РЕАЛЬНО исполнился, ExecutionStream сам переведет нас в IN_POSITION.
            if "110001" in err_str or "Order not exists" in err_str:
                logger.warning(f"⚠️ Order {self.ctx.order_id} not found. Assuming reset.")
                self.reset()  # <--- Просто сбрасываем, не выдумываем позицию
            else:
                logger.error(f"❌ Cancel Failed: {e}")

    async def panic_exit(self, reason: str = "Panic"):
        """Добавлен аргумент reason"""
        if not self.ctx or self.ctx.filled_qty <= 1e-9:
            self.reset()
            return

        exit_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        p_id = f"panic_{int(time.time())}"
        
        # Яркий лог паники
        logger.warning(f"🚨 [PANIC EXIT] {self.cfg.symbol} | Reason: {reason} | Dumping {self.ctx.filled_qty} by MARKET!")
        
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