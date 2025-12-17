# hft_strategy/config.py
import os
from dataclasses import dataclass

# ==========================================
# 🎛️ ПАНЕЛЬ УПРАВЛЕНИЯ (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ)
# ==========================================

# 1. Какой монетой торгуем?
TARGET_COIN = "AAVEUSDT" 

# 2. Сколько денег вкладываем в один ордер (в $)?
INVESTMENT_USDT = 30.0   

# ==========================================
# ⚙️ СИСТЕМНЫЕ НАСТРОЙКИ (ЛУЧШЕ НЕ ТРОГАТЬ)
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
    symbol: str
    ws_url: str = "wss://stream.bybit.com/v5/public/linear"

# Автоматическая сборка конфигов на основе твоих настроек выше
DB_CONFIG = DatabaseConfig(
    user=os.getenv("HFT_DB_USER", "hft_user"),
    password=os.getenv("HFT_DB_PASSWORD", "password"),
    database=os.getenv("HFT_DB_NAME", "hft_data"),
    host=os.getenv("HFT_DB_HOST", "localhost")
)

TRADING_CONFIG = TradingConfig(
    symbol=TARGET_COIN # <--- Подхватывает твою монету автоматически
)