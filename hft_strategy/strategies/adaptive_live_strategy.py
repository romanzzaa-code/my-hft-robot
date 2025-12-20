# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import math
import time
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, List, Union

from hft_strategy.domain.interfaces import IExecutionHandler 
from hft_strategy.domain.strategy_config import StrategyParameters

logger = logging.getLogger("ADAPTIVE_STRAT")

# --- LOB (Infrastructure) ---
class LocalOrderBook:
    """
    Локальный стакан. Хранит bids/asks и считает метрики.
    """
    def __init__(self):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_ts = 0

    def _to_key(self, price: float) -> float:
        return round(price, 8)

    def apply_update(self, event):
        if getattr(event, 'is_snapshot', False):
            self.bids.clear()
            self.asks.clear()

        for level in event.bids:
            key = self._to_key(level.price)
            if level.quantity == 0:
                if key in self.bids: del self.bids[key]
            else:
                self.bids[key] = level.quantity

        for level in event.asks:
            key = self._to_key(level.price)
            if level.quantity == 0:
                if key in self.asks: del self.asks[key]
            else:
                self.asks[key] = level.quantity
        
        self.last_ts = event.timestamp

    def get_volume(self, side: str, price: float) -> float:
        book = self.bids if side == "Buy" else self.asks
        key = self._to_key(price)
        return book.get(key, 0.0)

    def get_best(self, side: str) -> float:
        book = self.bids if side == "Buy" else self.asks
        if not book: return 0.0
        return max(book.keys()) if side == "Buy" else min(book.keys())

    def get_background_volume(self) -> float:
        if not self.bids or not self.asks: return 0.0
        sorted_bids = sorted(self.bids.keys(), reverse=True)
        sorted_asks = sorted(self.asks.keys())
        # Берем слои со 2 по 11 (исключая спред)
        bg_bids = sorted_bids[1:11] 
        bg_asks = sorted_asks[1:11]
        
        volumes = []
        for p in bg_bids: volumes.append(self.bids[p])
        for p in bg_asks: volumes.append(self.asks[p])
        
        if not volumes: return 0.0
        return sum(volumes) / len(volumes)

# --- States & Context ---
class StrategyState(Enum):
    IDLE = auto()          # Поиск входа
    ORDER_PLACED = auto()  # Лимитка в стакане, ждем исполнения
    IN_POSITION = auto()   # Позиция набрана, ведем сделку

@dataclass
class TradeContext:
    side: str              # "Buy" или "Sell"
    wall_price: float      # Цена стены
    entry_price: float     # Цена входа (наша лимитка)
    quantity: float        # Размер
    order_id: str          # ID ордера на вход
    tp_order_id: Optional[str] = None # ID Тейка
    placed_ts: float = 0.0 # Время выставления (для таймаута)

# --- Strategy ---
class AdaptiveWallStrategy:
    def __init__(self, executor: IExecutionHandler, cfg: StrategyParameters):
        self.exec = executor
        self.cfg = cfg
        self.state = StrategyState.IDLE
        self.ctx: Optional[TradeContext] = None
        self.lob = LocalOrderBook()
        self._lock = asyncio.Lock()
        
        self.tick_size = cfg.tick_size
        self.avg_vol = 0.0 
        self.initialized = False
        
        # Debounce logic
        self._wall_confirms = 0
        self._required_confirms = 3
        
        self.price_decimals = self._get_decimals(cfg.tick_size)
        self.qty_decimals = self._get_decimals(cfg.lot_size)
        
        self.current_tp_pct = self.cfg.min_tp_percent 
        if self.cfg.use_dynamic_tp:
            asyncio.create_task(self._volatility_loop())

    # --- 1. VOLATILITY WATCHDOG ---
    async def _volatility_loop(self):
        logger.debug(f"🌊 Volatility Watchdog Started for {self.cfg.symbol}")
        while True:
            try:
                klines = await self.exec.fetch_ohlc(self.cfg.symbol, interval="5", limit=self.cfg.natr_period + 1)
                if len(klines) < 2:
                    await asyncio.sleep(60)
                    continue
                    
                trs = []
                for i in range(len(klines) - 1): 
                    curr = klines[i]    
                    prev = klines[i+1]  
                    tr = max(curr['h'] - curr['l'], abs(curr['h'] - prev['c']), abs(curr['l'] - prev['c']))
                    trs.append(tr)
                
                if not trs: continue
                
                atr = sum(trs) / len(trs)
                current_close = klines[0]['c']
                
                natr = (atr / current_close) * 100
                target_tp = max(natr * self.cfg.tp_natr_multiplier, self.cfg.min_tp_percent)
                self.current_tp_pct = target_tp
                
            except Exception as e:
                logger.error(f"VolLoop Error: {e}")
            
            await asyncio.sleep(60)

    # --- 2. EXECUTION HANDLER (EVENT DRIVEN) ---
    # --- 2. EXECUTION HANDLER (EVENT DRIVEN) ---
    async def on_execution(self, event):
        """
        [NEW] Реактивный вход и выход.
        """
        async with self._lock:
            if not self.ctx:
                return

            # СЦЕНАРИЙ 1: Исполнение ВХОДА (Entry)
            if event.order_id == self.ctx.order_id:
                if self.state == StrategyState.ORDER_PLACED:
                    logger.info(f"⚡ ENTRY FILLED: {event.side} {event.exec_qty} @ {event.exec_price}")
                    self.state = StrategyState.IN_POSITION
                    self.ctx.entry_price = event.exec_price
                    await self._place_take_profit()
                return

            # СЦЕНАРИЙ 2: Исполнение ТЕЙКА (TP)
            # [FIX] Теперь мы ловим и этот ID
            if self.ctx.tp_order_id and event.order_id == self.ctx.tp_order_id:
                logger.info(f"💰 TP FILLED: {event.side} {event.exec_qty} @ {event.exec_price}. Trade Closed.")
                self._reset_state()
                return

            # Если пришел какой-то левый ID (например, старый ордер), игнорируем

    # --- 3. MARKET DATA HANDLER ---
    async def on_depth(self, snapshot):
        if self._lock.locked(): return
        
        async with self._lock:
            try:
                self.lob.apply_update(snapshot)
                if not self.lob.bids or not self.lob.asks: return

                self._update_metrics()

                best_bid_p = self.lob.get_best("Buy")
                best_ask_p = self.lob.get_best("Sell")

                # FSM (Finite State Machine)
                if self.state == StrategyState.IDLE:
                    await self._logic_idle(best_bid_p, best_ask_p)

                elif self.state == StrategyState.ORDER_PLACED:
                    await self._logic_order_placed()

                elif self.state == StrategyState.IN_POSITION:
                    await self._logic_in_position(best_bid_p, best_ask_p)
                    
            except Exception as e:
                logger.error(f"💥 Loop Error: {e}", exc_info=True)

    def _update_metrics(self):
        bg_vol = self.lob.get_background_volume()
        if bg_vol <= 0: return
        if not self.initialized:
            self.avg_vol = bg_vol
            self.initialized = True
        else:
            alpha = self.cfg.vol_ema_alpha
            self.avg_vol = alpha * bg_vol + (1 - alpha) * self.avg_vol

    # --- LOGIC PER STATE ---

    async def _logic_idle(self, best_bid_p, best_ask_p):
        """Поиск стен и вход в сделку"""
        best_bid_v = self.lob.get_volume("Buy", best_bid_p)
        best_ask_v = self.lob.get_volume("Sell", best_ask_p)

        threshold = self.avg_vol * self.cfg.wall_ratio_threshold
        is_bid_wall = best_bid_v > threshold and (best_bid_v * best_bid_p > self.cfg.min_wall_value_usdt)
        is_ask_wall = best_ask_v > threshold and (best_ask_v * best_ask_p > self.cfg.min_wall_value_usdt)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"👀 SCAN: Bg={self.avg_vol:.0f} | BidWall={is_bid_wall} | AskWall={is_ask_wall}")

        if is_bid_wall or is_ask_wall:
            self._wall_confirms += 1
        else:
            self._wall_confirms = 0 

        if self._wall_confirms >= self._required_confirms:
            if is_bid_wall:
                # Встаем перед стеной на покупку (Long)
                await self._place_entry_order("Buy", best_bid_p, best_bid_p + self.tick_size)
            elif is_ask_wall:
                # Встаем перед стеной на продажу (Short)
                await self._place_entry_order("Sell", best_ask_p, best_ask_p - self.tick_size)
            
            # Сброс счетчика, чтобы не спамить
            self._wall_confirms = 0 

    async def _logic_order_placed(self):
        """
        Логика ожидания входа.
        Здесь мы следим за целостностью стены.
        """
        # Если стена исчезла, пока мы стояли в очереди -> попытка отмены
        if not self._check_wall_integrity():
            logger.debug("🧱 Wall collapsed. Initiating cancel sequence...")
            
            # 1. Отправляем отмену
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
            
            # 2. [CRITICAL FIX] Race Condition Protection
            # Нельзя просто так взять и сделать reset_state.
            # Ордер мог исполниться в момент отмены.
            
            # Небольшая пауза, чтобы матчинг биржи успел обновить баланс/вернуть ошибку
            # Это не polling, это safety wait перед принятием решения о судьбе депозита.
            await asyncio.sleep(0.2)
            
            # 3. Проверка Истины (Single Source of Truth)
            # Спрашиваем у биржи: "Мы в позиции?"
            real_pos = await self.exec.get_position(self.cfg.symbol)
            
            # Проверяем, совпадает ли реальная позиция с нашим ожиданием
            is_accidentally_filled = False
            
            if self.ctx.side == "Buy":
                # Если мы хотели купить 100, а у нас есть > 10 (учитываем частичное исполнение)
                if real_pos >= self.ctx.quantity * 0.1: 
                    is_accidentally_filled = True
            else:
                if real_pos <= -self.ctx.quantity * 0.1:
                    is_accidentally_filled = True

            if is_accidentally_filled:
                logger.warning(f"😱 GHOST FILL DETECTED! Cancel failed, we are IN POSITION: {real_pos}")
                
                self.state = StrategyState.IN_POSITION
                
                # На всякий случай обновляем цену входа (если она была 0, берем текущую рыночную как ориентир)
                # или оставляем лимитную.
                
                # Срочно ставим Тейк, если его еще нет
                if not self.ctx.tp_order_id:
                    await self._place_take_profit()
                    
            else:
                # Фух, пронесло. Действительно вышли.
                logger.info("✅ Order cancelled cleanly. Resetting state.")
                self._reset_state()
            
            return
        
        # Также можно добавить таймаут (если ордер висит > 10 сек)
        if time.time() - self.ctx.placed_ts > 15.0:
             logger.debug("⏳ Order timed out. Cancelling...")
             await self._cancel_and_reset()


    async def _safe_cancel_and_reset(self):
        await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
        await asyncio.sleep(0.2)
        
        real_pos = await self.exec.get_position(self.cfg.symbol)
        
        # Упрощенная проверка "Есть ли позиция в нашу сторону?"
        has_pos = (self.ctx.side == "Buy" and real_pos > 0) or (self.ctx.side == "Sell" and real_pos < 0)
        
        if has_pos:
            logger.warning(f"⚠️ Order filled during cancel sequence. Transitioning to IN_POSITION.")
            self.state = StrategyState.IN_POSITION
            await self._place_take_profit()
        else:
            self._reset_state()


    async def _logic_in_position(self, best_bid, best_ask):
        """Ведение позиции (Stop Loss, Breakout)"""
        exit_price = best_bid if self.ctx.side == "Buy" else best_ask
        
        # 1. PnL Check
        delta = (exit_price - self.ctx.entry_price) if self.ctx.side == "Buy" else (self.ctx.entry_price - exit_price)
        pnl_ticks = delta / self.tick_size
        
        if pnl_ticks <= -self.cfg.stop_loss_ticks:
            logger.warning(f"🛑 STOP LOSS: {pnl_ticks:.1f} ticks. Executing Panic Exit.")
            await self._panic_exit()
            return

        # 2. Пробой стены (Breakout)
        # Если цена ушла ЗА стену (то есть стену съели)
        wall_broken = False
        if self.ctx.side == "Buy":
            if exit_price < self.ctx.wall_price: wall_broken = True
        else:
            if exit_price > self.ctx.wall_price: wall_broken = True
        
        if wall_broken:
            logger.warning(f"🔨 WALL BROKEN! Price {exit_price} breached Wall {self.ctx.wall_price}")
            await self._panic_exit()
            return

        # 3. Check Balance (редкая проверка для синхронизации)
        # Если позиция закрылась по Тейку (который висит на бирже), мы об этом узнаем через execution,
        # но на всякий случай можно оставить редкий чек баланса или просто ждать события.
        # В Clean Event-Driven архитектуре здесь ничего делать не нужно.

    # --- ACTIONS ---

    async def _place_entry_order(self, side: str, wall_price: float, entry_price: float):
        raw_qty = self.cfg.order_amount_usdt / entry_price
        qty = self._round_qty(raw_qty)
        price = self._round_price(entry_price)
        
        if qty < self.cfg.min_qty or qty * price < 5.0: 
            return

        logger.info(f"🧱 FOUND WALL {side} @ {wall_price}. Placing limit @ {price}")
        
        oid = await self.exec.place_limit_maker(self.cfg.symbol, side, price, qty)
        if oid:
            self.state = StrategyState.ORDER_PLACED
            self.ctx = TradeContext(
                side=side, 
                wall_price=wall_price, 
                entry_price=price, 
                quantity=qty, 
                order_id=oid,
                placed_ts=time.time()
            )

    async def _place_take_profit(self):
        if self.cfg.use_dynamic_tp:
            delta_price = self.ctx.entry_price * (self.current_tp_pct / 100.0)
            tp_ticks = delta_price / self.tick_size
            tp_ticks = max(1, round(tp_ticks))
        else:
            tp_ticks = self.cfg.fixed_tp_ticks

        tp_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        sign = 1 if self.ctx.side == "Buy" else -1
        
        tp_price = self.ctx.entry_price + (sign * tp_ticks * self.tick_size)
        tp_price = self._round_price(tp_price)
        
        logger.info(f"🎯 PLACING TP @ {tp_price} (+{tp_ticks} ticks)")
        
        oid = await self.exec.place_limit_maker(self.cfg.symbol, tp_side, tp_price, self.ctx.quantity)
        self.ctx.tp_order_id = oid

    async def _cancel_and_reset(self):
        """Отмена ордера и сброс состояния"""
        if self.ctx and self.ctx.order_id:
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
        self._reset_state()

    async def _panic_exit(self):
        """Закрытие по рынку"""
        if self.ctx.tp_order_id:
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.tp_order_id)
            self.ctx.tp_order_id = None
        
        exit_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        await self.exec.place_market_order(self.cfg.symbol, exit_side, self.ctx.quantity)
        self._reset_state()

    # --- HELPERS ---
    def _check_wall_integrity(self) -> bool:
        current_vol = self.lob.get_volume(self.ctx.side, self.ctx.wall_price)
        # Если объем упал ниже 50% от среднего, считаем стену снятой
        threshold = self.avg_vol * self.cfg.wall_ratio_threshold * 0.5
        return current_vol > threshold

    def _reset_state(self):
        self.state = StrategyState.IDLE
        self.ctx = None

    def _get_decimals(self, step: float) -> int:
        if step == 0: return 0
        step_str = f"{step:.8f}".rstrip("0")
        if "." in step_str:
            val = step_str.split(".")[1]
            return len(val) if val else 0
        return 0

    def _round_price(self, price: float) -> float:
        if self.tick_size == 0: return price
        steps = round(price / self.tick_size)
        clean_price = steps * self.tick_size
        return round(clean_price, self.price_decimals)

    def _round_qty(self, qty: float) -> Union[float, int]:
        if self.cfg.lot_size == 0: return qty
        steps = math.floor(qty / self.cfg.lot_size)
        clean_qty = steps * self.cfg.lot_size
        clean_qty = round(clean_qty, self.qty_decimals)
        if self.qty_decimals == 0:
            return int(clean_qty)
        return clean_qty