# hft_strategy/infrastructure/local_order_book.py
import time
import logging
from typing import Dict, Any

logger = logging.getLogger("LOB")

class LocalOrderBook:
    """
    Единая реализация локального стакана (Single Source of Truth).
    Поддерживает обновление через Python-объекты (HTTP/WS) и через C++ Snapshots.
    Соблюдает принцип SRP: только хранение и обновление состояния стакана.
    """
    def __init__(self):
        # Храним как Dict[float, float] для доступа O(1)
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_ts = 0

    def _to_key(self, price: float) -> float:
        """
        Нормализация ключа для исправления ошибок float.
        Критически важно для корректного удаления уровней (del bids[price]).
        """
        return round(price, 8)

    def apply_update(self, event: Any):
        """
        Применяет обновление (Snapshot или Delta) из Python-структур (например, из бэктеста или REST).
        """
        # Duck typing: проверяем атрибут is_snapshot
        if getattr(event, 'is_snapshot', False):
            self.bids.clear()
            self.asks.clear()

        # Обновляем Bids
        for level in event.bids:
            # Поддержка разных форматов: объект .price или tuple (price, qty)
            if hasattr(level, 'price'):
                p, q = level.price, level.quantity
            else:
                p, q = level[0], level[1]
            
            key = self._to_key(p)
            if q == 0:
                if key in self.bids: del self.bids[key]
            else:
                self.bids[key] = q

        # Обновляем Asks
        for level in event.asks:
            if hasattr(level, 'price'):
                p, q = level.price, level.quantity
            else:
                p, q = level[0], level[1]

            key = self._to_key(p)
            if q == 0:
                if key in self.asks: del self.asks[key]
            else:
                self.asks[key] = q
        
        self.last_ts = getattr(event, 'timestamp', time.time())

    def apply_snapshot(self, snapshot: Any):
        """
        Метод для быстрого наложения C++ снепшота (OrderBookSnapshot).
        Используется в Live-торговле.
        """
        # В C++ снепшоте всегда приходит полный стакан -> очищаем старый
        self.bids.clear()
        self.asks.clear()
        
        try:
            # Ожидаем структуру C++: vector<PriceLevel> с полями price, qty
            for item in snapshot.bids:
                p = getattr(item, 'price', 0.0)
                q = getattr(item, 'qty', 0.0) 
                self.bids[self._to_key(p)] = q
                
            for item in snapshot.asks:
                p = getattr(item, 'price', 0.0)
                q = getattr(item, 'qty', 0.0)
                self.asks[self._to_key(p)] = q
                
            self.last_ts = getattr(snapshot, 'local_timestamp', time.time())
        except Exception as e:
            logger.error(f"LOB Snapshot Error: {e}")

    def get_volume(self, side: str, price: float) -> float:
        """Безопасное получение объема по цене"""
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
        Рассчитывает среднюю ликвидность на уровнях 2-10 (Smart Scanner Logic).
        Исключает спред, чтобы не реагировать на манипуляции маркет-мейкеров на 1-м уровне.
        """
        if not self.bids or not self.asks:
            return 0.0

        sorted_bids = sorted(self.bids.keys(), reverse=True)
        sorted_asks = sorted(self.asks.keys())

        # Берем срез [1:11] -> уровни со 2-го по 11-й
        bg_bids_keys = sorted_bids[1:11] 
        bg_asks_keys = sorted_asks[1:11]
        
        volumes = []
        for p in bg_bids_keys: volumes.append(self.bids[p])
        for p in bg_asks_keys: volumes.append(self.asks[p])
        
        if not volumes:
            return 0.0
            
        return sum(volumes) / len(volumes)