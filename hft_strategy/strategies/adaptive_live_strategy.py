# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import math
import time
import uuid
from typing import Optional, Dict, Union, List

# --- C++ Core Bindings (Защита от импорта) ---
try:
    from hft_core import TickData, OrderBookSnapshot, OrderGateway
except ImportError:
    # Заглушки для разработки без скомпилированного C++ модуля
    TickData = object
    OrderBookSnapshot = object
    OrderGateway = object

from hft_strategy.domain.interfaces import IExecutionHandler 
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.trade_context import TradeContext, StrategyState

logger = logging.getLogger("ADAPTIVE_STRAT")

# --- LOB (Infrastructure) ---
class LocalOrderBook:
    """
    Гибридный локальный стакан.
    Поддерживает обновление через Python-объекты (HTTP/WS) и через C++ Snapshots.
    """
    def __init__(self):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_ts = 0

    def _to_key(self, price: float) -> float:
        return round(price, 8)

    def apply_update(self, event):
        """Легаси-метод для Python событий (например, REST Snapshot)"""
        if getattr(event, 'is_snapshot', False):
            self.bids.clear()
            self.asks.clear()

        # Обработка bids
        for level in event.bids:
            key = self._to_key(level.price)
            if level.quantity == 0:
                if key in self.bids: del self.bids[key]
            else:
                self.bids[key] = level.quantity

        # Обработка asks
        for level in event.asks:
            key = self._to_key(level.price)
            if level.quantity == 0:
                if key in self.asks: del self.asks[key]
            else:
                self.asks[key] = level.quantity
        
        self.last_ts = getattr(event, 'timestamp', time.time())

    def apply_snapshot(self, snapshot: OrderBookSnapshot):
        """
        Метод для быстрого C++ снепшота.
        Ожидает, что snapshot имеет итерируемые поля bids/asks (price, qty).
        """
        self.bids.clear()
        self.asks.clear()
        
        # Предполагаем структуру [(price, qty), ...] или объекты с полями .price/.qty
        # Адаптируйте этот цикл под реальную структуру вашего C++ биндинга
        try:
            for item in snapshot.bids:
                p = getattr(item, 'price', item[0] if isinstance(item, (tuple, list)) else item)
                q = getattr(item, 'quantity', getattr(item, 'qty', item[1] if isinstance(item, (tuple, list)) else 0))
                self.bids[self._to_key(p)] = q
                
            for item in snapshot.asks:
                p = getattr(item, 'price', item[0] if isinstance(item, (tuple, list)) else item)
                q = getattr(item, 'quantity', getattr(item, 'qty', item[1] if isinstance(item, (tuple, list)) else 0))
                self.asks[self._to_key(p)] = q
                
            self.last_ts = time.time()
        except Exception as e:
            logger.error(f"LOB Snapshot Error: {e}")

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

# --- Strategy ---
class AdaptiveWallStrategy:
    def __init__(self, 
                 executor: IExecutionHandler, 
                 cfg: StrategyParameters,
                 gateway: Optional[OrderGateway] = None): # Внедрение зависимости C++
        
        self.exec = executor   # HTTP REST (для сложных операций и баланса)
        self.gateway = gateway # C++ WebSocket (для быстрого выставления)
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

    # --- 2. EXECUTION HANDLER ---
    async def on_execution(self, event):
        """
        Обработчик событий исполнения. Поддерживает события и от REST, и от Gateway.
        """
        async with self._lock:
            if not self.ctx:
                return

            # СЦЕНАРИЙ 1: Исполнение ВХОДА
            # Проверяем совпадение ID. Если Gateway вернул ClientID, event.order_id должен совпадать.
            if event.order_id == self.ctx.order_id:
                new_fill = event.exec_qty
                self.ctx.filled_qty += new_fill
                
                logger.info(f"⚡ FILL: {event.symbol} +{new_fill} (Total: {self.ctx.filled_qty}/{self.ctx.quantity})")

                if self.state == StrategyState.ORDER_PLACED:
                    self.state = StrategyState.IN_POSITION
                    self.ctx.entry_price = event.exec_price

                await self._sync_take_profit()
                return

            # СЦЕНАРИЙ 2: Исполнение ВЫХОДА
            if self.ctx.tp_order_id and event.order_id == self.ctx.tp_order_id:
                filled_exit = event.exec_qty
                self.ctx.filled_qty -= filled_exit
                
                if self.ctx.filled_qty <= 1e-9:
                    logger.info(f"💰 POSITION CLOSED FULLY: {event.symbol}")
                    self._reset_state()
                else:
                    logger.info(f"📉 TP PARTIAL: -{filled_exit}. Remaining: {self.ctx.filled_qty}")
                return

    async def _sync_take_profit(self):
        """Управляет Тейк-Профитом через REST (надежность + ReduceOnly)."""
        if self.ctx.filled_qty <= 1e-9: return

        tp_price = self._calculate_tp_price()
        tp_side = "Sell" if self.ctx.side == "Buy" else "Buy"

        # 1. Если Тейка нет — создаем
        if not self.ctx.tp_order_id:
            logger.info(f"🎯 PLACING TP: {self.ctx.filled_qty} @ {tp_price} (ReduceOnly)")
            # Для TP используем HTTP executor, так как нужен ReduceOnly и надежность
            oid = await self.exec.place_limit_maker(
                self.cfg.symbol, tp_side, tp_price, self.ctx.filled_qty, reduce_only=True
            )
            if oid:
                self.ctx.tp_order_id = oid
        
        # 2. Если Тейк есть — обновляем
        else:
            success = await self.exec.amend_order(
                self.cfg.symbol, self.ctx.tp_order_id, self.ctx.filled_qty
            )
            if not success:
                logger.warning("⚠️ Amend failed. Waiting for next execution event.")

    def _calculate_tp_price(self) -> float:
        if self.cfg.use_dynamic_tp:
            delta_price = self.ctx.entry_price * (self.current_tp_pct / 100.0)
            tp_ticks = delta_price / self.tick_size
            tp_ticks = max(1, round(tp_ticks))
        else:
            tp_ticks = self.cfg.fixed_tp_ticks

        sign = 1 if self.ctx.side == "Buy" else -1
        tp_price = self.ctx.entry_price + (sign * tp_ticks * self.tick_size)
        return self._round_price(tp_price)

    # --- 3. MARKET DATA HANDLER ---

    def on_tick(self, tick: TickData):
        """
        Точка входа для тиков из C++ Gateway.
        Для стратегии WallDetection тики используются только для мониторинга PnL,
        основная логика в on_depth.
        """
        # Если нужно обновить метрики или проверить стоп-лосс на каждом тике:
        # self._check_stop_loss_fast(tick.price)
        pass

    async def on_depth(self, snapshot):
        """
        Единая точка обработки стакана (WS Python или C++).
        """
        if self._lock.locked(): return
        
        async with self._lock:
            try:
                # Определение типа входящих данных
                if hasattr(snapshot, 'bids') and not isinstance(snapshot.bids, dict):
                    # C++ Snapshot
                    self.lob.apply_snapshot(snapshot)
                else:
                    # Python Event
                    self.lob.apply_update(snapshot)
                
                if not self.lob.bids or not self.lob.asks: return

                self._update_metrics()

                best_bid_p = self.lob.get_best("Buy")
                best_ask_p = self.lob.get_best("Sell")

                # FSM
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
        best_bid_v = self.lob.get_volume("Buy", best_bid_p)
        best_ask_v = self.lob.get_volume("Sell", best_ask_p)

        threshold = self.avg_vol * self.cfg.wall_ratio_threshold
        is_bid_wall = best_bid_v > threshold and (best_bid_v * best_bid_p > self.cfg.min_wall_value_usdt)
        is_ask_wall = best_ask_v > threshold and (best_ask_v * best_ask_p > self.cfg.min_wall_value_usdt)

        if is_bid_wall or is_ask_wall:
            self._wall_confirms += 1
        else:
            self._wall_confirms = 0 

        if self._wall_confirms >= self._required_confirms:
            if is_bid_wall:
                await self._place_entry_order("Buy", best_bid_p, best_bid_p + self.tick_size)
            elif is_ask_wall:
                await self._place_entry_order("Sell", best_ask_p, best_ask_p - self.tick_size)
            
            self._wall_confirms = 0 

    async def _logic_order_placed(self):
        if not self._check_wall_integrity():
            logger.debug("🧱 Wall collapsed. Cancelling entry...")
            await self._safe_cancel_and_reset()
            return
        
        if time.time() - self.ctx.placed_ts > 15.0:
             logger.debug("⏳ Order timed out. Cancelling...")
             await self._safe_cancel_and_reset()

    async def _logic_in_position(self, best_bid, best_ask):
        if self.ctx.filled_qty <= 1e-9: return

        exit_price = best_bid if self.ctx.side == "Buy" else best_ask
        delta = (exit_price - self.ctx.entry_price) if self.ctx.side == "Buy" else (self.ctx.entry_price - exit_price)
        pnl_ticks = delta / self.tick_size
        
        # Stop Loss Check
        if pnl_ticks <= -self.cfg.stop_loss_ticks:
            logger.warning(f"🛑 STOP LOSS: {pnl_ticks:.1f} ticks. Panic Exit.")
            await self._panic_exit()
            return

        # Wall Breakout Check
        wall_broken = False
        if self.ctx.side == "Buy":
            if exit_price < self.ctx.wall_price: wall_broken = True
        else:
            if exit_price > self.ctx.wall_price: wall_broken = True
        
        if wall_broken:
            logger.warning(f"🔨 WALL BROKEN! Price {exit_price} breached Wall {self.ctx.wall_price}")
            await self._panic_exit()
            return

    # --- ACTIONS ---

    async def _place_entry_order(self, side: str, wall_price: float, entry_price: float):
        raw_qty = self.cfg.order_amount_usdt / entry_price
        qty = self._round_qty(raw_qty)
        price = self._round_price(entry_price)
        
        if qty < self.cfg.min_qty or qty * price < 5.0: 
            return

        logger.info(f"🧱 FOUND WALL {side} @ {wall_price}. Sending Limit @ {price}")
        
        # Генерируем Client Order ID для отслеживания
        client_oid = str(uuid.uuid4())

        # --- ВЕТВЛЕНИЕ: GATEWAY VS HTTP ---
        if self.gateway:
            try:
                # 1. Отправляем через C++ (Fire-and-forget)
                self.gateway.send_order(
                    self.cfg.symbol, 
                    side, 
                    float(qty), 
                    float(price)
                    # Если шлюз поддерживает client_oid, передайте его здесь
                )
                
                # 2. Оптимистичное обновление состояния
                self.state = StrategyState.ORDER_PLACED
                self.ctx = TradeContext(
                    side=side, 
                    wall_price=wall_price, 
                    entry_price=price, 
                    quantity=qty, 
                    order_id=client_oid, # Надеемся, что шлюз вернет это в event.order_id или у вас есть маппинг
                    filled_qty=0.0,
                    placed_ts=time.time()
                )
                logger.info("🚀 Order sent via C++ Gateway")
                return
            except Exception as e:
                logger.error(f"❌ Gateway Error: {e}. Falling back to HTTP.")
                # Если ошибка шлюза, идем к HTTP ниже
        
        # Fallback (или если шлюза нет): HTTP
        oid = await self.exec.place_limit_maker(self.cfg.symbol, side, price, qty, reduce_only=False)
        if oid:
            self.state = StrategyState.ORDER_PLACED
            self.ctx = TradeContext(
                side=side, 
                wall_price=wall_price, 
                entry_price=price, 
                quantity=qty, 
                order_id=oid,
                filled_qty=0.0,
                placed_ts=time.time()
            )

    async def _safe_cancel_and_reset(self):
        """Безопасная отмена с проверкой."""
        if self.gateway:
            # TODO: Реализовать отмену через Gateway, если поддерживается.
            # Пока используем HTTP для надежности отмены.
            pass
            
        await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
        
        await asyncio.sleep(0.2)
        
        if self.ctx.filled_qty > 0:
            logger.warning(f"⚠️ Cancelled order was partially filled: {self.ctx.filled_qty}. Staying IN_POSITION.")
            await self._sync_take_profit()
        else:
            self._reset_state()

    async def _panic_exit(self):
        """Экстренный выход по рынку."""
        if not self.ctx or self.ctx.filled_qty <= 1e-9: return
        
        if self.ctx.tp_order_id:
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.tp_order_id)
            self.ctx.tp_order_id = None
        
        exit_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        logger.warning(f"🚨 PANIC EXIT: {exit_side} {self.ctx.filled_qty} (ReduceOnly)")
        
        # Для паник-выхода лучше HTTP, так как нужен точный флаг ReduceOnly, 
        # который простые шлюзы иногда игнорируют.
        await self.exec.place_market_order(
            self.cfg.symbol, 
            exit_side, 
            self.ctx.filled_qty, 
            reduce_only=True
        )
        self._reset_state()

    # --- HELPERS ---
    def _check_wall_integrity(self) -> bool:
        current_vol = self.lob.get_volume(self.ctx.side, self.ctx.wall_price)
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