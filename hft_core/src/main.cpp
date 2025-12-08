#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h> // Желательно добавить для умных указателей
#include "exchange_streamer.hpp"
#include "parsers/bybit_parser.hpp"

namespace py = pybind11;

PYBIND11_MODULE(hft_core, m) {
    py::class_<TickData>(m, "TickData")
        .def_readonly("symbol", &TickData::symbol)
        .def_readonly("price", &TickData::price)
        .def_readonly("volume", &TickData::volume)
        .def_readonly("timestamp", &TickData::timestamp);

    // Указываем std::shared_ptr как holder type для IMessageParser
    py::class_<IMessageParser, std::shared_ptr<IMessageParser>>(m, "IMessageParser");

    // И для BybitParser тоже
    py::class_<BybitParser, IMessageParser, std::shared_ptr<BybitParser>>(m, "BybitParser")
        .def(py::init<>());

    py::class_<ExchangeStreamer>(m, "ExchangeStreamer")
        // Pybind11 теперь поймет, как передать shared_ptr
        .def(py::init<std::shared_ptr<IMessageParser>>()) 
        .def("connect", &ExchangeStreamer::connect)
        .def("start", &ExchangeStreamer::start, py::call_guard<py::gil_scoped_release>())
        .def("stop", &ExchangeStreamer::stop, py::call_guard<py::gil_scoped_release>())
        .def("send_message", &ExchangeStreamer::send_message)
        .def("set_callback", [](ExchangeStreamer &self, std::function<void(const TickData&)> cb) {
            self.set_callback([cb](const TickData& t) {
                py::gil_scoped_acquire acquire;
                cb(t);
            });
        });
}