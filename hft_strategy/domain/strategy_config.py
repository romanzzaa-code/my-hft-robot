# hft_strategy/domain/strategy_config.py
from dataclasses import dataclass
from typing import Dict

# Импортируем твои настройки из главного конфига
from hft_strategy.config import INVESTMENT_USDT

@dataclass
class StrategyParameters:
    symbol: str
    
    # Деньги берем из глобальной настройки
    order_amount_usdt: float = INVESTMENT_USDT
    
    # Эти поля заполнятся сами при старте (через fetch_instrument_info)
    tick_size: float = 0.0
    lot_size: float = 0.0
    min_qty: float = 0.0
    
    # --- НАСТРОЙКИ "МОЗГА" (ДЕФОЛТНЫЕ ДЛЯ ВСЕХ МОНЕТ) ---
    # Можно вынести и их в config.py, но пока оставим здесь как "заводские настройки"
    
    # Стена = x15 от среднего
    wall_ratio_threshold: float = 15.0
    
    # Фильтр мусора (стена должна стоить хотя бы $50k)
    min_wall_value_usdt: float = 50000.0
    
    # Скорость адаптации (EMA)
    vol_ema_alpha: float = 0.01 
    
    # Риск-менеджмент (в тиках)
    # 1 тик на вход, 15 на прибыль, 30 на стоп
    entry_delta_ticks: int = 1
    take_profit_ticks: int = 15
    stop_loss_ticks: int = 30


# [CHANGED] Больше никаких ручных блоков KNOWN_CONFIGS!
# Функция просто генерирует конфиг для ЛЮБОЙ монеты, которую ты дал.

def get_config(symbol: str) -> StrategyParameters:
    """
    Генерирует стратегию для любой монеты на лету.
    """
    return StrategyParameters(
        symbol=symbol.upper(),
        order_amount_usdt=INVESTMENT_USDT # <--- Берет твои $50 (или сколько ты поставил)
    )