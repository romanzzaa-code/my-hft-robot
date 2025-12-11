import logging
from typing import Dict, List, Optional

logger = logging.getLogger("SCANNER")

class MarketScanner:
    """
    Аналитический модуль.
    Принимает поток тикеров (TickerData) и определяет топ монет по обороту (Turnover).
    """
    def __init__(self, top_size: int = 5):
        self.top_size = top_size
        # Хранилище статистики: Symbol -> Turnover24h
        self._stats: Dict[str, float] = {} 

    def on_ticker_update(self, ticker):
        """
        Коллбек, вызываемый из C++ (через streamer.set_ticker_callback).
        В ticker приходит объект TickerData.
        """
        # Обновление словаря — операция O(1), это очень быстро
        self._stats[ticker.symbol] = ticker.turnover_24h

    def get_top_coins(self) -> List[str]:
        """
        Возвращает список тикеров (символов), входящих в Топ-N по обороту.
        """
        if not self._stats:
            return []
            
        # Сортировка всего рынка (150-200 монет) по убыванию оборота.
        # Для такого количества элементов это микросекунды.
        sorted_coins = sorted(
            self._stats.items(), 
            key=lambda item: item[1], 
            reverse=True
        )
        
        # Возвращаем только список строк ['SOLUSDT', 'PEPEUSDT', ...]
        top_list = [s[0] for s in sorted_coins[:self.top_size]]
        return top_list