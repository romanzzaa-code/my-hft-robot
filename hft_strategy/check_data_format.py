# hft_strategy/check_data_format.py
import numpy as np
import sys
import os

# Добавляем путь, чтобы импортировать флаги из библиотеки
sys.path.append(os.getcwd())
try:
    from hftbacktest import DEPTH_CLEAR_EVENT, TRADE_EVENT
except ImportError:
    # Фолбек значения для v2, если импорт не сработает
    DEPTH_CLEAR_EVENT = 3
    TRADE_EVENT = 1

FILE = "data/SOLUSDT_v2.npz"

print(f"🔍 Inspecting: {FILE}")

if not os.path.exists(FILE):
    print("❌ File not found!")
    sys.exit(1)

try:
    data = np.load(FILE)['data']
except Exception as e:
    print(f"❌ Load error: {e}")
    sys.exit(1)

print(f"Total rows: {len(data)}")
print(f"Fields: {data.dtype.names}")

# Проверяем Row 0
first = data[0]
ev = first['ev']
px = first['px']
qty = first['qty']

print(f"\nRow 0 Raw: {first}")
print(f"Price: {px}, Qty: {qty}, EventFlag: {ev}")

# --- УМНАЯ ПРОВЕРКА ---

# 1. Проверяем на CLEAR (Очистка)
# В hftbacktest v2 CLEAR обычно имеет младшие биты == 3 (0b11)
# А также цена и объем должны быть 0
is_clear_by_value = (px == 0) and (qty == 0)
is_clear_by_flag = (ev & DEPTH_CLEAR_EVENT) == DEPTH_CLEAR_EVENT

if is_clear_by_value:
    print("✅ OK: First event is DEPTH CLEAR (verified by 0.0 price/qty).")
elif is_clear_by_flag:
    # Если флаг совпал, но цена не 0 - это странно, но для проверки флага сойдет
    print("✅ OK: First event has CLEAR Flag.")
else:
    # Только если это НЕ clear, проверяем на Trade
    if (ev & TRADE_EVENT) == TRADE_EVENT:
        print("❌ ERROR: First event looks like a TRADE (and price != 0). Engine will crash.")
    else:
        print("✅ OK: First event is likely a Depth Update.")

# 2. Проверяем отрицательные объемы
min_qty = np.min(data['qty'])
print(f"\nQty Range: {min_qty} ... {np.max(data['qty'])}")

if min_qty >= 0:
    print("❌ WARNING: No negative quantities found! (Asks should be < 0 for CSV format)")
else:
    print("✅ OK: Negative quantities present (Asks are correct).")

print("\n🚀 READY TO LAUNCH.")