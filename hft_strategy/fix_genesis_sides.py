# hft_strategy/fix_genesis_sides.py
import numpy as np
import os

FILE = "data/parts/part_000.npz"

def fix_sides():
    print(f"🔧 FIXING MISSING SIDES in {FILE}...")
    
    data = np.load(FILE)['data']
    data = np.array(data, copy=True)
    
    # --- ДИАГНОСТИКА ДО ---
    ev0 = int(data[0]['ev'])
    ev1 = int(data[1]['ev'])
    print(f"   [BEFORE] Row 0 EV: {bin(ev0)} (Ends in 100? No Side!)")
    print(f"   [BEFORE] Row 1 EV: {bin(ev1)}")

    # --- ПАТЧ ---
    # Бит 0 = BUY (1)
    # Бит 1 = SELL (2)
    # Мы просто добавляем их через OR
    
    # Row 0: Делаем BID (добавляем 1)
    # Проверяем, если бит 0 не стоит, ставим его
    if not (ev0 & 1):
        data[0]['ev'] = ev0 | 1 
        print("   -> Row 0: Marked as BUY")

    # Row 1: Делаем ASK (добавляем 2)
    if not (ev1 & 2):
        data[1]['ev'] = ev1 | 2
        print("   -> Row 1: Marked as SELL")
        
    # --- ДИАГНОСТИКА ПОСЛЕ ---
    print(f"   [AFTER]  Row 0 EV: {bin(data[0]['ev'])} (Should end in 101)")
    print(f"   [AFTER]  Row 1 EV: {bin(data[1]['ev'])} (Should end in 110)")

    # Сохраняем
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("✅ SIDES FIXED. Engine should now see Bids and Asks.")

if __name__ == "__main__":
    fix_sides()