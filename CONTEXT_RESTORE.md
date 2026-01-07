# 🔥 HFT Robot Project Context (Restore Point)
**Date:** 08.12.2025
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 1 Completed (Data Infrastructure Ready)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (режим Master Trader Copytrading).
**Стек:**
- **Core:** C++20 (`ixwebsocket`, `simdjson`) — сбор данных.
- **Glue:** `pybind11` — биндинги с управлением GIL.
- **Logic:** Python 3.11 (`asyncio`) — стратегии и управление.
- **Storage:** TimescaleDB (Docker) — хранение тиков.
- **Backtest:** `hftbacktest` (планируется).

---

## 🏗 Текущая Архитектура (Clean Architecture)
Реализована гибридная схема:
1.  **C++ Layer (`hft_core`):**
    - `ExchangeStreamer`: "Тупой" коннектор, использует `ixwebsocket`.
    - `Parsers`: Отделены от стримера. Реализован `BybitParser` через интерфейс `IMessageParser`.
    - **Concurrency:** Реализована защита GIL (`py::gil_scoped_acquire` в коллбеках, `py::gil_scoped_release` в `start/stop`).
2.  **Python Layer (`hft_strategy`):**
    - `MarketBridge`: Адаптер, превращающий C++ callback в очередь `asyncio.Queue`.
    - `AsyncDBWriter`: Буферизированная запись в БД (batch insert через `COPY`).

---

## 📂 Структура файлов (Актуальная)
```text
d:/ant/
├── hft_core/
│   ├── include/
│   │   ├── entities/tick_data.hpp       (Struct TickData)
│   │   ├── parsers/imessage_parser.hpp  (Interface)
│   │   ├── parsers/bybit_parser.hpp     (Header)
│   │   └── exchange_streamer.hpp        (Dependency Injection)
│   ├── src/
│   │   ├── parsers/bybit_parser.cpp     (Implementation + simdjson)
│   │   ├── exchange_streamer.cpp        (ixwebsocket logic)
│   │   └── main.cpp                     (Pybind11 module definition)
│   └── CMakeLists.txt
├── hft_strategy/
│   ├── market_bridge.py                 (Bridge C++ -> Asyncio)
│   ├── db_writer.py                     (Asyncpg batch writer)
│   ├── db_migration.py                  (SQL schema init)
│   └── main.py                          (Entry point)
├── docker-compose.yml                   (TimescaleDB + pgAdmin)
└── tests/
    └── test_bybit.py                    (Smoke test)

 ✅ Что сделано (Done)
C++ Core Refactoring:

Внедрена Dependency Injection (Стример принимает Парсер).

Исправлен Deadlock при остановке (добавлен call_guard в stop).

Исправлен Segfault (добавлен gil_scoped_acquire в коллбек).

Data Pipeline:

Данные успешно идут с Bybit V5 (publicTrade).

Парсинг времени исправлен (поле "T" вместо "t").

Storage:

Поднят TimescaleDB в Docker.

Создана гипертаблица market_ticks.

Реализован AsyncDBWriter с буфером.

Проверено: В базе успешно копятся тики (50k+ записей подтверждено).

🚀 Дальнейшие действия (To-Do)
Мы находимся на переходе к Фазе 2: Бэктестинг.

Накопление данных:

[IN PROGRESS] Скрипт hft_strategy/main.py оставлен работать на сутки для сбора истории.

Экспорт данных:

Написать скрипт экспорта из TimescaleDB в формат .npz (структура для hftbacktest).

Учесть коррекцию local_timestamp vs exchange_timestamp.

Бэктестинг:

Настроить симуляцию hftbacktest.

Реализовать стратегию поиска стен (Wall Detection) на исторических данных.

🛠 Технические нюансы (Environment)
OS: Windows.

Build: cmake --build build --config Release.

Docker: Данные маппятся в D:\ant\timescaledb_data.

DB Access:

pgAdmin: http://localhost:5050 (Login: admin@admin.com / admin).

DB Credentials: hft_user / password. 

# 🔥 HFT Robot Project Context (Restore Point)
**Date:** 09.12.2025
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 2.2 Active (Data Collection & Pipeline Stability)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (Master Trader Copytrading).
**Текущий фокус:** Сбор "Золотого Датасета" (Trades + Orderbook Deltas) для обучения стратегии.

---

## 🏗 Текущая Архитектура (Hybrid C++/Python)
Реализован полный пайплайн доставки данных:
1.  **Source:** Bybit V5 WebSocket (`publicTrade`, `orderbook.50`).
2.  **C++ Core (`hft_core`):**
    * **Streamer:** `ExchangeStreamer` управляет соединением и маршрутизирует данные в два канала: `TickCallback` и `DepthCallback`.
    * **Parser:** `BybitParser` (simdjson) распознает `snapshot` и `delta`. Дельты обрабатываются как обновления стакана.
    * **Interface:** `IMessageParser` возвращает `ParseResultType` (Trade/Depth).
3.  **Python Layer (`hft_strategy`):**
    * **Bridge:** `MarketBridge` подписывается на оба канала, тегирует события (`type='trade'` / `type='depth'`).
    * **Writer:** `BufferedTickWriter` буферизирует события. Сериализует стаканы в JSON-строки перед вставкой.
4.  **Storage:** TimescaleDB (`market_ticks`, `market_depth_snapshots` с полями `JSONB`).

---

## ✅ Что сделано (Completed)

### 1. C++ Core Refactoring
* [x] **Entities:** Создана структура `OrderBookSnapshot` (bids, asks, timestamp).
* [x] **Parser Logic:** `BybitParser` научился понимать `topic: orderbook.50`. Реализована единая логика парсинга для `snapshot` и `delta`.
* [x] **Callback System:** `ExchangeStreamer` теперь имеет два метода: `set_tick_callback` и `set_depth_callback`.
* [x] **Pybind11 Fixes:** Добавлен `py::dynamic_attr()` для структур данных (позволяет Python'у делать `setattr`).

### 2. Database & Data Engineering
* [x] **Schema:** Создана таблица `market_depth_snapshots` c `JSONB` колонками для bids/asks.
* [x] **Serialization Fix:** Исправлена ошибка `no binary format encoder`. Python явно делает `json.dumps()` перед отправкой в `asyncpg`.
* [x] **Data Verification:** Подтверждено, что в базу пишутся и сделки, и дельты стакана (поток не прерывается).

### 3. Pipeline
* [x] **Export Script:** Написан `export_data.py` для конвертации SQL-данных в формат `.npz` (для `hftbacktest`). Скрипт умеет мерджить сделки и стаканы.

---

## 🚧 Технический Долг (Immediate Refactoring)
Эти задачи нужно выполнить **первыми** в новом чате перед переходом к бэктестам.

1.  **Config Management:** Убрать хардкод (`DB_CONFIG`, символы) в единый `config.py`.
2.  **Optimization:** Заменить стандартный `json` на `orjson` в `db_writer.py` для ускорения сериализации.
3.  **Testing:** Починить `tests/test_bybit.py` (он сломан после изменения API стримера).
4.  **Observability:** Добавить Error Callback в C++, чтобы не "глотать" ошибки парсинга молча.

---

## 📂 Структура файлов (Ключевые)
```text
hft_core/
├── include/
│   ├── entities/market_depth.hpp    (Struct OrderBookSnapshot)
│   ├── parsers/bybit_parser.hpp     (Updated parse signature)
│   └── exchange_streamer.hpp        (Dual callback definitions)
├── src/
│   ├── parsers/bybit_parser.cpp     (Snapshot + Delta logic)
│   ├── exchange_streamer.cpp        (Routing Trade vs Depth)
│   └── main.cpp                     (Pybind11 exports + dynamic_attr)
hft_strategy/
├── market_bridge.py                 (Subscribes to orderbook.50)
├── db_writer.py                     (Handles JSON serialization)
├── db_migration.py                  (Creates JSONB tables)
└── export_data.py                   (SQL -> NPZ converter)

# 🔥 HFT Robot Project Context (Restore Point)
**Date:** 09.12.2025 (Updated)
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 2.3 Completed (Architecture Hardened & Optimized)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (Master Trader Copytrading).
**Текущий фокус:** Переход к Фазе 3 (Логика стратегии и Бэктестинг).

---

## 🏗 Текущая Архитектура (Refactored & Clean)
Мы устранили "детские болезни" прототипа и перешли к промышленным стандартам:

1.  **Configuration (SSOT):**
    -   Внедрен `config.py` с датаклассами `DatabaseConfig` и `TradingConfig`.
    -   Убран хардкод паролей и URL из кода классов.
    -   `main.py` выступает как **Composition Root**, собирая граф зависимостей.

2.  **Performance Layer:**
    -   **Serialization:** Создан `serializers.py` (SRP).
    -   **Speed:** Стандартный `json` заменен на `orjson` (Rust-based, в 10-20 раз быстрее).
    -   **Non-Blocking:** Убраны блокирующие вызовы `json.dumps` из Event Loop'а.

3.  **Data Safety:**
    -   **Streaming:** Скрипт `export_data.py` переписан на **Server-Side Cursors**. Теперь экспорт гигабайтов данных не вызывает `MemoryError`.

---

## ✅ Что сделано (Completed Tasks)

### 1. Архитектура и Безопасность
* [x] **Config Management:** Создан `hft_strategy/config.py`. Все креды и настройки теперь в одном месте.
* [x] **Dependency Injection:** `MarketBridge` и `TimescaleRepository` теперь получают настройки через конструктор. Сделана легкая смена Mainnet <-> Testnet.
* [x] **Single Responsibility:** Логика сериализации вынесена в `serializers.py`.

### 2. Оптимизация (Performance)
* [cite_start][x] **Orjson Integration:** Внедрен `orjson` в `db_writer.py` и `export_data.py`[cite: 36].
* [cite_start][x] **Memory Safety:** `export_data.py` переписан на потоковую обработку (cursor iteration) вместо загрузки всего в RAM[cite: 36].

### 3. Базовый пайплайн (Сохранено с прошлых фаз)
* [cite_start][x] **C++ Core:** `ExchangeStreamer` + `BybitParser` (simdjson) работают стабильно[cite: 24, 46].
* [cite_start][x] **Data Storage:** TimescaleDB успешно пишет тики и снимки стаканов (JSONB)[cite: 36].

---

## 📂 Структура файлов (Актуальная)
```text
hft_core/
├── include/
│   ├── entities/market_depth.hpp    (Struct OrderBookSnapshot)
│   ├── parsers/bybit_parser.hpp     (Updated parse signature)
│   └── exchange_streamer.hpp        (Dual callback definitions)
├── src/
│   ├── parsers/bybit_parser.cpp     (Snapshot + Delta logic)
│   ├── exchange_streamer.cpp        (Routing Trade vs Depth)
│   └── main.cpp                     (Pybind11 exports)
hft_strategy/
├── config.py                        (🔥 NEW: Config Dataclasses)
├── serializers.py                   (🔥 NEW: Orjson Logic)
├── market_bridge.py                 (Updated: DI injection)
├── db_writer.py                     (Updated: Uses serializers & orjson)
├── export_data.py                   (Updated: Streaming cursors)
├── main.py                          (Updated: Composition Root)
└── db_migration.py                  (SQL schema init)


# 🔥 HFT Robot Project Context (Restore Point)
**Date:** 09.12.2025 (Updated)
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 2.5 Completed (Funnel Architecture & Multi-Asset Support)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (Master Trader Copytrading).
**Текущий фокус:** Накопление данных по Топ-5 самых ликвидных монет (Smart Selection).

---

## 🏗 Текущая Архитектура (Funnel Architecture)
Реализована профессиональная схема отбора инструментов ("Воронка"), позволяющая мониторить 200+ монет без перегрузки железа:

1.  **Level 1: Discovery (Разведка)**
    -   `BybitInstrumentProvider`: Раз в 24 часа запрашивает у API список всех USDT-перпетуалов, доступных для CopyTrading (исключая BTC/ETH).
2.  **Level 2: Surveillance (Наблюдение)**
    -   `ExchangeStreamer` (C++): Подписывается на легкий поток `tickers` для всего списка (200+ монет).
    -   `TickerData`: Новая C++ сущность для хранения макро-статистики (оборот, цена).
3.  **Level 3: Analytics (Анализ)**
    -   `MarketScanner` (Python): В реальном времени ранжирует монеты по обороту (`turnover_24h`).
4.  **Level 4: Execution (Фокусировка)**
    -   `MarketBridge`: Автоматически ротирует "тяжелые" подписки (`orderbook.50` + `publicTrade`) для Топ-5 горячих монет.
    -   `BufferedTickWriter`: Пишет в TimescaleDB полные данные только по избранным активам.

---

## ✅ Что сделано (Completed Tasks)

### 1. C++ Core (Low-Latency Layer)
* [x] **New Entity:** Добавлена структура `TickerData` (symbol, turnover, price change).
* [x] **Parser Upgrade:** Интерфейс `IMessageParser` расширен для поддержки тикеров. `BybitParser` научился парсить топик `tickers`. `BinanceParser` обновлен для совместимости.
* [x] **Routing:** В `ExchangeStreamer` добавлен отдельный канал `set_ticker_callback`, который не смешивается с потоком сделок.
* [x] **Python Bindings:** Экспортированы `TickerData` и коллбеки через `pybind11`.

### 2. Python Services (Strategy Layer)
* [x] **Service Layer:** Создана папка `services/` для декомпозиции логики.
* [x] **Instrument Provider:** Реализован фильтр монет (CopyTrading check, Blacklist BTC/ETH).
* [x] **Market Scanner:** Реализован алгоритм ранжирования (O(1) update, O(N log N) sort).
* [x] **Smart Bridge:** `MarketBridge` теперь умеет управлять двумя потоками подписок (Tickers vs Heavy Data) и синхронизировать их (Diff logic).

### 3. Orchestration
* [x] **Background Tasks:** В `main.py` запущены циклы `daily_discovery_loop` и `hot_rotation_loop`.
* [x] **Direct Wiring:** Тикеры из C++ передаются в Сканер напрямую через lambda, минуя `asyncio.Queue` (Zero-Overhead).

---

## 📂 Структура файлов (Актуальная)
```text
hft_core/
├── include/
│   ├── entities/ticker_data.hpp     (🔥 NEW: Ticker Entity)
│   ├── parsers/imessage_parser.hpp  (Updated: 4-arg signature)
│   └── exchange_streamer.hpp        (Updated: Ticker callback)
├── src/
│   ├── parsers/bybit_parser.cpp     (Updated: Parsing logic)
│   └── main.cpp                     (Updated: Pybind11 exports)
hft_strategy/
├── services/                        (🔥 NEW: Service Layer)
│   ├── instrument_provider.py       (Discovery)
│   └── market_scanner.py            (Analytics)
├── config.py
├── market_bridge.py                 (Updated: Smart Subscriptions)
├── main.py                          (Updated: Funnel Logic)
└── db_writer.py

🔥 HFT Robot Project Context (Restore Point)
Date: 11.12.2025 Role: Lead Quantitative Developer (Code Critic Persona) Status: Phase 2.5 STALLED (Backtesting Engine Integration Issues)

🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (Master Trader Copytrading). Текущий фокус: Запуск первого валидного бэктеста на исторических данных hftbacktest v2.4.4.

🏗 Архитектура (Funnel Architecture)
C++ Layer: ExchangeStreamer + BybitParser (simdjson). Стабилен.

Storage: TimescaleDB (Docker). Содержит >12 млн тиков по SOLUSDT.

Backtest: hftbacktest v2.4.4 (Rust core). Здесь текущая проблема.

✅ Достижения (What we did today)
1. Data Validation ("Золотой Датасет")
Создан инструмент validate_reconstruction.py.

Результат: Проверено 31 час данных SOLUSDT (850k снепшотов). 0 Integrity Errors (Crossed Books).

Вывод: Пайплайн сбора (C++ -> Python -> DB) работает идеально. Данные консистентны.

2. Migration to HftBacktest v2.4.4
Обнаружено, что библиотека обновилась с v1 до v2.4 (Breaking Changes).

Export: Переписан export_data.py. Теперь использует:

Битовые флаги (TRADE_EVENT | BUY_EVENT, DEPTH_EVENT).

Сортировку по local_ts (требование движка).

Наносекунды (1e9) вместо микросекунд.

Backtest: Переписан backtest.py под новый API (HashMapMarketDepthBacktest, .constant_order_latency(), методы настройки ассета).

Config: Внедрен strategy_config.py для нормализации стратегии (Ratio вместо Volume, Ticks вместо Price).

🛑 ТЕКУЩАЯ ПРОБЛЕМА (BLOCKER)
Симптом: При запуске debug_backtest.py движок инициализируется, но метод hbt.elapse(100_000_000) мгновенно возвращает код 1 (End of Data / Error), не совершив ни одного шага симуляции.

Диагностика:

Данные есть: Файл .npz весит ~90 МБ, содержит 12 млн строк.

Флаги верны: Используются нативные константы v2.4 (536870913 и т.д.).

Время корректно: Наносекунды, отсортированы по local_ts.

Гипотеза: Вероятно, проблема в формате передачи данных (.data([path]) vs .data(array)) или в специфическом требовании v2 к структуре первого события (Snapshot Marker). Движок Rust считает данные невалидными и сразу завершает работу.

📋 План действий (Next Steps)
Deep Debugging: Разобраться, почему Rust-ядро отвергает данные. Проверить заголовки .npz, типы данных (dtype).

Minimal Reproducible Example: Создать синтетический датасет из 10 строк и попытаться скормить его движку.

Fix Pipeline: Как только elapse вернет 0 (Success), запустить полный бэктест и анализ PnL.

📂 Структура файлов (Актуальная)
Plaintext

hft_strategy/
├── backtest.py                  (Engine v2 implementation)
├── debug_backtest.py            (Deep dive debugger - FAILING HERE)
├── export_data.py               (Exporter v2 with bitwise flags)
├── analyze_results.py           (PnL Visualizer)
├── validate_reconstruction.py   (Data Integrity Check - PASSED)
├── strategy_config.py           (Normalization logic)
└── ... (Infrastructure files)
}

# 📂 HFT Strategy Context Restore Point
**Дата:** 12.12.2025
**Статус:** ✅ Движок запущен, данные валидны, стратегия торгует (тестовый прогон).

---

## 🛑 История Проблем и Решений

### 1. Ошибка `BacktestError: Custom { kind: InvalidData, error: "unsupported data type" }`
**Симптомы:** Движок падал сразу после старта, `Steps: 0`.
**Причина:**
1.  Ядро Rust (`hftbacktest`) требует строгого выравнивания памяти (C-contiguous layout).
2.  Отсутствовали обязательные системные флаги событий `EXCH_EVENT` и `LOCAL_EVENT` (требование версии 2.4.4+).
**Решение:**
* Принудительное выравнивание: `data = np.ascontiguousarray(data)`.
* Добавление флагов: `ev |= EXCH_EVENT | LOCAL_EVENT`.

### 2. Проблема "Пустого Стакана" (`Bid: 0`, `Ask: 0`)
**Симптомы:** Движок работал, шаги шли (`Steps: 1M+`), но цены в стакане были равны 0.
**Причина:**
1.  **Loader:** Функция `load_data_correctly` перезаписывала правильные флаги из `export_data.py` (где уже были размечены `DEPTH_CLEAR`, `BUY/SELL`) на дефолтные.
2.  **Engine:** `HashMapMarketDepthBacktest` не может построить стакан без параметра `tick_size`. Он использует его для хеширования цен (float -> int). Без этого ордера игнорировались.
**Решение:**
* Написана функция `load_data_smart`, которая сохраняет существующие флаги.
* В конфигурацию `Asset` добавлен `.tick_size(0.01).lot_size(0.01)`.

---

## 🛠 Текущая Конфигурация (Working Setup)

### Файл: `backtest_main.py`
* **Загрузчик:** Использует `load_data_smart`. Определяет, размечены ли данные. Если да — добавляет только системные флаги. Если нет — пытается восстановить структуру.
* **Ассет:**
    ```python
    asset = (
        BacktestAsset()
        .data(data)
        .linear_asset(1.0)
        .tick_size(0.01)  # <--- КРИТИЧНО ВАЖНО
        .lot_size(0.01)
        .constant_order_latency(10_000_000, 10_000_000) # 10ms задержка
    )
    ```
* **Стратегия:** Внедрена простая логика "Ping-Pong" (выставляет лимитку на BestBid-1, при исполнении — продает на BestAsk+1).

### Файл: `analyze_stats.py` (Новый)
* Скрипт для чтения файла результатов `stats_sol.npz`.
* Использует `hftbacktest.stats.LinearAssetRecord` для расчета метрик.

---

## 📊 Текущий Статус
1.  **Данные:** Загружаются корректно. Первое событие имеет правильные флаги (пример: `EV=3758096388`).
2.  **Движок:** Успешно прогнал ~1.1 млн событий.
3.  **Тест Стратегии:**
    * Запуск прошел успешно.
    * Результат: `Steps: 2` (это `order_id` счетчик). Означает, что стратегия успела выставить 1 ордер.
    * Файл статистики `stats_sol.npz` создан.

---

## 🚀 План Действий (Next Steps)

1.  **Анализ результатов:**
    * Запустить `analyze_stats.py`, чтобы посмотреть, были ли сделки (Trades) или ордер просто висел.
    * Команда: `python analyze_stats.py`

2.  **Доработка Стратегии:**
    * Текущая "Ping-Pong" логика слишком проста (ордер может висеть вечно, если цена ушла).
    * Нужно добавить логику отмены (`cancel`) и перестановки ордеров (chasing).

3.  **Визуализация (Опционально):**
    * Построить график Equity Curve на основе данных из `stats_sol.npz`.

    # 🔥 HFT Robot Project Context (Restore Point)
**Date:** 15.12.2025
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 3 Completed (Strategy Optimized & Live Bot Ready)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (Master Trader Copytrading).
**Текущий фокус:** Запуск Live-торговли на реальные деньги (Real Money).

---

## 🏗 Архитектура (Clean & Scalable)
Мы провели масштабный рефакторинг и стабилизировали систему:

1.  **Structure:** Внедрена Clean Architecture:
    -   `domain/`: Константы (`events.py`) и конфиги (`strategy_config.py`).
    -   `infrastructure/`: Исполнение ордеров (`execution.py`), Мост (`market_bridge.py`), БД (`db_writer.py`).
    -   `strategies/`: Логика (`wall_bounce.py` для Numba, `live_strategy.py` для AsyncIO).
    -   `pipelines/`: ETL процессы (`export_data.py`).
    
2.  **Backtesting Engine:**
    -   Успешно проведены бэктесты на 1.2 млн событий (SOLUSDT).
    -   **Optuna** нашла оптимальные параметры (`wall=105.0`, `tp=5`, `sl=36`).
    -   Визуализация доказала корректность работы State Machine (робот не "залипает" в позициях).

3.  **Live Core:**
    -   **C++:** Пересобран `hft_core.pyd` (Release) с поддержкой парсинга тикеров и стаканов.
    -   **Python:** Реализован `live_bot.py` с автоматическим Path Hack для загрузки C++ ядра.
    -   **Execution:** `BybitExecutionHandler` (pybit) поддерживает Read-Only режим и реальную торговлю.

---

## ✅ Что сделано (Completed Tasks)

### 1. Optimization & Validation
* [x] **Strategy Logic:** Исправлен баг "Death Spiral" (замена `GTX` на `GTC` для Stop Loss). Теперь робот корректно кроет убытки.
* [x] **Parameter Tuning:** Скрипт `optimization.py` автоматически подобрал параметры с положительным Sharpe Ratio.
* [x] **Visualization:** `visualize.py` строит график Equity/Position, подтверждая адекватность логики.

### 2. Live Environment Setup
* [x] **Dependencies:** Установлен и проверен `pybit`. `requirements.txt` обновлен.
* [x] **Environment:** Настроена загрузка `.env` через `python-dotenv`.
* [x] **Compilation:** C++ ядро успешно скомпилировано и линкуется в Python.
* [x] **Simulation Test:** Бот запущен в режиме `READ-ONLY`. Логи подтверждают:
    -   C++ парсер видит стакан.
    -   Стратегия детектирует стены (`🧱 WALL DETECTED`).
    -   Исполнитель симулирует отправку ордеров (`🕶️ [SIM] PLACING`).

---

## 📂 Структура файлов (Ключевые)
```text
hft_strategy/
├── domain/
│   ├── events.py                    (SSOT для флагов)
│   └── strategy_config.py           (Параметры: Wall=105.0)
├── infrastructure/
│   ├── execution.py                 (Bybit API Wrapper)
│   └── market_bridge.py             (C++ -> Python Adapter)
├── strategies/
│   ├── wall_bounce.py               (Numba logic for Backtest)
│   └── live_strategy.py             (Async logic for Live)
├── live_bot.py                      (🔥 ENTRY POINT: Live Trading)
├── backtest_bot.py                  (Entry Point: Backtest)
├── optimization.py                  (Optuna Tuner)
└── visualize.py                     (Matplotlib Charts)

# 🔥 HFT Robot Project Context (Restore Point)
**Date:** 19.12.2025
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 4 Active (Live Testing & Strategy Hardening)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (Master Trader Copytrading).
**Текущий фокус:** Стабилизация Live-торговли, устранение "детских болезней" (Race Conditions, Spam, False Positives).

---

## 🏗 Текущая Архитектура (Clean & Robust)
Мы перешли от прототипа к промышленной архитектуре с защитой капитала:

1.  **Dependency Inversion (DIP):**
    -   Внедрен интерфейс `IExecutionHandler` (`domain/interfaces.py`).
    -   Стратегия `AdaptiveWallStrategy` больше не зависит от `BybitExecutionHandler` напрямую.
    -   **Critical Fix:** Методы исполнения теперь принимают `symbol` явным аргументом. Устранен баг, когда робот находил сигнал на одной монете, а ордер ставил на другой (из-за Singleton-природы хендлера).

2.  **Safety Layer (Infrastructure):**
    -   **Numeric Stability:** Реализован метод `_fmt()` в `execution.py`. Исключена отправка чисел в научной нотации (`1e-05`), что приводило к реджекта ордеров.
    -   **Connection Stability:** В `market_bridge.py` внедрен Application-Level Heartbeat (JSON-пинг `{"op": "ping"}` каждые 20 сек).
    -   **API Limits:** `recv_window=5000` добавлено для защиты от рассинхрона времени.

3.  **Smart Strategy Logic (State Machine):**
    -   **Hybrid Exit:** Робот различает "Разъедание" (цена пробила стену -> `Panic Exit`) и "Снятие/Спуфинг" (цена стоит -> `HOLD`).
    -   **Race Condition Protection:** Внедрен `Double-Check` позиции после отмены ордера. Робот не теряет "повисшие" позиции при лагах биржи.
    -   **Debounce:** (Временно отключен для тестов) Механизм `_required_confirms` для фильтрации мерцающих стен.

---

## ✅ Что сделано (Completed Tasks)

### 1. Архитектура и Баги
* [x] **Symbol Injection:** Стратегия теперь сама управляет контекстом символа. Мульти-бот работает корректно на 4+ парах одновременно.
* [x] **Ghost Position Fix:** Исправлена логика `_handle_order_placed`. Если ордер исполнился во время отмены, робот подхватывает его и ведет дальше.
* [x] **Logs Hygiene:** Уровень `INFO` очищен от спама. "Шум" сканера и проверок убран в `DEBUG`.

### 2. Логика Торговли
* [x] **Anti-Spoofing:** Если стену убрали, но цена не ухудшилась — робот держит позицию (экономия комиссии Taker).
* [x] **Panic Exit:** Работает надежно. При пробое уровня или жестком стопе позиция кроется по рынку с ретраями.

---

## 🚧 План действий (Next Steps)

### 1. Technical Debt (Срочно)
* [x] **Suppress Error 110001:** В `execution.py` нужно подавить ошибку "Order not exists" при отмене (сделать `INFO` вместо `ERROR`), чтобы не засорять логи. Это штатная ситуация для HFT.

### 2. Tuning (Перед увеличением объема)
* [x] **Enable Filters:** Вернуть `_required_confirms = 3` и настроить `wall_ratio_threshold` (мин. 5-10x от среднего), чтобы убрать вход в "шум".
* [x] **Event-Driven Execution:** (Позже) Заменить `asyncio.sleep(0.5)` на Websocket-стрим исполнений (`execution` topic) для мгновенной реакции.

---

## 📂 Структура файлов (Ключевые изменения)
```text
hft_strategy/
├── domain/
│   ├── interfaces.py                (✅ NEW: Контракт исполнителя)
│   └── strategy_config.py
├── infrastructure/
│   ├── execution.py                 (Updated: _fmt, symbol arg, heartbeat)
│   └── market_bridge.py             (Updated: Ping loop)
├── strategies/
│   └── adaptive_live_strategy.py    (Refactored: Hybrid Exit, Debounce, Clean Logs)
└── live_bot.py                      (Entry Point)

# 🔥 HFT Robot Project Context (Restore Point)
**Date:** 19.12.2025
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 4 Active (Event-Driven Architecture & Low Latency)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (Master Trader Copytrading).
**Текущий фокус:** Минимизация latency (переход на Push-уведомления) и стабилизация Live-режима.

---

## 🏗 Текущая Архитектура (Event-Driven & Clean)
Проведен критический рефакторинг системы исполнения. Мы отказались от опроса API (`await asyncio.sleep(0.5)`) в пользу мгновенной реакции на вебсокет-события.

1.  **C++ Core (`hft_core`):**
    -   **New Entity:** `ExecutionData` — структура для передачи сделок (ID, Price, Qty, Side).
    -   **Parser:** `BybitParser` научился разбирать приватный топик `execution`.
    -   **Routing:** `ExchangeStreamer` теперь имеет отдельный канал `set_execution_callback`, который работает параллельно с маркет-датой.

2.  **Infrastructure (Python):**
    -   **Dual Streamers:** `live_bot.py` теперь запускает два независимых стримера:
        1.  *Public Bridge:* `wss://stream.bybit.com/v5/public/linear` (Стакан, Сделки).
        2.  *Private Bridge:* `wss://stream.bybit.com/v5/private` (Исполнения).
    -   **Fan-In Pattern:** Данные из обоих мостов сливаются в единую `Shared Queue`.
    -   **Security:** Реализована HMAC-аутентификация для приватного канала.

3.  **Strategy Logic (Reactive):**
    -   **No More Polling:** Убрана задержка в 500мс. Стратегия больше не спрашивает "меня исполнили?", а ждет события.
    -   **Atomic Execution:** Метод `on_execution` мгновенно переводит робота в состояние `IN_POSITION` и выставляет Take Profit. Время реакции < 2мс.

---

## ✅ Что сделано (Completed Tasks)

### 1. C++ Low-Latency Layer
* [x] **Entity:** Добавлена `ExecutionData` и экспортирована в Python.
* [x] **Interfaces:** Обновлен `IMessageParser` (добавлен 5-й аргумент). `BinanceParser` и `BybitParser` синхронизированы.
* [x] **Build:** Проект успешно пересобран (`cmake --build`).

### 2. Infrastructure Layer
* [x] **MarketBridge Upgrade:** Внедрен Dependency Injection для очереди. Добавлена поддержка `authenticate()` и `subscribe_executions()`.
* [x] **Config:** Добавлен `private_ws_url` в `TradingConfig`.
* [x] **Live Bot:** Реализован запуск двух параллельных стримеров с единой точкой входа событий.

### 3. Strategy Layer
* [x] **Refactoring:** Метод `_handle_order_placed` очищен от поллинга.
* [x] **New Handler:** Реализован `on_execution`, который обрабатывает вход в позицию по факту события.

---

## 📂 Структура файлов (Ключевые изменения)
```text
hft_core/
├── include/entities/execution_data.hpp  (✅ NEW: DTO)
├── src/parsers/bybit_parser.cpp         (Updated: Parsing 'execution' topic)
├── src/main.cpp                         (Updated: Pybind export)
hft_strategy/
├── infrastructure/
│   └── market_bridge.py                 (Updated: Auth & Private Subs)
├── strategies/
│   └── adaptive_live_strategy.py        (Refactored: on_execution logic)
├── live_bot.py                          (Updated: Dual Streamer Setup)
└── config.py                            (Updated: Private WS URL)

# 🔥 HFT Robot Project Context (Restore Point)
**Date:** 20.12.2025
**Role:** Lead Quantitative Developer (Code Critic Persona)
**Status:** Phase 4.1 Active (Production Hardening & Race Condition Fixes)

## 🎯 Цель проекта
Создание самообучающегося HFT-робота для скальпинга "от плотностей" (Wall Bounce) на Bybit (режим Master Trader Copytrading).
**Текущий фокус:** Безопасность исполнения (Safety) и реактивность (Low Latency).

---

## 🏗 Текущая Архитектура (Event-Driven & Resilient)
Мы полностью отказались от polling-модели (`sleep(0.5)`) и внедрили гибридную систему исполнения, устойчивую к сетевым сбоям и гонкам состояний.

1.  **C++ Core (`hft_core`):**
    -   **Entity:** `ExecutionData` — структура для передачи сделок (ID, Price, Qty, Side, IsMaker).
    -   **Parser:** `BybitParser` разбирает приватный топик `execution`.
    -   **Routing:** `ExchangeStreamer` имеет отдельный канал `set_execution_callback`.

2.  **Infrastructure (Python):**
    -   **Dual Streamers:** `live_bot.py` запускает два независимых стримера:
        1.  *Public:* `wss://stream.bybit.com/v5/public/linear` (Orderbook, Trades).
        2.  *Private:* `wss://stream.bybit.com/v5/private` (Executions) с HMAC-аутентификацией.
    -   **Fan-In:** Данные сливаются в единую `Shared Queue`.
    -   **Resilience:** В `execution.py` внедрен Retry-механизм для REST-запросов (защита от `RemoteDisconnected`).

3.  **Strategy Logic (Smart State Machine):**
    -   **Reactive Entry:** Вход в позицию происходит мгновенно по событию `on_execution` (Push), без опроса API.
    -   **Reactive Exit:** Стратегия отслеживает исполнение Take Profit и корректно сбрасывает стейт в `IDLE`.
    -   **Anti-Ghost Protocol:** Реализована защита от "Призрачных исполнений" (Ghost Fills). При отмене ордера робот делает паузу 200мс и проверяет реальную позицию через REST. Если отмена не прошла — робот подхватывает позицию на лету.

---

## ✅ Что сделано (Completed Tasks)

### 1. Low-Latency Execution
* [x] **Event-Driven:** Реализован `on_execution` handler. Реакция на исполнение < 2мс.
* [x] **No Polling:** Убран `await asyncio.sleep(0.5)` из цикла ожидания входа.

### 2. Safety & Risk Management
* [x] **Race Condition Fix:** Метод `_safe_cancel_and_reset` спасает депозит, если ордер исполнился в момент отмены.
* [x] **Network Stability:** Внедрены ретраи в `fetch_ohlc` для подавления транзиентных ошибок сети.
* [x] **Logs Hygiene:** Логи очищены от спама, добавлены четкие маркеры событий (`⚡ EXECUTION`, `😱 GHOST FILL`, `💰 TP FILLED`).

### 3. Strategy Logic
* [x] **Full Cycle:** Робот видит и вход (Entry), и выход (TP/SL).
* [x] **Blind Spot Fix:** Исправлена ошибка, когда бот игнорировал исполнение Тейка из-за несовпадения OrderID.

---

## 📂 Структура файлов (Ключевые изменения)
```text
hft_core/
├── include/entities/execution_data.hpp  (DTO)
├── src/parsers/bybit_parser.cpp         (Execution parsing)
hft_strategy/
├── infrastructure/
│   ├── market_bridge.py                 (Auth & Private Subs)
│   ├── execution.py                     (Retry Logic)
├── strategies/
│   └── adaptive_live_strategy.py        (on_execution, _safe_cancel_and_reset)
├── live_bot.py                          (Dual Streamer Setup)
└── config.py                            (Private URL)


🔥 HFT Robot Project Context (Restore Point)
Date: 07.01.2026 Role: Lead Quantitative Developer (Code Critic Persona) Status: Phase 4.2 Completed (Decoupled Architecture & Production Hardened)

🎯 Текущий прогресс
Мы ликвидировали «God Object» в лице AdaptiveWallStrategy, превратив его в чистый оркестратор. Теперь система соответствует принципам SOLID и готова к масштабированию на десятки торговых пар без хаоса в коде.

🏗 Новая Архитектура (Service-Oriented)
Логика разделена на три независимых сервиса, координируемых через AdaptiveWallStrategy:

MarketAnalytics (services/analytics.py):

Обязанность: Математика и волатильность.

Функции: Фоновый расчет NATR (свечи 5м) и EMA фонового объема стакана.

WallDetector (services/wall_detector.py):

Обязанность: Генерация сигналов.

Функции: Расчет динамических порогов «стен» и логика подтверждения (debounce 3 тика).

TradeManager (services/trade_manager.py):

Обязанность: «Руки» робота. Исполнение и контроль позиции.

Функции: Управление TradeContext и StrategyState, реактивная обработка on_execution.

✅ Что сделано (Critical Fixes & Upgrades)
1. C++ Low-Latency Layer

Parameterized Orders: Метод send_order расширен. Теперь поддерживает order_link_id, order_type (Limit/Market), time_in_force и reduce_only.

Hermetic Build: CMakeLists.txt переведен на FetchContent. Библиотеки ixwebsocket и simdjson собираются автоматически.

TLS Fix: Принудительно включен флаг USE_TLS для корректной работы wss:// внутри Docker.

2. Strategy Logic (Safety First)

Take Profit: Исправлен синтаксический баг. Внедрен asyncio.Lock и детерминированный order_link_id (tp_{entry_id}), что исключает дублирование ордеров при резких движениях цены.

Panic Exit: Реализован каскадный выход (WS Market Order через C++ + REST Market Order). Используется IOC и reduce_only, что гарантирует закрытие без реджектов PostOnly.

Ghost Fill Protection: TradeManager проверяет реально налитый объем перед отменой, предотвращая потерю контроля над позицией.

3. Infrastructure & DevOps

Hot Reload: В docker-compose.yml добавлены volumes. Теперь правки в Python применяются через docker compose restart bot за 2 секунды без перекомпиляции C++.

Docker Stability: В Dockerfile добавлены системные зависимости libssl-dev и zlib1g-dev для сборки на любой архитектуре (Mac M4 / Ubuntu).

📂 Обновленная структура файлов
Plaintext
hft_strategy/
├── services/
│   ├── analytics.py        (Математика рынка)
│   ├── wall_detector.py    (Поиск сигналов)
│   └── trade_manager.py    (Исполнение и FSM)
├── strategies/
│   └── adaptive_live_strategy.py (Тонкий оркестратор)
├── domain/
│   ├── trade_context.py    (Value Objects: State, Context)
│   └── interfaces.py       (DIP: IExecutionHandler)
└── infrastructure/
    └── execution.py        (Bybit REST Wrapper)