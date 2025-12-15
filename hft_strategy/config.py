# hft_strategy/config.py
import os
from dataclasses import dataclass

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
    # Bybit Mainnet: wss://stream.bybit.com/v5/public/linear
    # Bybit Testnet: wss://stream-testnet.bybit.com/v5/public/linear
    ws_url: str = "wss://stream.bybit.com/v5/public/linear"

# --- SINGLE SOURCE OF TRUTH ---
# В идеале брать из os.getenv(), но для начала соберем хардкод здесь.

DB_CONFIG = DatabaseConfig(
    user=os.getenv("HFT_DB_USER", "hft_user"),
    password=os.getenv("HFT_DB_PASSWORD", "password"),
    database=os.getenv("HFT_DB_NAME", "hft_data"),
    host=os.getenv("HFT_DB_HOST", "localhost")
)

TRADING_CONFIG = TradingConfig(
    symbol="SOLUSDT",
    ws_url="wss://stream.bybit.com/v5/public/linear"
)