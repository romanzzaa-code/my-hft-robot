cmake_minimum_required(VERSION 3.15)

project(hft_core)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# --- 1. Настройка OpenSSL (MacOS Fix) ---
if(APPLE)
    if(EXISTS "/opt/homebrew/opt/openssl@3")
        set(OPENSSL_ROOT_DIR "/opt/homebrew/opt/openssl@3")
    elseif(EXISTS "/usr/local/opt/openssl@3")
        set(OPENSSL_ROOT_DIR "/usr/local/opt/openssl@3")
    endif()
endif()

# Ищем системные пакеты
find_package(OpenSSL REQUIRED)
find_package(ZLIB REQUIRED)

# --- 2. Автоматическая загрузка библиотек через FetchContent ---
include(FetchContent)

FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG        v3.11.3
)

FetchContent_Declare(
    simdjson
    GIT_REPOSITORY https://github.com/simdjson/simdjson.git
    GIT_TAG        v3.10.1
)

FetchContent_Declare(
    ixwebsocket
    GIT_REPOSITORY https://github.com/machinezone/IXWebSocket.git
    GIT_TAG        v11.4.5
)

FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG        v2.12.0
)

set(USE_TLS ON CACHE BOOL "" FORCE)

# Делаем всё доступным
FetchContent_MakeAvailable(nlohmann_json simdjson ixwebsocket pybind11)


# --- 3. Сборка модуля ---
add_library(hft_core SHARED 
    src/main.cpp
    src/exchange_streamer.cpp 
    src/order_gateway.cpp
    src/parsers/binance_parser.cpp
    src/parsers/bybit_parser.cpp
)

# --- 4. Линковка ---
target_link_libraries(hft_core PRIVATE 
    ixwebsocket::ixwebsocket
    simdjson::simdjson
    nlohmann_json::nlohmann_json
    OpenSSL::SSL
    OpenSSL::Crypto
    ZLIB::ZLIB
    pybind11::module
)

if(WIN32)
    target_link_libraries(hft_core PRIVATE Bcrypt Crypt32)
endif()

target_include_directories(hft_core PRIVATE src include)

set_target_properties(hft_core PROPERTIES PREFIX "${PYTHON_MODULE_PREFIX}")
set_target_properties(hft_core PROPERTIES SUFFIX "${PYTHON_MODULE_EXTENSION}")

# --- 5. Установка (ОБЯЗАТЕЛЬНО для pip install) ---
install(TARGETS hft_core DESTINATION .)