# hft_strategy/domain/interfaces.py
from typing import Protocol, Optional, List, Dict

class IExecutionHandler(Protocol):
    async def fetch_instrument_info(self, symbol: str) -> tuple[float, float, float]: ...

    async def fetch_ohlc(self, symbol: str, interval: str = "5", limit: int = 20) -> List[Dict]: ...

    # [UPDATED] Добавлен order_link_id
    async def place_limit_maker(
        self, 
        symbol: str, 
        side: str, 
        price: float, 
        qty: float, 
        reduce_only: bool = False,
        order_link_id: Optional[str] = None  # <--- NEW
    ) -> Optional[str]: ...

    # [UPDATED] Добавлен order_link_id
    async def place_market_order(
        self, 
        symbol: str, 
        side: str, 
        qty: float, 
        reduce_only: bool = False,
        order_link_id: Optional[str] = None  # <--- NEW
    ) -> Optional[str]: ...

    async def amend_order(self, symbol: str, order_id: str, qty: float) -> bool: ...

    async def cancel_order(self, symbol: str, order_id: str) -> None: ...

    async def get_position(self, symbol: str) -> float: ...