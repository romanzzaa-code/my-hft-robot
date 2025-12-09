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