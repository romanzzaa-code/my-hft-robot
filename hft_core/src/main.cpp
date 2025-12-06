#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include "exchange_streamer.hpp"

namespace py = pybind11;

PYBIND11_MODULE(hft_core, m) {
    py::class_<TickData>(m, "TickData")
        .def_readonly("symbol", &TickData::symbol)
        .def_readonly("price", &TickData::price)
        .def_readonly("volume", &TickData::volume)
        .def_readonly("timestamp", &TickData::timestamp); // Добавили поле

    py::class_<ExchangeStreamer>(m, "ExchangeStreamer")
        .def(py::init<>())
        .def("connect", &ExchangeStreamer::connect)
        .def("start", &ExchangeStreamer::start, py::call_guard<py::gil_scoped_release>())
        .def("stop", &ExchangeStreamer::stop)
        .def("send_message", &ExchangeStreamer::send_message) // Добавили метод
        .def("set_callback", &ExchangeStreamer::set_callback);
}