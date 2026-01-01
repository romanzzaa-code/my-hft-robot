cmake_minimum_required(VERSION 3.15)

# Указываем путь к vcpkg (если он у тебя в C:/vcpkg)
#set(CMAKE_TOOLCHAIN_FILE "C:/vcpkg/scripts/buildsystems/vcpkg.cmake" CACHE STRING "Vcpkg toolchain file")

project(hft_core)

# Настройки стандарта
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# 1. Simdjson берем из системы (мы его поставили через brew)
find_package(simdjson CONFIG REQUIRED)

# 2. IXWebSocket скачиваем и собираем сами (так как нет в brew)
include(FetchContent)
FetchContent_Declare(
  ixwebsocket
  GIT_REPOSITORY https://github.com/machinezone/IXWebSocket.git
  GIT_TAG        v11.4.4  # Фиксируем стабильную версию
)
# Отключаем сборку тестов и примеров ixwebsocket, чтобы было быстрее
set(IXWEBSOCKET_INSTALL OFF CACHE BOOL "" FORCE)
set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(ixwebsocket)

# --- 2. Подключаем Pybind11 через FetchContent ---
include(FetchContent)
FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG        v2.12.0
)
FetchContent_MakeAvailable(pybind11)

# --- 3. Ищем Python ---
find_package(Python 3.12 COMPONENTS Interpreter Development REQUIRED)

# --- 4. Сборка модуля ---
add_library(hft_core SHARED 
    src/main.cpp
    src/exchange_streamer.cpp 
    src/parsers/binance_parser.cpp
    src/parsers/bybit_parser.cpp
)

# --- 5. Линковка ---
target_link_libraries(hft_core PRIVATE 
    ixwebsocket::ixwebsocket
    simdjson::simdjson
    pybind11::module
)

# [FIX] Добавляем системные библиотеки Windows для криптографии
if(WIN32)
    target_link_libraries(hft_core PRIVATE Bcrypt Crypt32)
endif()

target_include_directories(hft_core PRIVATE src include)

# Настройка имени выходного файла
set_target_properties(hft_core PROPERTIES PREFIX "${PYTHON_MODULE_PREFIX}")
set_target_properties(hft_core PROPERTIES SUFFIX "${PYTHON_MODULE_EXTENSION}")