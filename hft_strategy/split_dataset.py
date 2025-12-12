# hft_strategy/split_dataset.py
import numpy as np
import os
import glob

INPUT_FILE = "data/SOLUSDT_v2.npz"
OUTPUT_DIR = "data/parts"
CHUNK_SIZE = 1_000_000

def split():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input not found: {INPUT_FILE}")
        return

    # Очистка старых частей
    if os.path.exists(OUTPUT_DIR):
        for f in glob.glob(f"{OUTPUT_DIR}/*.npz"):
            os.remove(f)
    else:
        os.makedirs(OUTPUT_DIR)

    print(f"📦 Loading {INPUT_FILE}...")
    data = np.load(INPUT_FILE)['data']
    total_rows = len(data)
    print(f"   Total rows: {total_rows}")
    
    # Проверка флагов (на всякий случай)
    print(f"   First EV: {data[0]['ev']} (Check if legacy flags present)")

    print(f"🔪 Splitting into chunks of {CHUNK_SIZE}...")
    
    # Нарезка
    for i in range(0, total_rows, CHUNK_SIZE):
        chunk = data[i : i + CHUNK_SIZE]
        # Принудительно выравниваем каждый кусок
        chunk_clean = np.ascontiguousarray(chunk)
        
        part_name = f"{OUTPUT_DIR}/part_{i // CHUNK_SIZE:03d}.npz"
        np.savez_compressed(part_name, data=chunk_clean)
        print(f"   Saved {part_name} ({len(chunk_clean)} rows)")

    print("✅ Done! Parts are ready in data/parts/")

if __name__ == "__main__":
    split()