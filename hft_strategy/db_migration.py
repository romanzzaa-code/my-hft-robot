import psycopg2
import logging
import sys

# Настройки подключения (как в docker-compose.yml)
DB_CONFIG = {
    "dbname": "hft_data",
    "user": "hft_user",
    "password": "password",
    "host": "localhost",
    "port": "5432"
}

# SQL-схема
# hft_strategy/db_migration.py

# ... (импорты и конфиг те же)

INIT_SQL = """
-- 1. Создаем таблицу с учетом HFT специфики
CREATE TABLE IF NOT EXISTS market_ticks (
    time            TIMESTAMPTZ NOT NULL, -- Local arrival time (Partition Key)
    exch_time       TIMESTAMPTZ NOT NULL, -- Exchange matching engine time
    symbol          TEXT NOT NULL,
    price           DOUBLE PRECISION NULL,
    volume          DOUBLE PRECISION NULL,
    is_buyer_maker  BOOLEAN NULL
);

-- 2. Гипертаблица
SELECT create_hypertable('market_ticks', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

-- 3. Индексы
CREATE INDEX IF NOT EXISTS idx_market_ticks_symbol_time ON market_ticks (symbol, time DESC);
-- Полезный индекс для анализа задержек
CREATE INDEX IF NOT EXISTS idx_market_ticks_exch_time ON market_ticks (exch_time DESC);

-- 4. Сжатие
ALTER TABLE market_ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC' -- Сортировка внутри чанка
);
SELECT add_compression_policy('market_ticks', INTERVAL '3 days', if_not_exists => TRUE);
"""

def run_migration():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("DB_MIGRATION")
    
    try:
        logger.info("Connecting to TimescaleDB...")
        # Устанавливаем соединение
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True # Важно для DDL операций
        
        with conn.cursor() as cur:
            logger.info("Executing SQL schema...")
            cur.execute(INIT_SQL)
            logger.info("✅ Migration successful! Table 'market_ticks' ready.")
            
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        logger.error("Make sure Docker container is running: 'docker-compose up -d'")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()