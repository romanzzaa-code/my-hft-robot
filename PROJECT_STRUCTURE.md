# Project Structure: My HFT Robot (Rust)

Этот файл служит картой для Gemini CLI. Здесь описаны основные компоненты и их ответственности.

## Root Directory
- `rust_src/`: Основной код на Rust (Workspace).
- `config/`: Конфигурационные файлы (YAML/JSON) для стратегий и подключений.
- `logs/`: Логи работы робота.
- `timescaledb_data/`: Данные для локальной БД (аналитика/бектест).
- `ARCHITECTURE.md`: Высокоуровневое описание архитектуры.
- `PROJECT_STATE.md`: Текущий прогресс рефакторинга и следующие шаги.

## Rust Workspace (`rust_src/`)

### 1. `hft-domain` (Core Business Logic)
Самый внутренний слой. Не зависит от внешних библиотек (кроме Decimal/Serde).
- `lib.rs`: Определения базовых типов (`Price`, `Qty`, `Side`), `ExecutionReport`, `Tick` и трейта `ExecutionHandler` (DIP).
- `strategy_logic.rs`: `AdaptiveWallStrategyLogic` — чистая логика принятия решений. Содержит стейт-машину стратегии.
- `analytics.rs`: `MarketAnalytics` — расчет NATR, TP/SL, средних объемов.
- `detector.rs`: `WallDetector` — алгоритм поиска "стенок" в стакане.
- `orderbook.rs`: `LocalOrderBook` — эффективное хранение и обновление локальной копии стакана.

### 2. `hft-service` (Application Services)
Слой оркестрации и реализации инфраструктурных трейтов.
- `runner.rs`: `Runner` — главный цикл робота (`tokio::select!`). Связывает стримы данных, стратегию и экзекутор.
- `lib.rs`: Трейты `MarketDataStream` и `ExecutionReportStream`.
- `executors.rs`: Реализации `ExecutionHandler`. `LiveExecutor` (реальная торговля) и `ShadowExecutor` (логирование без отправки).
- `bybit_rest.rs`: `BybitRestClient` — реализация REST запросов к Bybit V5.
- `bybit_ws_private.rs`: `BybitPrivateWs` — WebSocket клиент для приватных данных (ордера, позиции).
- `market_scanner.rs`: Поиск волатильных пар для запуска стратегии.
- `factories.rs`: `BybitRunnerFactory` — создание инстансов `Runner` со всеми зависимостями.

### 3. `hft-core` (Shared Infrastructure)
Общие утилиты и базовые коннекторы.
- `connector.rs`: Базовые структуры для обмена сообщениями с биржами (`ExchangeMessage`).
- `error.rs`: Глобальная обработка ошибок.
- `utils/`: Таймеры, логирование, работа с конфигурацией.

### 4. `hft-app` (Entry Point)
Загрузка конфигов, инициализация логов и запуск `Runner` или `MarketScanner`.

## Hot Paths (Для оптимизации)
1. `hft-service/src/runner.rs`: Цикл `run()` — здесь происходит вся магия.
2. `hft-domain/src/strategy_logic.rs`: Метод `on_tick` и `on_orderbook`.
3. `hft-domain/src/analytics.rs`: `update_natr` и расчеты уровней.

## Dependencies
- `rust_decimal`: Для точных вычислений без float-ошибок.
- `tokio`: Асинхронный рантайм.
- `tracing`: Высокопроизводительное логирование.
