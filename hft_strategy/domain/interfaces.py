# hft_strategy/domain/interfaces.py
from typing import Protocol, Optional, List, Dict

class IExecutionHandler(Protocol):
    """
    Интерфейс теперь требует явного указания символа для каждой операции.
    """
    
    async def fetch_instrument_info(self, symbol: str) -> tuple[float, float, float]:
        ...

    async def fetch_ohlc(self, symbol: str, interval: str = "5", limit: int = 20) -> List[Dict]:
        ...

    # [FIX] Добавляем symbol: str
    async def place_limit_maker(self, symbol: str, side: str, price: float, qty: float) -> Optional[str]:
        ...

    # [FIX] Добавляем symbol: str
    async def place_market_order(self, symbol: str, side: str, qty: float) -> Optional[str]:
        ...

    # [FIX] Добавляем symbol: str (для отмены тоже важно знать контекст, хотя API Bybit позволяет и без, но для консистентности лучше передать)
    async def cancel_order(self, symbol: str, order_id: str) -> None:
        ...

    # [FIX] Добавляем symbol: str
    async def get_position(self, symbol: str) -> float:
        ...