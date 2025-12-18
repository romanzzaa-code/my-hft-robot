# hft_strategy/config.py
import os
from dataclasses import dataclass
from typing import List

# ==========================================
# 🎛️ ПАНЕЛЬ УПРАВЛЕНИЯ
# ==========================================

# 1. Список монет для торговли
TARGET_COINS = ["ALCHUSDT", "STRKUSDT", "HMSTRUSDT", "RIVERUSDT"]

# 2. Размер ордера в $ (на каждую монету)
INVESTMENT_USDT = 20.0   

# ==========================================
# ⚙️ СИСТЕМНЫЕ НАСТРОЙКИ
# ==========================================

@dataclass
class DatabaseConfig:
    user: str
    password: str
    database: str
    host: str = "localhost"
    port: str = "5432"

    def as_dict(self):
        return {
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "host": self.host,
            "port": self.port
        }

@dataclass
class TradingConfig:
    # Символ здесь больше не важен, так как мы берем список TARGET_COINS
    # Но оставим поле, чтобы не ломать старый код, если он где-то используется
    symbol: str 
    ws_url: str = "wss://stream.bybit.com/v5/public/linear"

# Автоматическая сборка конфигов
DB_CONFIG = DatabaseConfig(
    user=os.getenv("HFT_DB_USER", "hft_user"),
    password=os.getenv("HFT_DB_PASSWORD", "password"),
    database=os.getenv("HFT_DB_NAME", "hft_data"),
    host=os.getenv("HFT_DB_HOST", "localhost")
)

TRADING_CONFIG = TradingConfig(
    # Берем первую монету как дефолтную, чтобы инициализация не падала
    symbol=TARGET_COINS[0] if TARGET_COINS else "BTCUSDT"
)