# hft_strategy/strategy_config.py
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class StrategyParameters:
    symbol: str
    tick_size: float          # Шаг цены (0.01 для SOL)
    lot_size: float           # Шаг объема (0.1 для SOL)
    
    # --- Логика Стен ---
    # Стена считается "Стеной", если она в K раз больше среднего объема
    wall_ratio_threshold: float 
    
    # --- Управление ордерами (в тиках) ---
    entry_delta_ticks: int = 1     # Встаем на 1 тик ПЕРЕД стеной
    stop_loss_ticks: int = 15      # Стоп в тиках
    take_profit_ticks: int = 30    # Тейк в тиках
    
    order_qty: float = 1.0         # Размер лота для теста

# База знаний (пока ручная, потом будем искать через Optuna)
KNOWN_CONFIGS: Dict[str, StrategyParameters] = {
    "SOLUSDT": StrategyParameters(
        symbol="SOLUSDT",
        tick_size=0.01,
        lot_size=0.1,
        wall_ratio_threshold=15.0, # Для SOL стены должны быть жирными
        stop_loss_ticks=20,        # 0.2$
        take_profit_ticks=40,      # 0.4$
        order_qty=1.0              # 1 SOL
    ),
    # Для примера:
    "BTCUSDT": StrategyParameters(
        symbol="BTCUSDT",
        tick_size=0.1,
        lot_size=0.001,
        wall_ratio_threshold=10.0,
        stop_loss_ticks=50,
        take_profit_ticks=100,
        order_qty=0.01
    )
}

def get_config(symbol: str) -> StrategyParameters:
    symbol = symbol.upper()
    cfg = KNOWN_CONFIGS.get(symbol)
    if not cfg:
        raise ValueError(f"❌ No config found for {symbol}. Add it to strategy_config.py")
    return cfg