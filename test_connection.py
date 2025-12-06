import sys
import os
import time

# --- 1. ПРАВИЛЬНЫЙ ПОИСК ПУТЕЙ ---
# Твой скрипт лежит в D:\ant
current_dir = os.path.dirname(os.path.abspath(__file__))

# Сборка лежит глубже: D:\ant\hft_core\build\Release
# (Проверяем оба варианта: Debug и Release)
possible_paths = [
    os.path.join(current_dir, "hft_core", "build", "Release"),
    os.path.join(current_dir, "hft_core", "build", "Debug"),
    os.path.join(current_dir, "build", "Release"), # Если ты скопировал папку build
]

found_path = None
for p in possible_paths:
    if os.path.exists(p):
        found_path = p
        break

if found_path:
    # !!! КРИТИЧЕСКИ ВАЖНО !!!
    # insert(0, ...) ставит путь ПЕРВЫМ в списке.
    # Это заставляет Python брать .pyd отсюда, а не папку hft_core рядом со скриптом.
    sys.path.insert(0, found_path)
    print(f"✅ Добавлен приоритетный путь: {found_path}")
else:
    print("❌ ПУТЬ К СБОРКЕ НЕ НАЙДЕН. Проверь, где лежит файл .pyd")
    # Выводим текущую структуру для отладки
    print(f"Искал в: {possible_paths}")
    sys.exit(1)

try:
    import hft_core
    # Проверка на вшивость: откуда загрузился модуль?
    print(f"📍 Модуль загружен из: {hft_core.__file__}") 
    
    # Если загрузился не .pyd, выбрасываем ошибку сами
    if not hft_core.__file__.endswith(".pyd"):
        raise ImportError("Загружена папка вместо библиотеки! Проблема shadowing.")
        
except ImportError as e:
    print(f"💀 ОШИБКА ИМПОРТА: {e}")
    sys.exit(1)

# --- 2. CALLBACK ---
def on_tick_received(tick):
    print(f"⚡ TICK: {tick.symbol} | P: {tick.price:.2f} | V: {tick.volume:.5f}")

# --- 3. ЗАПУСК ---
def main():
    print("Инициализация класса...")
    try:
        streamer = hft_core.ExchangeStreamer()
    except AttributeError:
        print("❌ ОШИБКА: Класс ExchangeStreamer не найден в модуле.")
        print("Скорее всего, ты импортировал папку с исходниками, а не .pyd файл.")
        return

    streamer.set_callback(on_tick_received)
    
    # Тест на Binance
    url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    
    print(f"🔌 Подключение к {url}...")
    streamer.connect(url)
    streamer.start()
    
    print("⏳ Слушаем 10 секунд...")
    try:
        for i in range(10):
            time.sleep(1)
            # Чтобы не было скучно, печатаем точки
            print(".", end="", flush=True)
    except KeyboardInterrupt:
        pass
    
    print("\n🛑 Остановка...")
    streamer.stop()
    print("✅ Тест завершен.")

if __name__ == "__main__":
    main()