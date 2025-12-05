cmake_minimum_required(VERSION 3.15)

project(hft_core)

# --- 1. Настройки ---
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# --- 2. Зависимости ---
include(FetchContent)

# 2.1 Pybind11
FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG        v2.12.0
)
FetchContent_MakeAvailable(pybind11)

# 2.2 Libuv (КРИТИЧНО для Windows)
FetchContent_Declare(
  libuv
  GIT_REPOSITORY https://github.com/libuv/libuv.git
  GIT_TAG        v1.48.0
)
FetchContent_MakeAvailable(libuv)

# 2.3 uSockets (Ручная сборка)
FetchContent_Declare(
  usockets
  GIT_REPOSITORY https://github.com/uNetworking/uSockets.git
  GIT_TAG        v0.8.8
)
FetchContent_GetProperties(usockets)
if(NOT usockets_POPULATED)
  FetchContent_Populate(usockets)
endif()

# Логика исходников uSockets
file(GLOB USOCKETS_SOURCES 
    "${usockets_SOURCE_DIR}/src/*.c"
    "${usockets_SOURCE_DIR}/src/eventing/*.c"
    "${usockets_SOURCE_DIR}/src/crypto/*.c"
)

if(WIN32)
    # На Windows убираем лишнее, используем libuv
    list(REMOVE_ITEM USOCKETS_SOURCES 
        "${usockets_SOURCE_DIR}/src/eventing/epoll_kqueue.c"
        "${usockets_SOURCE_DIR}/src/eventing/gcd.c"
    )
    add_compile_definitions(LIBUS_USE_LIBUV)
else()
    # На Linux/Mac
    list(REMOVE_ITEM USOCKETS_SOURCES 
        "${usockets_SOURCE_DIR}/src/eventing/libuv.c"
        "${usockets_SOURCE_DIR}/src/eventing/gcd.c" 
        "${usockets_SOURCE_DIR}/src/eventing/windows.c"
    )
endif()

# Создаем библиотеку uSockets
add_library(uSockets STATIC ${USOCKETS_SOURCES})
target_include_directories(uSockets PUBLIC "${usockets_SOURCE_DIR}/src")

if(WIN32)
    target_link_libraries(uSockets PRIVATE uv_a)
endif()

target_compile_definitions(uSockets PRIVATE LIBUS_NO_SSL)

# 2.4 uWebSockets (HEADER ONLY)
# Мы просто скачиваем файлы, но НЕ делаем add_subdirectory, 
# чтобы не создавать лишних целей, которые путают CMake.
FetchContent_Declare(
  uwebsockets
  GIT_REPOSITORY https://github.com/uNetworking/uWebSockets.git
  GIT_TAG        v20.66.0
)
FetchContent_GetProperties(uwebsockets)
if(NOT uwebsockets_POPULATED)
  FetchContent_Populate(uwebsockets)
endif()

# 2.5 Simdjson
FetchContent_Declare(
  simdjson
  GIT_REPOSITORY https://github.com/simdjson/simdjson.git
  GIT_TAG        v3.10.0
)
FetchContent_MakeAvailable(simdjson)

# --- 3. Оптимизация ---
if(MSVC)
    add_compile_options(/O2 /arch:AVX2 /Oi /GL)
else()
    add_compile_options(-O3 -march=native -flto)
endif()

# --- 4. Поиск Python ---
find_package(Python 3.10 COMPONENTS Interpreter Development REQUIRED)

# --- 5. Сборка нашего модуля ---
add_library(hft_core SHARED src/main.cpp)

# --- 6. Линковка ---
# ВНИМАНИЕ: Здесь убрали uWebSockets, так как это не библиотека, а просто хидеры
target_link_libraries(hft_core PRIVATE 
    pybind11::module 
    pybind11::lto 
    simdjson::simdjson
    uSockets 
)

if(WIN32)
    # Системные библиотеки Windows для сети
    target_link_libraries(hft_core PRIVATE uv_a ws2_32 iphlpapi userenv psapi)
endif()

# --- 7. Пути к заголовкам ---
target_include_directories(hft_core PRIVATE 
    include
    ${uwebsockets_SOURCE_DIR}/src  # <-- Вот здесь мы подключаем uWebSockets
    ${usockets_SOURCE_DIR}/src
)

# --- 8. Настройки вывода ---
set_target_properties(hft_core PROPERTIES PREFIX "${PYTHON_MODULE_PREFIX}")
set_target_properties(hft_core PROPERTIES SUFFIX "${PYTHON_MODULE_EXTENSION}")

message(STATUS "HFT Core configuration done. Ready to build.")