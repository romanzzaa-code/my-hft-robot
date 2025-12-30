# hft_strategy/domain/trade_context.py
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional

class StrategyState(Enum):
    """Состояния машины состояний стратегии"""
    IDLE = auto()          # Поиск входа
    ORDER_PLACED = auto()  # Ордер отправлен, ждем
    IN_POSITION = auto()   # Позиция набрана

@dataclass
class TradeContext:
    """
    Value Object, хранящий контекст текущей активной сделки.
    """
    side: str              # "Buy" or "Sell"
    wall_price: float      # Цена стены, от которой играем
    entry_price: float     # Цена нашего входа
    quantity: float        # Плановый объем (Target), сколько хотели купить
    order_id: str          # ID ордера на вход
    
    # [NEW] Реально исполненный объем (Cumulative Fill). 
    # Заполняется по мере прихода событий execution.
    filled_qty: float = 0.0 
    
    tp_order_id: Optional[str] = None # ID ордера Take Profit
    placed_ts: float = 0.0 # Время выставления (для таймаута)