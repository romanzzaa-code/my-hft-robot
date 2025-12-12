# hft_strategy/inspect_genesis.py
import numpy as np
import os

FILE = "data/parts/part_000.npz"

def inspect():
    print(f"🕵️ CHECKING GENESIS in {FILE}...")
    
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    data = np.load(FILE)['data']
    print(f"   Total rows: {len(data)}")

    print("\n🔍 FIRST 5 ROWS (Must NOT be 0.0):")
    print(f"   {'idx':<4} | {'Price':<10} | {'EV (int)':<12} | {'EV (bin)'}")
    print("-" * 60)
    
    for i in range(min(5, len(data))):
        row = data[i]
        px = row['px']
        ev = int(row['ev'])
        bin_ev = bin(ev)
        
        marker = "✅" if px > 0 else "❌ ZERO!"
        print(f"   {i:<4} | {px:<10.2f} | {ev:<12} | {bin_ev} {marker}")

    # Проверка на "скрытые" нули в первых 100 строках
    zeros = np.where(data[:100]['px'] == 0)[0]
    if len(zeros) > 0:
        print(f"\n⚠️ WARNING: Found ZERO prices in first 100 rows at indices: {zeros}")
        print("   The engine reads these and updates the book to 0.0!")
    else:
        print("\n✅ No zero prices in the header.")

if __name__ == "__main__":
    inspect()