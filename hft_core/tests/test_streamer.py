import sys
import os
import time

sys.path.append(os.path.join(os.getcwd(), 'hft_core', 'build', 'Release'))

try:
    import hft_core
    print("✅ Библиотека загружена.")
except ImportError as e:
    print(f"❌ Ошибка: {e}")
    sys.exit(1)

def main():
    streamer = hft_core.ExchangeStreamer()
    
    # ИСПОЛЬЗУЕМ ОБЫЧНЫЙ WS (без шифрования) для теста движка
    # Этот сервер просто возвращает нам то, что мы ему отправим, 
    # но uWebSockets должен хотя бы установить соединение.
    test_url = "ws://echo.websocket.events" 
    
    print(f"Connecting to {test_url}...")
    streamer.connect(test_url)
    
    streamer.start()
    
    print("Streamer running. Waiting 5 seconds...")
    time.sleep(5)
    print("Test finished.")

if __name__ == "__main__":
    main()