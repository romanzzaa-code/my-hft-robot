# hft_strategy/domain/events.py

"""
Domain Layer: Event Constants
Single Source of Truth для типов событий и флагов.
Используется для взаимодействия с hftbacktest и кодирования данных.
"""

import logging

logger = logging.getLogger("DOMAIN")

# Попытка импорта из библиотеки (чтобы быть в синхроне с версией hftbacktest)
try:
    from hftbacktest import (
        DEPTH_EVENT, 
        TRADE_EVENT, 
        DEPTH_CLEAR_EVENT, 
        DEPTH_SNAPSHOT_EVENT,
        BUY_EVENT, 
        SELL_EVENT,
        EXCH_EVENT, 
        LOCAL_EVENT
    )
except ImportError:
    logger.warning("⚠️ hftbacktest not found. Using HARDCODED v2 constants.")
    # Фолбек значения для hftbacktest v2.x (Rust)
    # Старшие биты для источника
    EXCH_EVENT = 1 << 31  # 2147483648
    LOCAL_EVENT = 1 << 30 # 1073741824
    
    # Стороны (обычно 29 и 28 биты в v2, но иногда зависят от реализации)
    BUY_EVENT = 1 << 29
    SELL_EVENT = 1 << 28
    
    # Типы событий (младшие биты)
    DEPTH_EVENT = 1
    TRADE_EVENT = 2
    DEPTH_CLEAR_EVENT = 3
    DEPTH_SNAPSHOT_EVENT = 4

# Маска для системных флагов (чтобы не потерять их при обновлении типа)
SYSTEM_FLAGS = EXCH_EVENT | LOCAL_EVENT

def get_event_name(ev_code: int) -> str:
    """Helper для отладки: расшифровывает флаг в строку"""
    parts = []
    if ev_code & EXCH_EVENT: parts.append("EXCH")
    if ev_code & LOCAL_EVENT: parts.append("LOCAL")
    if ev_code & BUY_EVENT: parts.append("BUY")
    if ev_code & SELL_EVENT: parts.append("SELL")
    
    # Тип (младшие 8 бит)
    type_code = ev_code & 0xFF
    if type_code == DEPTH_EVENT: parts.append("DEPTH")
    elif type_code == TRADE_EVENT: parts.append("TRADE")
    elif type_code == DEPTH_CLEAR_EVENT: parts.append("CLEAR")
    elif type_code == DEPTH_SNAPSHOT_EVENT: parts.append("SNAPSHOT")
    
    return "|".join(parts)