# hft_strategy/inspect_header.py
import numpy as np
import os

FILE = "data/parts/part_000.npz"

def inspect():
    print(f"🕵️ INSPECTING: {FILE}")
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    try:
        data = np.load(FILE)['data']
    except Exception as e:
        print(f"❌ Load Error: {e}")
        return

    print(f"   Total rows: {len(data)}")
    
    if len(data) == 0:
        print("❌ Data is empty!")
        return

    print("\n🔍 FIRST 5 ROWS (Header Check):")
    print(f"   {'idx':<4} | {'Local TS (ns)':<20} | {'Price':<10} | {'EV (int)':<10} | {'EV (binary)'}")
    print("-" * 80)
    
    # Выводим первые 5 строк
    for i in range(min(5, len(data))):
        row = data[i]
        ev = int(row['ev'])
        ts = int(row['local_ts'])
        px = row['px']
        
        # Бинарное представление флагов
        bin_ev = bin(ev)
        print(f"   {i:<4} | {ts:<20} | {px:<10.2f} | {ev:<10} | {bin_ev}")

    print("-" * 80)
    
    # Проверка памяти
    print(f"🧠 C_CONTIGUOUS: {data.flags['C_CONTIGUOUS']}")
    
    # Проверка времени
    t0 = data[0]['local_ts']
    t1 = data[1]['local_ts']
    if t0 == 0:
        print("⚠️ WARNING: First timestamp is 0!")
    if t1 < t0:
        print("❌ CRITICAL: Time travel detected (Row 1 < Row 0)!")
    else:
        print("✅ Time seems monotonic initially.")

if __name__ == "__main__":
    inspect()