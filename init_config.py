# init_config.py
import json
import os

CONFIG_DIR = "config"
FILE_PATH = os.path.join(CONFIG_DIR, "strategy_params.json")

DEFAULT_SETTINGS = {
    "comment": "HFT Bot Configuration File. Edited by Telegram Commander.",
    "target_coins": ["ARCUSDT", "RAVEUSDT", "HMSTRUSDT", "LIGHTUSDT", "JELLYJELLYUSDT", "BEATUSDT"],
    "investment_usdt": 20.0,
    "wall_ratio_threshold": 25.0,
    "min_wall_value_usdt": 50000.0,
    "vol_ema_alpha": 0.018955904607758676
}

def init():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        print(f"📁 Created directory: {CONFIG_DIR}")

    if not os.path.exists(FILE_PATH):
        with open(FILE_PATH, 'w') as f:
            json.dump(DEFAULT_SETTINGS, f, indent=4)
        print(f"✅ Created default config: {FILE_PATH}")
    else:
        print(f"⚠️ Config already exists at {FILE_PATH}, skipping overwrite.")

if __name__ == "__main__":
    init()