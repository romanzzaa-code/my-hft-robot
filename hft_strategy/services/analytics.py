# hft_strategy/services/analytics.py
import asyncio
import logging
from typing import Optional, List, Dict
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.interfaces import IExecutionHandler

logger = logging.getLogger("ANALYTICS")

class MarketAnalytics:
    """
    Сервис мониторинга волатильности и фоновых объемов.
    """
    def __init__(self, executor: IExecutionHandler, cfg: StrategyParameters):
        self.exec = executor
        self.cfg = cfg
        
        self.current_tp_pct = cfg.min_tp_percent
        self.avg_background_vol = 0.0
        self.is_initialized = False
        
        self._running = False

    async def start(self):
        self._running = True
        asyncio.create_task(self._volatility_loop())
        logger.info(f"🌊 MarketAnalytics started for {self.cfg.symbol}")

    def stop(self):
        self._running = False

    def update_background_volume(self, current_bg_vol: float):
        if current_bg_vol <= 0: return
        
        if not self.is_initialized:
            self.avg_background_vol = current_bg_vol
            self.is_initialized = True
        else:
            alpha = self.cfg.vol_ema_alpha
            self.avg_background_vol = alpha * current_bg_vol + (1 - alpha) * self.avg_background_vol

    def calculate_exits(self, side: str, entry_price: float, wall_price: float) -> tuple[float, float]:
        """
        Рассчитывает TP (динамический) и SL (строго за стеной).
        """
        tick = self.cfg.tick_size
        if tick <= 0: tick = 0.0001 # Fallback
        
        # 1. Тейк-Профит (через NATR)
        target_pct = self.current_tp_pct
        
        # 2. Стоп-Лосс: строго ОТ СТЕНЫ
        # Берем отступ из конфига (там должно быть 1)
        sl_offset = self.cfg.stop_loss_ticks * tick 

        if side == "Buy":
            # TP: Вход + %
            raw_tp = entry_price * (1 + target_pct / 100)
            
            # SL: Цена Стены - Отступ (вниз)
            # Пример: Стена 100, Тик 1 -> Стоп 99
            raw_sl = wall_price - sl_offset
            
        else: # Sell
            # TP: Вход - %
            raw_tp = entry_price * (1 - target_pct / 100)
            
            # SL: Цена Стены + Отступ (вверх)
            # Пример: Стена 100, Тик 1 -> Стоп 101
            raw_sl = wall_price + sl_offset

        # 3. Округление
        tp_price = round(round(raw_tp / tick) * tick, 8)
        sl_price = round(round(raw_sl / tick) * tick, 8)
        
        # [DEBUG LOG] Чтобы ты видел математику в консоли
        logger.debug(
            f"📐 CALC: Side={side} | Wall={wall_price} | Entry={entry_price} | "
            f"SL_Offset={self.cfg.stop_loss_ticks} ticks | -> SL={sl_price}"
        )

        return tp_price, sl_price

    async def _volatility_loop(self):
        """Фоновый цикл расчета ATR"""
        while self._running:
            try:
                klines = await self.exec.fetch_ohlc(
                    self.cfg.symbol, 
                    interval="5", 
                    limit=self.cfg.natr_period + 1
                )
                
                if len(klines) < 2:
                    await asyncio.sleep(60)
                    continue
                
                trs = []
                for i in range(len(klines) - 1):
                    curr, prev = klines[i], klines[i+1]
                    tr = max(
                        curr['h'] - curr['l'], 
                        abs(curr['h'] - prev['c']), 
                        abs(curr['l'] - prev['c'])
                    )
                    trs.append(tr)
                
                atr = sum(trs) / len(trs)
                current_close = klines[0]['c']
                
                natr = (atr / current_close) * 100 if current_close > 0 else 0
                
                self.current_tp_pct = max(
                    natr * self.cfg.tp_natr_multiplier, 
                    self.cfg.min_tp_percent
                )
                
            except Exception as e:
                logger.error(f"❌ Volatility calculation error: {e}")
            
            await asyncio.sleep(60)