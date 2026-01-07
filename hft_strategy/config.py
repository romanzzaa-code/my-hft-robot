# hft_strategy/config.py
import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Импортируем параметры стратегии
from hft_strategy.domain.strategy_config import StrategyParameters, get_config

# ==========================================
# 🎛️ ПАНЕЛЬ УПРАВЛЕНИЯ (Hardcoded Defaults)
# ==========================================
TARGET_COINS = ["ARCUSDT", "RAVEUSDT", "HMSTRUSDT", "LIGHTUSDT", "JELLYJELLYUSDT", "BEATUSDT"]
INVESTMENT_USDT = 20.0

# ==========================================
# ⚙️ DATACLASSES
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
    private_ws_url: str = "wss://stream.bybit.com/v5/private"

@dataclass
class Config:
    """
    Главный класс конфигурации, который ожидает live_bot.py
    """
    api_key: str
    api_secret: str
    testnet: bool
    symbol: str
    log_level: str
    strategy: StrategyParameters
    
    # Добавляем параметры базы данных для полноты
    db: DatabaseConfig = field(default_factory=lambda: DB_CONFIG)

# ==========================================
# 🔨 FACTORY FUNCTIONS
# ==========================================

def load_config(path: str = None) -> Config:
    """
    Фабрика конфигурации. 
    Аргумент path оставлен для совместимости с live_bot.py, 
    но по факту мы берем данные из ENV и Hardcoded констант.
    """
    
    # 1. Загрузка ключей (Приоритет: ENV -> Hardcode -> Error)
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    
    # Если ключей нет - работаем в Read-Only (или падаем, если это критично)
    if not api_key or not api_secret:
        logging.warning("⚠️ API Keys not found in ENV. Bot might fail in trade execution.")

    # 2. Выбор символа
    # Если передан аргумент в path (например "config.yaml"), можно попробовать распарсить его,
    # но пока просто берем первый символ из списка или дефолт.
    symbol = TARGET_COINS[0] if TARGET_COINS else "BTCUSDT"
    
    # 3. Настройка стратегии
    strategy_params = get_config(symbol)
    # Переопределяем параметры из глобальных настроек
    strategy_params.order_amount_usdt = INVESTMENT_USDT

    return Config(
        api_key=api_key or "",
        api_secret=api_secret or "",
        testnet=False, # Или os.getenv("BYBIT_TESTNET", "False").lower() == "true"
        symbol=symbol,
        log_level="DEBUG",
        strategy=strategy_params
    )

# ==========================================
# 🔌 GLOBAL INSTANCES (Для совместимости)
# ==========================================

DB_CONFIG = DatabaseConfig(
    user=os.getenv("HFT_DB_USER", "hft_user"),
    password=os.getenv("HFT_DB_PASSWORD", "password"),
    database=os.getenv("HFT_DB_NAME", "hft_data"),
    host=os.getenv("HFT_DB_HOST", "localhost")
)

TRADING_CONFIG = TradingConfig(
    symbol=TARGET_COINS[0] if TARGET_COINS else "BTCUSDT"
)