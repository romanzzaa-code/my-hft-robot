import sys
import os
import time
import json

# --- МАГИЯ ПУТЕЙ (Оставляем как было, чтобы скрипт нашел библиотеку) ---
current_script_dir = os.path.dirname(os.path.abspath(__file__))

project_root = os.path.dirname(current_script_dir)

possible_paths = [
    os.path.join(project_root, "hft_core", "build", "Release"),
    os.path.join(project_root, "build", "Release"),
    os.path.join(project_root, "hft_core", "build", "Debug"),
]

found = False
for p in possible_paths:
    if os.path.exists(p):
        sys.path.insert(0, p)
        print(f"✅ Найден модуль в: {p}")
        found = True
        break

if not found:
    print("❌ Билд не найден! Проверь пути.")
    sys.exit(1)

try:
    import hft_core
    print(f"📦 Библиотека загружена: {hft_core.__file__}")
except ImportError as e:
    print(f"💀 Ошибка импорта: {e}")
    sys.exit(1)

# --- ЛОГИКА ТЕСТА ---

def on_tick(tick):
    # Теперь мы получаем чистые данные!
    print(f"📈 TICK | {tick.symbol} | P: {tick.price:.2f} | V: {tick.volume:.4f} | TS: {tick.timestamp}")

def main():
    print("\n--- 🏗️ СБОРКА КОМПОНЕНТОВ (CLEAN ARCHITECTURE) ---")
    
    # 1. Создаем стратегию парсинга (наш новый "картридж")
    try:
        parser = hft_core.BybitParser()
        print("✅ Парсер Bybit создан успешно")
    except AttributeError:
        print("❌ ОШИБКА: Python не видит класс BybitParser. Проверь main.cpp!")
        return

    # 2. Внедряем зависимость в стример (Dependency Injection)
    # Стример теперь не знает, с какой биржей работает — ему все равно!
    try:
        bot = hft_core.ExchangeStreamer(parser)
        print("✅ Стример инициализирован с парсером")
    except TypeError as e:
        print(f"❌ ОШИБКА КОНСТРУКТОРА: {e}")
        print("Скорее всего, типы аргументов не совпадают (shared_ptr vs unique_ptr)")
        return

    bot.set_callback(on_tick)

    # 3. Подключение (Bybit Public V5)
    url = "wss://stream.bybit.com/v5/public/linear"
    print(f"🔌 Подключение к {url}...")
    
    # Важно: Стример сам запускает поток, но благодаря нашему фиксу
    # он безопасно захватит GIL при вызове on_tick.
    bot.connect(url)
    bot.start()

    # Ждем соединения (в реальном коде лучше использовать callback на onOpen)
    time.sleep(2)

    # 4. Подписка
    sub_msg = {
        "op": "subscribe",
        "args": [
            "publicTrade.BTCUSDT"
        ]
    }
    msg_str = json.dumps(sub_msg)
    print(f"📤 Отправка подписки: {msg_str}")
    bot.send_message(msg_str)

    print("⏳ Слушаем эфир Bybit (нажми Ctrl+C для выхода)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Остановка...")
        bot.stop()
        print("✅ Тест завершен корректно.")

if __name__ == "__main__":
    main()