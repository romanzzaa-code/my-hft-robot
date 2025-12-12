# hft_strategy/convert_to_npy.py
import numpy as np
import os

# Вход: сжатый архив (который мы уже вылечили санитаром)
INPUT_FILE = "data/SOLUSDT_clean.npz" 
# Если clean нет, возьмет v2
if not os.path.exists(INPUT_FILE):
    INPUT_FILE = "data/SOLUSDT_v2.npz"

# Выход: сырой бинарник
OUTPUT_FILE = "data/SOLUSDT.npy"

def convert():
    print(f"📦 Loading compressed {INPUT_FILE}...")
    try:
        data = np.load(INPUT_FILE)['data']
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    print(f"💾 Saving uncompressed to {OUTPUT_FILE}...")
    # Сохраняем как обычный NPY (не сжатый!)
    np.save(OUTPUT_FILE, data)
    
    print("✅ Done. Now we can use Memory Mapping.")

if __name__ == "__main__":
    convert()