# hft_strategy/domain/strategy_config.py
from dataclasses import dataclass
from typing import Dict

@dataclass
class StrategyParameters:
    symbol: str
    tick_size: float          
    lot_size: float           
    
    # ПАРАМЕТРЫ СТРАТЕГИИ (OPTIMIZED)
    wall_vol_threshold: float  # Было ratio, теперь это абсолютный объем (105.0)
    
    entry_delta_ticks: int = 1     
    stop_loss_ticks: int = 36      # OPTIMIZED
    take_profit_ticks: int = 5     # OPTIMIZED
    
    order_qty: float = 0.1         

# База знаний
KNOWN_CONFIGS: Dict[str, StrategyParameters] = {
    "SOLUSDT": StrategyParameters(
        symbol="SOLUSDT",
        tick_size=0.01,
        lot_size=0.1,
        # Результаты Optuna:
        wall_vol_threshold=105.0, 
        stop_loss_ticks=36,       
        take_profit_ticks=5,      
        order_qty=1.0 # 1 SOL для теста
    ),
}

def get_config(symbol: str) -> StrategyParameters:
    symbol = symbol.upper()
    cfg = KNOWN_CONFIGS.get(symbol)
    if not cfg:
        # Fallback на случай, если конфига нет (чтобы не падало)
        return KNOWN_CONFIGS["SOLUSDT"]
    return cfg