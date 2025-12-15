# hft_strategy/serializers.py
import orjson
from typing import List, Any

class MarketDataSerializer:
    """
    Отвечает за быстрое преобразование рыночных данных в формат для БД.
    Соблюдает принцип SRP (Single Responsibility Principle).
    """

    @staticmethod
    def serialize_depth(bids: List[Any], asks: List[Any]) -> tuple[str, str]:
        """
        Сериализует биды и аски в JSON-строки, используя orjson.
        Возвращает строки (str), так как asyncpg ожидает str для JSONB по умолчанию,
        либо требует декодирования bytes.
        """
        # Преобразуем структуры C++ (PriceLevel) в списки списков [price, qty]
        # orjson.dumps возвращает bytes, поэтому декодируем в str для asyncpg
        # OPTION_NAIVE_UTC: указывает, что datetime объекты нужно трактовать как UTC
        
        # Быстрая конвертация list comprehension
        bids_data = [[b.price, b.quantity] for b in bids]
        asks_data = [[a.price, a.quantity] for a in asks]
        
        return (
            orjson.dumps(bids_data).decode('utf-8'),
            orjson.dumps(asks_data).decode('utf-8')
        )

    @staticmethod
    def serialize_tick(event) -> tuple:
        """
        Подготавливает тик для вставки (пока простая логика, но теперь она изолирована).
        """
        # Здесь можно добавить логику округления, если нужно
        return (
            event.symbol,
            event.price,
            event.volume
        )