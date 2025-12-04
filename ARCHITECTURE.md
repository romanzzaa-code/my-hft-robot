Project: HFT Scalping Bot (Hybrid C++/Python)
Goal
Create a self-learning scalping bot for Bybit (Master Trader Copytrading) that trades off "Order Book Walls".

Architecture Stack
Core (C++):

Uses uWebSockets for ultra-low latency data streams (Binance/Bybit/OKX).

Uses simdjson for parsing JSON.

Exposed to Python via pybind11.

Logic (Python):

asyncio based main loop.

Strategy: Detects liquidity walls -> Front-runs them.

Execution: pybit SDK (V5 API) for CopyTrading.

Data & Learning:

Database: TimescaleDB (PostgreSQL) for tick data.

Backtest: hftbacktest library (simulates queue position).

Optimization: Optuna (re-trains parameters daily).

UI:

Telegram Bot (aiogram) for Start/Stop/Config.

Current Status
Rules for AI Assistant
Always prioritize low latency code in C++.

In Python, use asyncio properly, never block the loop.

When modifying C++, ensure CMakeLists.txt is updated.

Remember we are trading in "Master Trader" mode on Bybit.

hft_core Module Architecture
Module Purpose: Core C++ module for high-frequency trading operations, exposed to Python via pybind11

Directory Structure:
- src/: Contains C++ source files
- include/: Contains C++ header files
- tests/: Contains unit tests

Build System: CMake with C++20 standard

Dependencies Integration:
- pybind11: Integrated via FetchContent for Python bindings
- uWebSockets: Integrated via FetchContent with uSockets dependency
- simdjson: Integrated via FetchContent for high-performance JSON parsing

Compiler Optimizations:
- Flags: -O3 and -march=native for vector instruction activation
- Critical for simdjson performance requirements

Build Output: Shared library (.so/.dll) importable as Python module named 'hft_core'