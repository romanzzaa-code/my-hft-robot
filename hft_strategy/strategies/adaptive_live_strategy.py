# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import math
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, List, Union

from hft_strategy.infrastructure.execution import BybitExecutionHandler
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
    def __init__(self, executor: BybitExecutionHandler, cfg: StrategyParameters):
        self.exec = executor
        self.cfg = cfg
        self.state = StrategyState.IDLE
        self.ctx: Optional[TradeContext] = None
        self.lob = LocalOrderBook()
        self._lock = asyncio.Lock()
        
        self.tick_size = cfg.tick_size
        self.avg_vol = 0.0 
        self.initialized = False
        self._last_log_ts = 0
        
        # [FIX] Precision Management
        self.price_decimals = self._get_decimals(cfg.tick_size)
        self.qty_decimals = self._get_decimals(cfg.lot_size)
        
        # Dynamic Take Profit State
        self.current_tp_pct = self.cfg.min_tp_percent 
        if self.cfg.use_dynamic_tp:
            asyncio.create_task(self._volatility_loop())

    # --- VOLATILITY LOGIC ---
    async def _volatility_loop(self):
        logger.info("🌊 Volatility Watchdog Started")
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
                    await self._handle_idle(best_bid_p, best_bid_v, best_ask_p, best_ask_v)
                elif self.state == StrategyState.ORDER_PLACED:
                    await self._handle_order_placed()
                elif self.state == StrategyState.IN_POSITION:
                    await self._handle_in_position(best_bid_p, best_ask_p)
                    
            except Exception as e:
                logger.error(f"💥 Loop Error: {e}", exc_info=True)

    async def _handle_idle(self, bid_p, bid_v, ask_p, ask_v):
        threshold = self.avg_vol * self.cfg.wall_ratio_threshold
        now = asyncio.get_running_loop().time()
        if now - self._last_log_ts > 10.0:
            logger.info(
                f"👀 SCAN [{self.cfg.symbol}]: Bg={self.avg_vol:.0f} | Thr={threshold:.0f} | "
                f"TP={self.current_tp_pct:.2f}%"
            )
            self._last_log_ts = now

        if bid_v > threshold and (bid_v * bid_p > self.cfg.min_wall_value_usdt):
            await self._place_entry_order("Buy", bid_p, bid_p + self.tick_size)
            return

        if ask_v > threshold and (ask_v * ask_p > self.cfg.min_wall_value_usdt):
            await self._place_entry_order("Sell", ask_p, ask_p - self.tick_size)

    async def _handle_order_placed(self):
        if not self._check_wall_integrity():
            await self.exec.cancel_order(self.ctx.order_id)
            self._reset_state()
            return

        real_pos = await self.exec.get_position()
        
        if (self.ctx.side == "Buy" and real_pos >= self.ctx.quantity * 0.9) or \
           (self.ctx.side == "Sell" and real_pos <= -self.ctx.quantity * 0.9):
             logger.info(f"✅ FILLED ({self.ctx.side}). Pos: {real_pos}")
             self.state = StrategyState.IN_POSITION
             await self._place_take_profit()

    async def _handle_in_position(self, best_bid, best_ask):
        if not self._check_wall_integrity():
            logger.warning("⚠️ Wall COLLAPSED! PANIC EXIT.")
            await self._panic_exit()
            return

        curr_price = best_bid if self.ctx.side == "Buy" else best_ask
        pnl = (curr_price - self.ctx.entry_price) if self.ctx.side == "Buy" else (self.ctx.entry_price - curr_price)
        pnl_ticks = pnl / self.tick_size
        
        if pnl_ticks <= -self.cfg.stop_loss_ticks:
            logger.warning(f"🛑 STOP LOSS ({pnl_ticks:.1f} ticks).")
            await self._panic_exit()
            return

        real_pos = await self.exec.get_position()
        if abs(real_pos) < self.ctx.quantity * 0.1:
            logger.info("💰 TP EXECUTED.")
            self._reset_state()

    # --- UTILS ---
    def _check_wall_integrity(self) -> bool:
        current_vol = self.lob.get_volume(self.ctx.side, self.ctx.wall_price)
        threshold = self.avg_vol * self.cfg.wall_ratio_threshold * 0.5
        return current_vol > threshold

    async def _place_entry_order(self, side: str, wall_price: float, entry_price: float):
        raw_qty = self.cfg.order_amount_usdt / entry_price
        
        # [UPDATED] Используем строгую логику округления и проверки min_qty
        qty = self._round_qty(raw_qty)
        price = self._round_price(entry_price)
        
        # Фильтр: Минимальный объем (из лота)
        if qty < self.cfg.min_qty:
            return
            
        # Фильтр: Минимальная стоимость ($5, например)
        if qty * price < 5.0: 
            return

        logger.info(f"🧱 WALL: {side} {self.lob.get_volume(side, wall_price):.0f} @ {wall_price}. Order @ {price}")
        oid = await self.exec.place_limit_maker(side, price, qty)
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
        
        logger.info(f"🎯 TP @ {tp_price} (+{self.current_tp_pct:.2f}% / {tp_ticks} ticks)")
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

    def _get_decimals(self, step: float) -> int:
        if step == 0: return 0
        step_str = f"{step:.8f}".rstrip("0")
        if "." in step_str:
            # Убираем точку в конце "1."
            val = step_str.split(".")[1]
            return len(val) if val else 0
        return 0

    def _round_price(self, price: float) -> float:
        if self.tick_size == 0: return price
        steps = round(price / self.tick_size)
        clean_price = steps * self.tick_size
        return round(clean_price, self.price_decimals)

    def _round_qty(self, qty: float) -> Union[float, int]:
        """
        Корректное округление QTY.
        1. Формула: floor(qty / step) * step
        2. Если шаг целый (decimals=0), возвращаем int (напр. 6 вместо 6.0)
        """
        if self.cfg.lot_size == 0: return qty
        
        # 1. Floor round (по спецификации API)
        steps = math.floor(qty / self.cfg.lot_size)
        clean_qty = steps * self.cfg.lot_size
        
        # 2. Убираем "шум" float (напр. 6.000000001 -> 6.0)
        clean_qty = round(clean_qty, self.qty_decimals)
        
        # 3. Приведение к int для целочисленных шагов
        if self.qty_decimals == 0:
            return int(clean_qty)
            
        return clean_qty