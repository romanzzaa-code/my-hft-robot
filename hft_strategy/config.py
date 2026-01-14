# hft_strategy/config.py
import os
import logging
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Импортируем параметры стратегии
from hft_strategy.domain.strategy_config import StrategyParameters, get_config

# ==========================================
# 🗂️ FILE SYSTEM CONFIG
# ==========================================
# Папка config должна быть примонтирована через Docker Volume
CONFIG_DIR = "config"
SETTINGS_FILE = os.path.join(CONFIG_DIR, "strategy_params.json")

# ==========================================
# 🎛️ ПАНЕЛЬ УПРАВЛЕНИЯ (Hardcoded Defaults - Фолбек)
# ==========================================
DEFAULT_TARGET_COINS = ["ARCUSDT", "RAVEUSDT", "HMSTRUSDT", "LIGHTUSDT", "JELLYJELLYUSDT", "BEATUSDT"]
DEFAULT_INVESTMENT_USDT = 20.0

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
    Главный класс конфигурации.
    """
    api_key: str
    api_secret: str
    testnet: bool
    symbol: str
    log_level: str
    strategy: StrategyParameters
    
    db: DatabaseConfig = field(default_factory=lambda: DB_CONFIG)

# ==========================================
# 🛠️ JSON LOADER LOGIC
# ==========================================

def _load_json_settings() -> Dict[str, Any]:
    """
    Пытается загрузить настройки из JSON файла.
    Если файла нет или он битый — возвращает пустой словарь.
    """
    if not os.path.exists(SETTINGS_FILE):
        return {}
    
    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
            logging.info(f"📂 Config loaded from {SETTINGS_FILE}")
            return data
    except Exception as e:
        logging.error(f"❌ Error reading {SETTINGS_FILE}: {e}. Using defaults.")
        return {}

def _ensure_config_dir():
    """Создает папку config, если её нет"""
    if not os.path.exists(CONFIG_DIR):
        try:
            os.makedirs(CONFIG_DIR)
        except OSError:
            pass # Может быть ошибка прав доступа в Docker, игнорируем

# ==========================================
# 🔨 FACTORY FUNCTIONS
# ==========================================

def load_config(path: str = None) -> Config:
    """
    Фабрика конфигурации. 
    Приоритет: JSON File > ENV > Hardcode
    """
    _ensure_config_dir()
    
    # 1. Загрузка ключей (Приоритет: ENV -> Error)
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    
    if not api_key or not api_secret:
        logging.warning("⚠️ API Keys not found in ENV. Bot running in READ-ONLY mode.")

    # 2. Загрузка JSON настроек
    json_settings = _load_json_settings()
    
    # 3. Определение символа
    # Если в JSON есть список coins, берем первый, иначе дефолт
    target_coins = json_settings.get("target_coins", DEFAULT_TARGET_COINS)
    symbol = target_coins[0] if target_coins else "BTCUSDT"
    
    # 4. Настройка стратегии
    # Создаем объект с дефолтными значениями
    strategy_params = get_config(symbol)
    
    # Переопределяем значениями из JSON, если они там есть
    # Это позволяет менять их через файл без правки кода
    if "investment_usdt" in json_settings:
        strategy_params.order_amount_usdt = float(json_settings["investment_usdt"])
    else:
        strategy_params.order_amount_usdt = DEFAULT_INVESTMENT_USDT

    if "wall_ratio_threshold" in json_settings:
        strategy_params.wall_ratio_threshold = float(json_settings["wall_ratio_threshold"])
        
    if "min_wall_value_usdt" in json_settings:
        strategy_params.min_wall_value_usdt = float(json_settings["min_wall_value_usdt"])
        
    if "vol_ema_alpha" in json_settings:
        strategy_params.vol_ema_alpha = float(json_settings["vol_ema_alpha"])

    logging.info(f"⚙️ Active Strategy Params: WallRatio={strategy_params.wall_ratio_threshold}, "
                 f"Inv=${strategy_params.order_amount_usdt}, MinWall=${strategy_params.min_wall_value_usdt}")

    return Config(
        api_key=api_key,
        api_secret=api_secret,
        testnet=False, 
        symbol=symbol,
        log_level="INFO",
        strategy=strategy_params
    )

# ==========================================
# 🔌 GLOBAL INSTANCES
# ==========================================

DB_CONFIG = DatabaseConfig(
    user=os.getenv("HFT_DB_USER", "hft_user"),
    password=os.getenv("HFT_DB_PASSWORD", "password"),
    database=os.getenv("HFT_DB_NAME", "hft_data"),
    host=os.getenv("HFT_DB_HOST", "timescaledb") # В Docker это имя сервиса
)

# Вызываем один раз для инициализации дефолтов, если кто-то импортирует напрямую
TRADING_CONFIG = TradingConfig(
    symbol="BTCUSDT" # Placeholder
)