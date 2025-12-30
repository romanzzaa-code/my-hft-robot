# hft_strategy/domain/interfaces.py
from typing import Protocol, Optional, List, Dict

class IExecutionHandler(Protocol):
    """
    Интерфейс исполнителя.
    [UPDATED] Добавлены reduce_only и amend_order для безопасного управления позицией.
    """
    
    async def fetch_instrument_info(self, symbol: str) -> tuple[float, float, float]:
        ...

    async def fetch_ohlc(self, symbol: str, interval: str = "5", limit: int = 20) -> List[Dict]:
        ...

    # [UPDATE] Добавлен reduce_only
    async def place_limit_maker(
        self, symbol: str, side: str, price: float, qty: float, reduce_only: bool = False
    ) -> Optional[str]:
        ...

    # [UPDATE] Добавлен reduce_only
    async def place_market_order(
        self, symbol: str, side: str, qty: float, reduce_only: bool = False
    ) -> Optional[str]:
        ...

    # [NEW] Метод для изменения активного ордера (например, объема Тейка)
    async def amend_order(self, symbol: str, order_id: str, qty: float) -> bool:
        ...

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        ...

    async def get_position(self, symbol: str) -> float:
        ...