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