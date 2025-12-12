# hft_strategy/check_time_range.py
import numpy as np
import sys
import os
from datetime import datetime

FILE = "data/SOLUSDT_v2.npz"

if not os.path.exists(FILE):
    print("❌ File not found")
    sys.exit(1)

print(f"📦 Loading {FILE}...")
data = np.load(FILE)['data']

if len(data) == 0:
    print("❌ Data is empty!")
    sys.exit(1)

ts_start = data[0]['local_ts']
ts_end = data[-1]['local_ts']
duration_ns = ts_end - ts_start
duration_sec = duration_ns / 1_000_000_000.0

print(f"\n📊 Data Statistics:")
print(f"   Rows:      {len(data)}")
print(f"   Start TS:  {ts_start} ({datetime.fromtimestamp(ts_start/1e9)})")
print(f"   End TS:    {ts_end}   ({datetime.fromtimestamp(ts_end/1e9)})")
print(f"   Duration:  {duration_sec:.4f} seconds ({duration_sec/3600:.2f} hours)")

# Проверка на монотонность
diffs = np.diff(data['local_ts'])
min_diff = np.min(diffs)
if min_diff < 0:
    print(f"\n❌ CRITICAL: Time travel detected! Min diff: {min_diff}")
    print("   The engine requires strictly sorted data.")
else:
    print("\n✅ Time monotonicity check passed.")