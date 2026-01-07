# hft_strategy/services/wall_detector.py
import logging
from typing import Optional, Dict, Tuple
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.infrastructure.local_order_book import LocalOrderBook

logger = logging.getLogger("DETECTOR")

class WallDetector:
    """
    Отвечает за обнаружение ликвидных стен в стакане.
    Не совершает сделок, только генерирует сигналы.
    """
    def __init__(self, cfg: StrategyParameters):
        self.cfg = cfg
        
        # Логика подтверждения (Debounce)
        self._wall_confirms = 0
        self._required_confirms = 3 # Можно вынести в конфиг

    def detect_signal(self, lob: LocalOrderBook, avg_vol: float) -> Optional[Dict]:
        """
        Анализирует стакан и возвращает параметры входа, если сигнал найден.
        """
        best_bid_p = lob.get_best("Buy")
        best_ask_p = lob.get_best("Sell")
        
        if best_bid_p == 0 or best_ask_p == 0:
            return None

        best_bid_v = lob.get_volume("Buy", best_bid_p)
        best_ask_v = lob.get_volume("Sell", best_ask_p)

        # 1. Расчет динамического порога на основе EMA объема из MarketAnalytics
        threshold = avg_vol * self.cfg.wall_ratio_threshold
        
        # 2. Проверка условий «Стены»
        is_bid_wall = best_bid_v > threshold and (best_bid_v * best_bid_p > self.cfg.min_wall_value_usdt)
        is_ask_wall = best_ask_v > threshold and (best_ask_v * best_ask_p > self.cfg.min_wall_value_usdt)

        # 3. Логика подтверждения (чтобы не прыгать на мерцающие заявки)
        if is_bid_wall or is_ask_wall:
            self._wall_confirms += 1
        else:
            self._wall_confirms = 0 

        if self._wall_confirms >= self._required_confirms:
            self._wall_confirms = 0 # Сброс после срабатывания
            
            if is_bid_wall:
                return {
                    "side": "Buy",
                    "wall_price": best_bid_p,
                    "entry_price": best_bid_p + self.cfg.tick_size
                }
            elif is_ask_wall:
                return {
                    "side": "Sell",
                    "wall_price": best_ask_p,
                    "entry_price": best_ask_p - self.cfg.tick_size
                }
        
        return None