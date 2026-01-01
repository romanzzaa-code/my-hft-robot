# hft_strategy/domain/strategy_config.py
from dataclasses import dataclass

# --- CONSTANTS (Defaults) ---
# Перенесли константу сюда, чтобы разорвать круг импортов
DEFAULT_INVESTMENT_USDT = 20.0 

@dataclass
class StrategyParameters:
    symbol: str
    # Используем локальную константу
    order_amount_usdt: float = DEFAULT_INVESTMENT_USDT
    tick_size: float = 0.0
    lot_size: float = 0.0
    min_qty: float = 0.0
    
    # --- ЛОГИКА СТЕН ---
    wall_ratio_threshold: float = 2.0
    min_wall_value_usdt: float = 5000.0
    vol_ema_alpha: float = 0.018955904607758676 
    
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
        order_amount_usdt=DEFAULT_INVESTMENT_USDT
    )