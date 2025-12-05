#include <pybind11/pybind11.h>
// Подключаем наш заголовочный файл, чтобы видеть класс ExchangeStreamer
#include "exchange_streamer.hpp"

namespace py = pybind11;

PYBIND11_MODULE(hft_core, m) {
    m.doc() = "HFT Core Module: C++ Engine for High-Frequency Trading";

    // Создаем Python-класс "ExchangeStreamer" внутри модуля
    py::class_<ExchangeStreamer>(m, "ExchangeStreamer")
        // 1. Экспортируем конструктор (чтобы можно было писать streamer = ExchangeStreamer())
        .def(py::init<>())
        
        // 2. Экспортируем метод connect
        .def("connect", &ExchangeStreamer::connect, "Connect to a WebSocket URL")
        
        // 3. Экспортируем метод start
        // ВАЖНО: Используем call_guard<py::gil_scoped_release>(),
        // чтобы C++ отпустил глобальную блокировку Python (GIL) на время работы потока.
        // Без этого твой Python-скрипт зависнет намертво при вызове start().
        .def("start", &ExchangeStreamer::start, py::call_guard<py::gil_scoped_release>());
}