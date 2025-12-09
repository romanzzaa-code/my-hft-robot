# hft_strategy/db_migration.py
import psycopg2
import logging
import sys

from config import DB_CONFIG

INIT_SQL = """
-- 1. Таблица сделок (существует)
CREATE TABLE IF NOT EXISTS market_ticks (
    time            TIMESTAMPTZ NOT NULL,
    exch_time       TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    price           DOUBLE PRECISION NULL,
    volume          DOUBLE PRECISION NULL,
    is_buyer_maker  BOOLEAN NULL
);

-- 2. [NEW] Таблица снимков стакана
-- Храним bids/asks как JSONB массивы [[price, qty], ...], это экономит место и IOPS
CREATE TABLE IF NOT EXISTS market_depth_snapshots (
    time            TIMESTAMPTZ NOT NULL, -- Local time
    exch_time       TIMESTAMPTZ NOT NULL, -- Exchange time
    symbol          TEXT NOT NULL,
    bids            JSONB, -- Array of [price, qty]
    asks            JSONB, -- Array of [price, qty]
    is_snapshot     BOOLEAN DEFAULT TRUE
);

-- 3. Превращаем в гипертаблицы
SELECT create_hypertable('market_ticks', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');
SELECT create_hypertable('market_depth_snapshots', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

-- 4. Индексы
CREATE INDEX IF NOT EXISTS idx_market_ticks_symbol_time ON market_ticks (symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_depth_symbol_time ON market_depth_snapshots (symbol, time DESC);

-- 5. Сжатие (Опционально, но полезно для HFT)
ALTER TABLE market_ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
-- Для JSONB сжатие TimescaleDB работает отлично
ALTER TABLE market_depth_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);

-- Политики сжатия (через 3 дня данные сжимаются)
SELECT add_compression_policy('market_ticks', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_compression_policy('market_depth_snapshots', INTERVAL '3 days', if_not_exists => TRUE);
"""

def run_migration():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("DB_MIGRATION")
    
    try:
        logger.info("Connecting to TimescaleDB...")
        conn = psycopg2.connect(**DB_CONFIG.as_dict())
        conn.autocommit = True
        
        with conn.cursor() as cur:
            logger.info("Executing SQL schema...")
            cur.execute(INIT_SQL)
            logger.info("✅ Migration successful! Tables ready.")
            
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()