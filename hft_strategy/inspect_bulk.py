# hft_strategy/inspect_bulk.py
import numpy as np
import os

FILE = "data/parts/part_000.npz"

def check():
    print(f"🕵️ BULK INSPECTION: {FILE}")
    data = np.load(FILE)['data']
    
    # Смотрим строки с 1000 по 1005
    print("\n🔍 ROWS 1000-1005 (The Silent Killers):")
    print(f"   {'idx':<6} | {'Price':<10} | {'EV (bin)'}")
    print("-" * 50)
    
    for i in range(1000, 1005):
        row = data[i]
        px = row['px']
        ev = row['ev']
        print(f"   {i:<6} | {px:<10.2f} | {bin(ev)}")

    # Считаем нули во всем файле
    zeros = np.count_nonzero(data['px'] < 0.01)
    print(f"\n☢️ TOTAL ROWS WITH ZERO PRICE: {zeros}")
    if zeros > 0:
        print("   ☝️ This is why your backtest shows 0.0. These rows overwrite the book.")

if __name__ == "__main__":
    check()