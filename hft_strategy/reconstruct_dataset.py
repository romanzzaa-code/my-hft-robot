# hft_strategy/reconstruct_dataset.py
import numpy as np
import os
import sys

INPUT_FILE = "data/SOLUSDT_clean.npz"
if not os.path.exists(INPUT_FILE):
    INPUT_FILE = "data/SOLUSDT_v2.npz"

OUTPUT_FILE = "data/SOLUSDT_reconstructed.npz"

def reconstruct():
    print(f"📦 Loading source: {INPUT_FILE}...")
    try:
        raw_data = np.load(INPUT_FILE)['data']
    except Exception as e:
        print(f"❌ Load failed: {e}")
        return

    print(f"   Source shape: {raw_data.shape}")
    print(f"   Source flags: {raw_data.flags}")

    # ОПРЕДЕЛЯЕМ ЖЕСТКУЮ СТРУКТУРУ ДЛЯ RUST
    # Это эталон, который ожидает hftbacktest
    rust_dtype = np.dtype([
        ('ev', 'uint64'),
        ('exch_ts', 'int64'),
        ('local_ts', 'int64'),
        ('px', 'float64'),
        ('qty', 'float64'),
        ('order_id', 'uint64'),
        ('ival', 'int64'),
        ('fval', 'float64')
    ])

    print("\n🔨 Rebuilding array from scratch (forcing memory layout)...")
    
    # 1. Создаем пустой массив нужного размера
    new_data = np.empty(len(raw_data), dtype=rust_dtype)
    
    # 2. Копируем поля явно (это убьет любые скрытые связи с старой памятью)
    # Используем имена полей, чтобы не зависеть от порядка
    for name in rust_dtype.names:
        print(f"   Copying field: {name}...")
        new_data[name] = raw_data[name]

    # 3. Принудительное выравнивание
    final_data = np.ascontiguousarray(new_data)
    
    print("\n🔍 Final Inspection (First Row):")
    print(final_data[0])
    
    # Важная проверка: Таймстемпы не должны быть 0 (кроме теста)
    if final_data[0]['local_ts'] == 0:
         print("⚠️ WARNING: First timestamp is 0!")

    print(f"\n💾 Saving to {OUTPUT_FILE}...")
    np.savez_compressed(OUTPUT_FILE, data=final_data)
    print("✅ RECONSTRUCTION COMPLETE.")

if __name__ == "__main__":
    reconstruct()