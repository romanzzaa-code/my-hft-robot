# hft_strategy/fix_all_zeros.py
import numpy as np
import os

FILE = "data/parts/part_000.npz"

def nuke_zeros():
    print(f"☢️ OPERATION: NUKE ZEROS in {FILE}")
    
    data = np.load(FILE)['data']
    data = np.array(data, copy=True)
    
    # 1. Находим нормальную цену-донора
    valid_row_idx = -1
    for i in range(len(data)):
        if data[i]['px'] > 10.0:
            valid_row_idx = i
            break
            
    if valid_row_idx == -1:
        print("❌ CRITICAL: No valid prices found in file!")
        return

    donor_px = data[valid_row_idx]['px']
    donor_ev = data[valid_row_idx]['ev']
    print(f"   🧬 Donor Price: {donor_px} at index {valid_row_idx}")

    # 2. Проходим по первым 1000 строкам и лечим нули
    # (Дальше обычно уже идут нормальные торги)
    count = 0
    for i in range(min(1000, len(data))):
        if data[i]['px'] < 0.0001: # Если цена 0
            # Жестко меняем на донора, но сохраняем время!
            data[i]['px'] = donor_px
            # Флаг тоже лучше взять нормальный, если старый был "Clear=3"
            # Но если это Snapshot, то ок. Просто копируем флаг донора для надежности.
            data[i]['ev'] = donor_ev 
            count += 1
            
    print(f"   🩹 Patched {count} rows with zero prices.")

    # 3. Сохраняем
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("✅ SAVED. Zeros eliminated.")

if __name__ == "__main__":
    nuke_zeros()