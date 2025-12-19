# hft_strategy/domain/strategy_config.py
from dataclasses import dataclass
from hft_strategy.config import INVESTMENT_USDT

@dataclass
class StrategyParameters:
    symbol: str
    order_amount_usdt: float = INVESTMENT_USDT
    tick_size: float = 0.0
    lot_size: float = 0.0
    min_qty: float = 0.0
    
    # --- ЛОГИКА СТЕН ---
    wall_ratio_threshold: float = 5.0
    min_wall_value_usdt: float = 10000.0
    vol_ema_alpha: float = 0.01 
    
    # --- РИСК-МЕНЕДЖМЕНТ ---
    entry_delta_ticks: int = 1
    stop_loss_ticks: int = 30
    
    # [NEW] ДИНАМИЧЕСКИЙ ТЕЙК
    use_dynamic_tp: bool = True     # Включить авто-тейк?
    natr_period: int = 20           # Период ATR (свечи 5 мин)
    tp_natr_multiplier: float = 0.5 # 50% от NATR
    min_tp_percent: float = 0.2     # Пол (не меньше 0.2%)
    
    # Если use_dynamic_tp = False, используется это значение:
    fixed_tp_ticks: int = 15 

def get_config(symbol: str) -> StrategyParameters:
    return StrategyParameters(
        symbol=symbol.upper(),
        order_amount_usdt=INVESTMENT_USDT
    )