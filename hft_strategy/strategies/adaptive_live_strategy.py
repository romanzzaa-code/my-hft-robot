# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import math
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, List, Union

# Зависим от абстракции
from hft_strategy.domain.interfaces import IExecutionHandler 
from hft_strategy.domain.strategy_config import StrategyParameters

logger = logging.getLogger("ADAPTIVE_STRAT")

# --- LOB (Infrastructure) ---
class LocalOrderBook:
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
        bg_bids = sorted_bids[1:11] 
        bg_asks = sorted_asks[1:11]
        
        volumes = []
        for p in bg_bids: volumes.append(self.bids[p])
        for p in bg_asks: volumes.append(self.asks[p])
        
        if not volumes: return 0.0
        return sum(volumes) / len(volumes)

# --- States & Context ---
class StrategyState(Enum):
    IDLE = auto()          
    ORDER_PLACED = auto()  
    IN_POSITION = auto()   

@dataclass
class TradeContext:
    side: str
    wall_price: float
    entry_price: float
    quantity: float
    order_id: str
    tp_order_id: Optional[str] = None

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
        self._required_confirms = 1
        
        self.price_decimals = self._get_decimals(cfg.tick_size)
        self.qty_decimals = self._get_decimals(cfg.lot_size)
        
        self.current_tp_pct = self.cfg.min_tp_percent 
        if self.cfg.use_dynamic_tp:
            asyncio.create_task(self._volatility_loop())

    # --- VOLATILITY LOGIC ---
    async def _volatility_loop(self):
        # [CLEANUP] INFO -> DEBUG (Не спамим при старте, если монет много)
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
                    
                    hl = curr['h'] - curr['l']
                    h_cp = abs(curr['h'] - prev['c'])
                    l_cp = abs(curr['l'] - prev['c'])
                    
                    tr = max(hl, h_cp, l_cp)
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

    def _update_metrics(self):
        bg_vol = self.lob.get_background_volume()
        if bg_vol <= 0: return
        if not self.initialized:
            self.avg_vol = bg_vol
            self.initialized = True
        else:
            alpha = self.cfg.vol_ema_alpha
            self.avg_vol = alpha * bg_vol + (1 - alpha) * self.avg_vol

    async def on_depth(self, snapshot):
        if self._lock.locked(): return
        async with self._lock:
            try:
                self.lob.apply_update(snapshot)
                if not self.lob.bids or not self.lob.asks: return

                self._update_metrics()

                best_bid_p = self.lob.get_best("Buy")
                best_ask_p = self.lob.get_best("Sell")
                best_bid_v = self.lob.get_volume("Buy", best_bid_p)
                best_ask_v = self.lob.get_volume("Sell", best_ask_p)

                if self.state == StrategyState.IDLE:
                    # Проверяем условия стены
                    threshold = self.avg_vol * self.cfg.wall_ratio_threshold
                    is_bid_wall = best_bid_v > threshold and (best_bid_v * best_bid_p > self.cfg.min_wall_value_usdt)
                    is_ask_wall = best_ask_v > threshold and (best_ask_v * best_ask_p > self.cfg.min_wall_value_usdt)

                    # [CLEANUP] Логирование сканирования только в DEBUG
                    # Это уберет 90% спама в консоли
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"👀 SCAN [{self.cfg.symbol}]: Bg={self.avg_vol:.0f} | Thr={threshold:.0f} | "
                            f"BidWall={is_bid_wall} | AskWall={is_ask_wall}"
                        )

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

                elif self.state == StrategyState.ORDER_PLACED:
                    await self._handle_order_placed()
                elif self.state == StrategyState.IN_POSITION:
                    await self._handle_in_position(best_bid_p, best_ask_p)
                    
            except Exception as e:
                logger.error(f"💥 Loop Error: {e}", exc_info=True)

    async def _handle_order_placed(self):
        real_pos = await self.exec.get_position(self.cfg.symbol)
        
        is_filled = False
        if self.ctx.side == "Buy":
            is_filled = real_pos >= self.ctx.quantity * 0.9 
        else:
            is_filled = real_pos <= -self.ctx.quantity * 0.9

        if is_filled:
             # [KEEP INFO] Важное событие - вход в позицию
             logger.info(f"✅ FILLED ({self.ctx.side}). Pos: {real_pos}")
             self.state = StrategyState.IN_POSITION
             await self._place_take_profit()
             return

        if not self._check_wall_integrity():
            # [CLEANUP] INFO -> DEBUG (Это рутина для HFT)
            logger.debug("🧱 Wall collapsed. Attempting cancel...")
            
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.order_id)
            
            await asyncio.sleep(0.5) 
            real_pos_after = await self.exec.get_position(self.cfg.symbol)
            
            is_filled_after = False
            if self.ctx.side == "Buy":
                is_filled_after = real_pos_after >= self.ctx.quantity * 0.1 
            else:
                is_filled_after = real_pos_after <= -self.ctx.quantity * 0.1

            if is_filled_after:
                logger.warning(f"😅 Race condition caught! Filled during cancel. Pos: {real_pos_after}")
                self.state = StrategyState.IN_POSITION
                await self._place_take_profit()
            else:
                # [CLEANUP] INFO -> DEBUG
                logger.debug("🗑️ Order cancelled/gone. Resetting state.")
                self._reset_state()
            return

    async def _handle_in_position(self, best_bid, best_ask):
        exit_price = best_bid if self.ctx.side == "Buy" else best_ask
        pnl = (exit_price - self.ctx.entry_price) if self.ctx.side == "Buy" else (self.ctx.entry_price - exit_price)
        pnl_ticks = pnl / self.tick_size
        
        if pnl_ticks <= -self.cfg.stop_loss_ticks:
            # [KEEP WARNING] Это потеря денег, надо видеть
            logger.warning(f"🛑 HARD STOP LOSS ({pnl_ticks:.1f} ticks).")
            await self._panic_exit()
            return

        wall_broken = False
        if self.ctx.side == "Buy":
            if exit_price < self.ctx.wall_price: 
                wall_broken = True
        else:
            if exit_price > self.ctx.wall_price: 
                wall_broken = True
        
        if wall_broken:
            # [KEEP WARNING] Пробой стены
            logger.warning(f"🔨 WALL BROKEN/EATEN! Price: {exit_price} vs Wall: {self.ctx.wall_price}")
            await self._panic_exit()
            return

        if not self._check_wall_integrity():
            # [KEEP INFO] Это важный сигнал, что робот перешел в режим HOLD
            # Но можно сделать DEBUG, если слишком часто мигает. Пока оставим INFO.
            logger.info(f"⚠️ Wall volume gone. Price safe. HOLDING. Delta: {abs(exit_price - self.ctx.wall_price):.4f}")
            # Мы решили НЕ выходить, если цена не пробита
            pass 

        real_pos = await self.exec.get_position(self.cfg.symbol)
        if abs(real_pos) < self.ctx.quantity * 0.1:
            # [KEEP INFO] Прибыль
            logger.info("💰 TP EXECUTED (Confirmed by balance).")
            self._reset_state()

    # --- UTILS ---
    def _check_wall_integrity(self) -> bool:
        current_vol = self.lob.get_volume(self.ctx.side, self.ctx.wall_price)
        threshold = self.avg_vol * self.cfg.wall_ratio_threshold * 0.5
        return current_vol > threshold

    async def _place_entry_order(self, side: str, wall_price: float, entry_price: float):
        raw_qty = self.cfg.order_amount_usdt / entry_price
        
        qty = self._round_qty(raw_qty)
        price = self._round_price(entry_price)
        
        if qty < self.cfg.min_qty: return
        if qty * price < 5.0: return

        # [KEEP INFO] Попытка входа - это важно
        logger.info(f"🧱 WALL DETECTED: {side} {self.lob.get_volume(side, wall_price):.0f}. Order @ {price}")
        
        oid = await self.exec.place_limit_maker(self.cfg.symbol, side, price, qty)
        if oid:
            self.state = StrategyState.ORDER_PLACED
            self.ctx = TradeContext(side, wall_price, price, qty, oid)

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
        
        # [KEEP INFO] Выставление тейка
        logger.info(f"🎯 TP PLACED @ {tp_price} (+{self.current_tp_pct:.2f}% / {tp_ticks} ticks)")
        
        oid = await self.exec.place_limit_maker(self.cfg.symbol, tp_side, tp_price, self.ctx.quantity)
        self.ctx.tp_order_id = oid

    async def _panic_exit(self):
        if self.ctx.tp_order_id:
            await self.exec.cancel_order(self.cfg.symbol, self.ctx.tp_order_id)
        
        exit_side = "Sell" if self.ctx.side == "Buy" else "Buy"
        await self.exec.place_market_order(self.cfg.symbol, exit_side, self.ctx.quantity)
        self._reset_state()

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