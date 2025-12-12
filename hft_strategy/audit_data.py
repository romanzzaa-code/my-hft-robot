# hft_strategy/audit_data.py
import asyncio
import asyncpg
import logging
import argparse
import orjson
import sys
import os
from datetime import datetime

# Патч путей, чтобы видеть config
sys.path.append(os.getcwd())
from hft_strategy.config import DB_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("AUDIT")

async def audit_symbol(symbol: str):
    logger.info(f"🔌 Connecting to DB to audit {symbol}...")
    try:
        conn = await asyncpg.connect(**DB_CONFIG.as_dict())
    except Exception as e:
        logger.error(f"DB Connection failed: {e}")
        return

    stats = {
        "symbol": symbol,
        "total_trades": 0,
        "total_snapshots": 0,
        "crossed_books": 0,     # Bid >= Ask (Fatal)
        "neg_latency": 0,       # Local < Exchange (Clock skew)
        "time_gaps": 0,         # Gap > 1s (Packet loss)
        "min_ts": float('inf'),
        "max_ts": 0
    }
    
    last_exch_ts = 0

    try:
        # Используем транзакцию для серверного курсора (снижаем нагрузку на RAM)
        async with conn.transaction():
            
            # --- 1. ПРОВЕРКА СДЕЛОК ---
            logger.info(f"📊 Streaming TRADES for {symbol}...")
            # Читаем только нужные поля
            async for row in conn.cursor(f"""
                SELECT 
                    EXTRACT(EPOCH FROM exch_time)*1000000 as ts, 
                    EXTRACT(EPOCH FROM time)*1000000 as loc_ts 
                FROM market_ticks 
                WHERE symbol = '{symbol}' 
                ORDER BY exch_time ASC
            """):
                stats["total_trades"] += 1
                ts = row['ts']
                loc_ts = row['loc_ts']

                # Границы времени
                if ts < stats["min_ts"]: stats["min_ts"] = ts
                if ts > stats["max_ts"]: stats["max_ts"] = ts

                # Проверка дыр в данных (> 1 секунды нет торгов - подозрительно для BTC)
                if last_exch_ts > 0:
                    delta = ts - last_exch_ts
                    if delta > 1_000_000: # 1 sec
                        stats["time_gaps"] += 1
                    if delta < 0:
                        logger.warning(f"📉 Time Travel detected! Diff: {delta}us at {ts}")
                
                # Проверка локального времени (отрицательная задержка)
                if loc_ts < ts:
                    stats["neg_latency"] += 1
                
                last_exch_ts = ts

            # --- 2. ПРОВЕРКА СТАКАНОВ ---
            logger.info(f"📚 Streaming SNAPSHOTS for {symbol}...")
            async for row in conn.cursor(f"""
                SELECT bids, asks 
                FROM market_depth_snapshots 
                WHERE symbol = '{symbol}'
            """):
                stats["total_snapshots"] += 1
                
                # Быстрая десериализация
                bids_raw = row['bids']
                asks_raw = row['asks']
                
                # Обработка str vs list (зависит от драйвера, orjson ест всё)
                bids = orjson.loads(bids_raw) if isinstance(bids_raw, str) else bids_raw
                asks = orjson.loads(asks_raw) if isinstance(asks_raw, str) else asks_raw
                
                if not bids or not asks:
                    continue

                # Проверка на перекрещивание (Crossed Order Book)
                # Бид не может быть дороже Аска. Если так - это арбитраж или баг парсера.
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
                
                if best_bid >= best_ask:
                    stats["crossed_books"] += 1

    finally:
        await conn.close()

    # --- ОТЧЕТ ---
    duration_sec = (stats["max_ts"] - stats["min_ts"]) / 1_000_000 if stats["max_ts"] > 0 else 0
    
    print("\n" + "="*60)
    print(f"🕵️  AUDIT REPORT: {symbol}")
    print("="*60)
    print(f"⏱  Data Duration:    {duration_sec / 3600:.2f} hours")
    print(f"📈 Total Trades:     {stats['total_trades']}")
    print(f"📸 Total Snapshots:  {stats['total_snapshots']}")
    print("-" * 60)
    print(f"💀 Crossed Books:    {stats['crossed_books']} \t(Must be 0!)")
    print(f"📉 Negative Latency: {stats['neg_latency']} \t(Clock sync issues)")
    print(f"🕳  Large Gaps (>1s): {stats['time_gaps']} \t(Network/Socket issues)")
    print("="*60 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HFT Data Integrity Auditor")
    parser.add_argument("symbol", type=str, help="Trading pair to audit (e.g. BTCUSDT)")
    args = parser.parse_args()

    try:
        # Патч для Windows (если нужно)
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(audit_symbol(args.symbol))
    except KeyboardInterrupt:
        pass