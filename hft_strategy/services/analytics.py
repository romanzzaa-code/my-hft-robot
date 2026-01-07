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
    Освобождает стратегию от циклов запроса свечей и математики цен.
    """
    def __init__(self, executor: IExecutionHandler, cfg: StrategyParameters):
        self.exec = executor
        self.cfg = cfg
        
        # Состояние метрик
        self.current_tp_pct = cfg.min_tp_percent
        self.avg_background_vol = 0.0
        self.is_initialized = False
        
        self._running = False

    async def start(self):
        """Запуск фонового мониторинга волатильности"""
        self._running = True
        asyncio.create_task(self._volatility_loop())
        logger.info(f"🌊 MarketAnalytics started for {self.cfg.symbol}")

    def stop(self):
        self._running = False

    def update_background_volume(self, current_bg_vol: float):
        """Расчет EMA объема (вызывается из стратегии при каждом апдейте стакана)"""
        if current_bg_vol <= 0: return
        
        if not self.is_initialized:
            self.avg_background_vol = current_bg_vol
            self.is_initialized = True
        else:
            alpha = self.cfg.vol_ema_alpha
            self.avg_background_vol = alpha * current_bg_vol + (1 - alpha) * self.avg_background_vol

    def calculate_exits(self, side: str, entry_price: float, wall_price: float) -> tuple[float, float]:
        """
        Рассчитывает цены Take Profit и Stop Loss на основе текущей волатильности (NATR).
        Возвращает: (tp_price, sl_price)
        """
        tick = self.cfg.tick_size
        if tick <= 0: tick = 0.01 
        
        # 1. Расчет Тейка (на основе динамического % из волатильности)
        target_pct = self.current_tp_pct
        
        if side == "Buy":
            raw_tp = entry_price * (1 + target_pct / 100)
            # Стоп для лонга: на 1 тик ниже стены
            raw_sl = wall_price - tick
        else: # Sell
            raw_tp = entry_price * (1 - target_pct / 100)
            # Стоп для шорта: на 1 тик выше стены
            raw_sl = wall_price + tick

        # 2. Округление до шага цены
        tp_price = round(round(raw_tp / tick) * tick, 8)
        sl_price = round(round(raw_sl / tick) * tick, 8)
        
        # 3. Санитарная проверка (чтобы Тейк не был слишком близко)
        min_dist = 5 * tick
        dist = abs(tp_price - entry_price)
        
        if dist < min_dist:
            if side == "Buy": tp_price = entry_price + min_dist
            else: tp_price = entry_price - min_dist
            tp_price = round(tp_price, 8)

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
                
                logger.debug(f"📊 Metrics updated: NATR={natr:.2f}%, TargetTP={self.current_tp_pct:.2f}%")
                
            except Exception as e:
                logger.error(f"❌ Volatility calculation error: {e}")
            
            await asyncio.sleep(60)