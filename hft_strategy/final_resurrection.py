# hft_strategy/final_resurrection.py
import numpy as np
import os
import sys

# Пытаемся импортировать, чтобы посмотреть правде в глаза
try:
    from hftbacktest import (
        EXCH_EVENT, LOCAL_EVENT,
        DEPTH_EVENT, DEPTH_SNAPSHOT_EVENT, DEPTH_CLEAR_EVENT,
        BUY_EVENT, SELL_EVENT
    )
    print("📚 Library Constants Loaded:")
    print(f"   DEPTH={DEPTH_EVENT}, SELL={SELL_EVENT}, CLEAR={DEPTH_CLEAR_EVENT}")
except ImportError:
    print("⚠️ Library not found. Using safe defaults.")
    # Безопасные дефолты для V2
    EXCH_EVENT = 1 << 31
    LOCAL_EVENT = 1 << 30
    DEPTH_EVENT = 1
    BUY_EVENT = 0 # Будем полагаться на знак
    SELL_EVENT = 0 
    DEPTH_SNAPSHOT_EVENT = 4

FILE = "data/parts/part_000.npz"

def resurrect():
    print(f"🕯️ FINAL RESURRECTION on {FILE}...")
    
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    data = np.load(FILE)['data']
    data = np.array(data, copy=True)
    
    # 1. Медиана для разделения сторон
    valid_px = data['px'][data['px'] > 10.0]
    if len(valid_px) == 0:
        print("❌ No valid prices.")
        return
    median = np.median(valid_px)
    print(f"   🎯 Median Price: {median:.2f}")

    # 2. Очистка флагов
    # Оставляем только EXCH | LOCAL. Сбрасываем все младшие биты.
    # Маска 0xFFFFFFFF00000000 сохраняет старшие 32 бита (где сидят EXCH/LOCAL)
    high_bits_mask = 0xFFFFFFFF00000000
    
    # Если в файле старшие биты потеряны, восстановим их вручную
    # (Примерно как мы видели: 3221225472)
    base_flags = EXCH_EVENT | LOCAL_EVENT
    
    # 3. НОВАЯ СТРАТЕГИЯ: Qty Sign + Pure Depth Flag
    # Мы ставим всем событиям просто DEPTH_EVENT (1), избегая комбинации с 2.
    # Сторону кодируем знаком объема:
    # Bid: Qty > 0
    # Ask: Qty < 0
    
    print("   🔧 Applying: Event=DEPTH(1), Side encoded in Qty Sign...")

    # Разделяем
    is_bid = data['px'] < median
    is_ask = data['px'] >= median

    # Применяем флаги
    # Всем ставим просто DEPTH (1) + BASE
    data['ev'] = base_flags | 1 # DEPTH_EVENT
    
    # Применяем знаки объема
    # Bids -> Positive
    data['qty'][is_bid] = np.abs(data['qty'][is_bid])
    
    # Asks -> Negative
    data['qty'][is_ask] = -np.abs(data['qty'][is_ask])

    # 4. GENESIS (Head transplant)
    # Первые две строки делаем SNAPSHOT (4), чтобы инициализировать движок.
    # Здесь безопасно использовать флаги сторон, так как 4 | 2 = 6 (не 3).
    print("   💉 Injecting Genesis Snapshots...")
    
    # Row 0: Snapshot Bid
    data[0]['px'] = median - 0.01
    data[0]['qty'] = 1.0
    data[0]['ev'] = base_flags | 4 | 1 # Snap(4) | Buy(1) = 5
    
    # Row 1: Snapshot Ask
    data[1]['px'] = median + 0.01
    data[1]['qty'] = -1.0
    data[1]['ev'] = base_flags | 4 | 2 # Snap(4) | Sell(2) = 6

    # 5. Сохранение
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("✅ SAVED. Collision avoided. Run backtest.")

if __name__ == "__main__":
    resurrect()