import sys
import os
import time
import json

# --- МАГИЯ ПУТЕЙ (Anti-Shadowing) ---
# Определяем, где мы находимся
current_script_dir = os.path.dirname(os.path.abspath(__file__))

# Список мест, где может прятаться скомпилированный pyd
possible_paths = [
    # Если скрипт в корне d:\ant, а билд в d:\ant\hft_core\build\Release
    os.path.join(current_script_dir, "hft_core", "build", "Release"),
    # Если скрипт в корне, а билд в d:\ant\build\Release
    os.path.join(current_script_dir, "build", "Release"),
    # Debug версии
    os.path.join(current_script_dir, "hft_core", "build", "Debug"),
]

found = False
for p in possible_paths:
    if os.path.exists(p):
        # Вставляем путь ПЕРВЫМ (индекс 0), чтобы перебить локальную папку
        sys.path.insert(0, p)
        print(f"✅ Найден модуль в: {p}")
        found = True
        break

if not found:
    print("❌ Билд не найден! Проверь пути.")
    print(f"Искал здесь: {possible_paths}")
    sys.exit(1)

try:
    import hft_core
    # Проверка: если файл не заканчивается на .pyd (или .so), это ошибка
    if not hft_core.__file__.endswith((".pyd", ".so")):
        print(f"⚠️ ВНИМАНИЕ: Импортирован {hft_core.__file__}")
        raise ImportError("Загружена папка исходников вместо скомпилированной библиотеки!")
except ImportError as e:
    print(f"💀 Ошибка импорта: {e}")
    sys.exit(1)

# --- ЛОГИКА ТЕСТА ---
def on_tick(tick):
    # Выводим тик. Обрати внимание на TS (Timestamp)
    print(f"📈 BYBIT | {tick.symbol} | Price: {tick.price} | Vol: {tick.volume} | TS: {tick.timestamp}")

def main():
    print("Инициализация...")
    try:
        bot = hft_core.ExchangeStreamer()
    except AttributeError:
        print("❌ ОШИБКА: Класс ExchangeStreamer не найден.")
        print("Вероятно, Python импортировал папку hft_core вместо файла .pyd")
        return

    bot.set_callback(on_tick)

    # 1. Подключение (Bybit Public V5)
    url = "wss://stream.bybit.com/v5/public/linear"
    print(f"🔌 Подключение к {url}...")
    bot.connect(url)
    bot.start()

    # Ждем соединения
    time.sleep(2)

    # 2. Подписка (Обязательно для Bybit!)
    sub_msg = {
        "op": "subscribe",
        "args": [
            "publicTrade.BTCUSDT"
        ]
    }
    msg_str = json.dumps(sub_msg)
    print(f"📤 Отправка подписки: {msg_str}")
    
    # !!! Если здесь упадет - значит ты не пересобрал проект с новым методом send_message !!!
    if hasattr(bot, 'send_message'):
        bot.send_message(msg_str)
    else:
        print("❌ ОШИБКА: Метод send_message не найден! Ты забыл нажать F7 (Build) после обновления C++ кода.")
        bot.stop()
        return

    print("⏳ Слушаем эфир Bybit...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Остановка...")
        bot.stop()

if __name__ == "__main__":
    main()