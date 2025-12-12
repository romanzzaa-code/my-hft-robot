# hft_strategy/fix_flags_critical.py
import numpy as np
import glob
import os
import sys

# Импортируем маски из библиотеки
try:
    from hftbacktest import (
        EXCH_EVENT, LOCAL_EVENT, 
        DEPTH_SNAPSHOT_EVENT, DEPTH_EVENT,
        BUY_EVENT, SELL_EVENT
    )
except ImportError:
    print("❌ Critical: hftbacktest not installed or flags missing.")
    sys.exit(1)

PARTS_DIR = "data/parts"

def fix_all_parts():
    files = sorted(glob.glob(f"{PARTS_DIR}/*.npz"))
    if not files:
        print(f"❌ No files found in {PARTS_DIR}")
        return

    print(f"🚑 Starting CRITICAL FLAG REPAIR on {len(files)} files...")
    print(f"   Target Flags to Add: EXCH ({EXCH_EVENT}) | LOCAL ({LOCAL_EVENT})")

    for i, fpath in enumerate(files):
        print(f"   🔧 Patching {os.path.basename(fpath)}...", end=" ")
        
        try:
            # 1. Загрузка
            data = np.load(fpath)['data']
            data = np.array(data, copy=True) # Делаем mutable копию
            
            # 2. Добавляем EXCH_EVENT и LOCAL_EVENT ко ВСЕМ строкам
            # Это делает события "видимыми" для движка
            # И спользуем побитовое ИЛИ
            data['ev'] = data['ev'] | EXCH_EVENT | LOCAL_EVENT
            
            # 3. СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ ПЕРВОГО ФАЙЛА (Инициализация)
            if i == 0:
                print("[INIT SNAPSHOT]", end=" ")
                # Находим события первого таймстемпа и превращаем их в SNAPSHOT
                start_ts = data[0]['local_ts']
                count = 0
                for r in range(len(data)):
                    if data[r]['local_ts'] > start_ts + 1000: # Ушли дальше 1 мкс
                        break
                    
                    # Меняем DEPTH_EVENT (или CLEAR) на DEPTH_SNAPSHOT_EVENT
                    # Но сохраняем сторону (BUY/SELL) и флаги источника
                    old_ev = data[r]['ev']
                    
                    # Сбрасываем старые типы событий (очищаем биты 0-7, грубо говоря)
                    # Но лучше просто пересобрать
                    
                    base_flags = EXCH_EVENT | LOCAL_EVENT | DEPTH_SNAPSHOT_EVENT
                    
                    if (old_ev & BUY_EVENT):
                        data[r]['ev'] = base_flags | BUY_EVENT
                    elif (old_ev & SELL_EVENT):
                        data[r]['ev'] = base_flags | SELL_EVENT
                    else:
                        # Если это Clear или что-то еще, всё равно помечаем как часть снапшота
                         data[r]['ev'] = base_flags
                    
                    count += 1
                
            # 4. Сохранение (обязательно contiguous)
            final_data = np.ascontiguousarray(data)
            np.savez_compressed(fpath, data=final_data)
            print("✅ OK")

        except Exception as e:
            print(f"❌ FAIL: {e}")

    print("\n🎉 All parts patched. Now the engine should see the data.")

if __name__ == "__main__":
    fix_all_parts()