# hft_strategy/validate_reconstruction.py
import asyncio
import asyncpg
import logging
import orjson
import sys
import os
from collections import defaultdict

# Патч путей
sys.path.append(os.getcwd())
from hft_strategy.config import DB_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("REPLAY")

class OrderBook:
    def __init__(self):
        self.bids = {}  # price -> qty
        self.asks = {}  # price -> qty
        self.ready = False

    def apply(self, bids_list, asks_list, is_snapshot):
        # 1. Если это Снэпшот - перезаписываем всё
        if is_snapshot:
            self.bids = {float(p): float(q) for p, q in bids_list}
            self.asks = {float(p): float(q) for p, q in asks_list}
            self.ready = True
            return

        # 2. Если это Дельта, но стакана еще нет - пропускаем (ждем снапшота)
        if not self.ready:
            return

        # 3. Применяем дельты (qty=0 -> удаление)
        for p, q in bids_list:
            p, q = float(p), float(q)
            if q == 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = q

        for p, q in asks_list:
            p, q = float(p), float(q)
            if q == 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = q

    def check_integrity(self):
        if not self.ready: return True # Нечего проверять
        if not self.bids or not self.asks: return True # Пустой стакан - бывает

        best_bid = max(self.bids.keys())
        best_ask = min(self.asks.keys())

        if best_bid >= best_ask:
            return False, best_bid, best_ask
        return True, best_bid, best_ask

async def validate_stream(symbol: str):
    conn = await asyncpg.connect(**DB_CONFIG.as_dict())
    logger.info(f"🎞️ Starting L2 Replay for {symbol}...")
    
    book = OrderBook()
    stats = {
        "processed": 0,
        "crossed_errors": 0,
        "first_snapshot_found": False
    }

    try:
        async with conn.transaction():
            # Читаем строго по времени биржи!
            async for row in conn.cursor(f"""
                SELECT bids, asks, is_snapshot, exch_time
                FROM market_depth_snapshots 
                WHERE symbol = '{symbol}'
                ORDER BY exch_time ASC
            """):
                stats["processed"] += 1
                
                # Десериализация
                bids = orjson.loads(row['bids']) if isinstance(row['bids'], str) else row['bids']
                asks = orjson.loads(row['asks']) if isinstance(row['asks'], str) else row['asks']
                is_snap = row['is_snapshot']

                if is_snap:
                    stats["first_snapshot_found"] = True
                
                # Применяем изменения
                book.apply(bids, asks, is_snap)

                # Проверяем целостность ВОССТАНОВЛЕННОГО стакана
                is_valid, bb, ba = book.check_integrity()
                if not is_valid:
                    logger.error(f"❌ CROSSED BOOK at {row['exch_time']}! BestBid: {bb} >= BestAsk: {ba}")
                    stats["crossed_errors"] += 1
                    # Остановимся после первых 10 ошибок, чтобы не спамить
                    if stats["crossed_errors"] > 10:
                        break
                
                if stats["processed"] % 50000 == 0:
                    logger.info(f"   Processed {stats['processed']} events... Current Spread: {ba - bb:.4f}")

    finally:
        await conn.close()

    print("\n" + "="*50)
    print(f"🎞️ REPLAY REPORT: {symbol}")
    print("="*50)
    print(f"Events Processed: {stats['processed']}")
    print(f"Snapshot Found:   {stats['first_snapshot_found']}")
    print(f"Integrity Errors: {stats['crossed_errors']}")
    print("="*50 + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_reconstruction.py SYMBOL")
        sys.exit(1)
        
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(validate_stream(sys.argv[1]))
    except KeyboardInterrupt:
        pass