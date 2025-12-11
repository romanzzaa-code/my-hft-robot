#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h> 
#include "exchange_streamer.hpp"
#include "parsers/bybit_parser.hpp"
#include "entities/ticker_data.hpp" // <--- Важно!

namespace py = pybind11;

PYBIND11_MODULE(hft_core, m) {
    // ... (TickData, PriceLevel, OrderBookSnapshot, IMessageParser, BybitParser остаются как были) ...
    
    // Повторю для контекста, но убедись, что не удаляешь старое:
    py::class_<TickData>(m, "TickData", py::dynamic_attr())
        .def_readonly("symbol", &TickData::symbol)
        .def_readonly("price", &TickData::price)
        .def_readonly("volume", &TickData::volume)
        .def_readonly("timestamp", &TickData::timestamp);

    py::class_<PriceLevel>(m, "PriceLevel")
        .def_readonly("price", &PriceLevel::price)
        .def_readonly("quantity", &PriceLevel::quantity);

    py::class_<OrderBookSnapshot>(m, "OrderBookSnapshot", py::dynamic_attr())
        .def_readonly("symbol", &OrderBookSnapshot::symbol)
        .def_readonly("timestamp", &OrderBookSnapshot::timestamp)
        .def_readonly("local_timestamp", &OrderBookSnapshot::local_timestamp)
        .def_readonly("bids", &OrderBookSnapshot::bids)
        .def_readonly("asks", &OrderBookSnapshot::asks)
        .def_readonly("is_snapshot", &OrderBookSnapshot::is_snapshot);

    // [NEW] Экспорт новой сущности TickerData
    py::class_<TickerData>(m, "TickerData", py::dynamic_attr())
        .def_readonly("symbol", &TickerData::symbol)
        .def_readonly("last_price", &TickerData::last_price)
        .def_readonly("turnover_24h", &TickerData::turnover_24h)
        .def_readonly("price_24h_pcnt", &TickerData::price_24h_pcnt)
        .def_readonly("timestamp", &TickerData::timestamp);

    py::class_<IMessageParser, std::shared_ptr<IMessageParser>>(m, "IMessageParser");

    py::class_<BybitParser, IMessageParser, std::shared_ptr<BybitParser>>(m, "BybitParser")
        .def(py::init<>());

    // --- Streamer ---
    py::class_<ExchangeStreamer>(m, "ExchangeStreamer")
        .def(py::init<std::shared_ptr<IMessageParser>>()) 
        .def("connect", &ExchangeStreamer::connect)
        .def("start", &ExchangeStreamer::start, py::call_guard<py::gil_scoped_release>())
        .def("stop", &ExchangeStreamer::stop, py::call_guard<py::gil_scoped_release>())
        .def("send_message", &ExchangeStreamer::send_message)
        .def("set_tick_callback", [](ExchangeStreamer &self, std::function<void(const TickData&)> cb) {
            self.set_tick_callback([cb](const TickData& t) {
                py::gil_scoped_acquire acquire; 
                cb(t);
            });
        })
        .def("set_depth_callback", [](ExchangeStreamer &self, std::function<void(const OrderBookSnapshot&)> cb) {
            self.set_depth_callback([cb](const OrderBookSnapshot& d) {
                py::gil_scoped_acquire acquire; 
                cb(d);
            });
        })
        // [NEW] Биндинг для тикеров (с защитой GIL)
        .def("set_ticker_callback", [](ExchangeStreamer &self, std::function<void(const TickerData&)> cb) {
            self.set_ticker_callback([cb](const TickerData& t) {
                py::gil_scoped_acquire acquire; 
                cb(t);
            });
        });
}