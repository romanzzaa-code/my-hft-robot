from typing import Dict, List, Optional
import logging

class LocalOrderBook:
    """
    Отвечает за поддержание актуального состояния стакана.
    Принимает Snapshots и Deltas, хранит Map: Price -> Quantity.
    """
    def __init__(self):
        # Храним как Dict[float, float] для быстрого доступа O(1)
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_ts = 0

    def apply_update(self, event):
        """
        Применяет обновление (Snapshot или Delta) из C++
        event: OrderBookSnapshot (структура из pybind11)
        """
        # 1. Если это Снэпшот — очищаем старые данные
        if event.is_snapshot:
            self.bids.clear()
            self.asks.clear()

        # 2. Обновляем Bids
        for level in event.bids:
            price = level.price
            qty = level.quantity
            if qty == 0:
                # В дельте 0 означает удаление уровня
                if price in self.bids:
                    del self.bids[price]
            else:
                self.bids[price] = qty

        # 3. Обновляем Asks
        for level in event.asks:
            price = level.price
            qty = level.quantity
            if qty == 0:
                if price in self.asks:
                    del self.asks[price]
            else:
                self.asks[price] = qty
        
        self.last_ts = event.timestamp

    def get_volume(self, side: str, price: float) -> float:
        """Безопасное получение объема по конкретной цене с допуском float"""
        book = self.bids if side == "Buy" else self.asks
        
        # Точное совпадение (для хеш-мапы float - это риск, но в Python работает, если значения идентичны)
        if price in book:
            return book[price]
            
        # Если точного нет, ищем с эпсилоном (чуть медленнее, но надежнее)
        epsilon = 1e-8
        for p, q in book.items():
            if abs(p - price) < epsilon:
                return q
        return 0.0

    def get_best(self, side: str) -> Optional[float]:
        """Возвращает лучшую цену"""
        book = self.bids if side == "Buy" else self.asks
        if not book:
            return None
        return max(book.keys()) if side == "Buy" else min(book.keys())