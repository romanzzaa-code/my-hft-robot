# hft_strategy/infrastructure/local_order_book.py
from typing import Dict, List, Optional

class LocalOrderBook:
    """
    Поддерживает локальную копию стакана (LOB) на основе событий Snapshot и Delta.
    Решает проблему float-ключей и рассчитывает фоновую ликвидность.
    """
    def __init__(self):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_ts = 0

    def _to_key(self, price: float) -> float:
        """Нормализация ключа для исправления ошибок IEEE 754"""
        return round(price, 8)

    def apply_update(self, event):
        """Применяет обновление (полиморфизм: работает и со снимком, и с дельтой)"""
        # Проверка на атрибут is_snapshot (duck typing)
        if getattr(event, 'is_snapshot', False):
            self.bids.clear()
            self.asks.clear()

        # Обновление Bids
        for level in event.bids:
            key = self._to_key(level.price)
            if level.quantity == 0:
                if key in self.bids:
                    del self.bids[key]
            else:
                self.bids[key] = level.quantity

        # Обновление Asks
        for level in event.asks:
            key = self._to_key(level.price)
            if level.quantity == 0:
                if key in self.asks:
                    del self.asks[key]
            else:
                self.asks[key] = level.quantity
        
        self.last_ts = event.timestamp

    def get_volume(self, side: str, price: float) -> float:
        """Возвращает объем по цене с защитой от отсутствия ключа"""
        book = self.bids if side == "Buy" else self.asks
        key = self._to_key(price)
        return book.get(key, 0.0)

    def get_best(self, side: str) -> float:
        """Возвращает лучшую цену (Top of Book)"""
        book = self.bids if side == "Buy" else self.asks
        if not book:
            return 0.0
        return max(book.keys()) if side == "Buy" else min(book.keys())

    def get_background_volume(self) -> float:
        """
        Рассчитывает среднюю ликвидность на уровнях 2-10 (исключая Best Bid/Ask).
        Это нужно, чтобы стена на 1-м уровне не искажала статистику.
        """
        if not self.bids or not self.asks:
            return 0.0

        # Сортируем: Биды по убыванию, Аски по возрастанию
        sorted_bids = sorted(self.bids.keys(), reverse=True)
        sorted_asks = sorted(self.asks.keys())

        # Берем срез [1:10] (со второго по десятый)
        bg_bids_keys = sorted_bids[1:11] 
        bg_asks_keys = sorted_asks[1:11]
        
        volumes = []
        for p in bg_bids_keys: volumes.append(self.bids[p])
        for p in bg_asks_keys: volumes.append(self.asks[p])
        
        if not volumes:
            return 0.0
            
        return sum(volumes) / len(volumes)