#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h> 
#include "exchange_streamer.hpp"
#include "order_gateway.hpp" // <--- ВАЖНО: Добавили хедер шлюза
#include "parsers/bybit_parser.hpp"
#include "entities/tick_data.hpp"
#include "entities/execution_data.hpp"

namespace py = pybind11;

PYBIND11_MODULE(hft_core, m) {

    // --- PriceLevel ---
    py::class_<PriceLevel>(m, "PriceLevel")
        .def_readwrite("price", &PriceLevel::price)
        .def_readwrite("qty", &PriceLevel::qty);

    // --- OrderBookSnapshot ---
    py::class_<OrderBookSnapshot>(m, "OrderBookSnapshot")
        .def_readwrite("symbol", &OrderBookSnapshot::symbol)
        .def_readwrite("bids", &OrderBookSnapshot::bids)
        .def_readwrite("asks", &OrderBookSnapshot::asks)
        .def_readwrite("timestamp", &OrderBookSnapshot::timestamp)
        .def_readwrite("u", &OrderBookSnapshot::u)
        .def_readwrite("local_timestamp", &OrderBookSnapshot::local_timestamp) // <--- Вернули
        .def_readwrite("is_snapshot", &OrderBookSnapshot::is_snapshot);        // <--- Вернули

    // --- TickData ---
    py::class_<TickData>(m, "TickData")
        .def(py::init<>())
        .def_readwrite("symbol", &TickData::symbol)
        .def_readwrite("price", &TickData::price)
        .def_readwrite("qty", &TickData::qty)
        .def_readwrite("timestamp", &TickData::timestamp)
        .def_readwrite("side", &TickData::side);

    // --- TickerData ---
    py::class_<TickerData>(m, "TickerData")
        .def(py::init<>())
        .def_readwrite("symbol", &TickerData::symbol)
        .def_readwrite("best_bid", &TickerData::best_bid)
        .def_readwrite("best_ask", &TickerData::best_ask)
        .def_readwrite("turnover_24h", &TickerData::turnover_24h)
        .def_readwrite("volume_24h", &TickerData::volume_24h)
        .def_readwrite("last_price", &TickerData::last_price)         // <--- Вернули
        .def_readwrite("price_24h_pcnt", &TickerData::price_24h_pcnt) // <--- Вернули
        .def_readwrite("timestamp", &TickerData::timestamp);

    // --- ExecutionData ---
    py::class_<ExecutionData>(m, "ExecutionData")
        .def(py::init<>())
        .def_readwrite("symbol", &ExecutionData::symbol)
        .def_readwrite("side", &ExecutionData::side)
        .def_readwrite("order_id", &ExecutionData::order_id)
        .def_readwrite("exec_type", &ExecutionData::exec_type)
        // Важно: биндим те поля, которые заполняет парсер
        .def_readwrite("exec_price", &ExecutionData::exec_price) 
        .def_readwrite("exec_qty", &ExecutionData::exec_qty)
        .def_readwrite("is_maker", &ExecutionData::is_maker)
        .def_readwrite("timestamp", &ExecutionData::timestamp);

    // --- Парсеры ---
    py::class_<IMessageParser, std::shared_ptr<IMessageParser>>(m, "IMessageParser");
    
    py::class_<BybitParser, IMessageParser, std::shared_ptr<BybitParser>>(m, "BybitParser")
        .def(py::init<>());

    // --- OrderGateway (НОВОЕ) ---
    py::class_<OrderGateway>(m, "OrderGateway")
        // Конструктор: api_key, api_secret, testnet
        .def(py::init<std::string, std::string, bool>(), 
             py::arg("api_key"), py::arg("api_secret"), py::arg("testnet") = false)
        
        // Методы управления соединением (отпускаем GIL, чтобы не блокировать Python)
        .def("connect", &OrderGateway::connect, py::call_guard<py::gil_scoped_release>())
        .def("stop", &OrderGateway::stop, py::call_guard<py::gil_scoped_release>())
        
        // Торговые методы (КРИТИЧНО: gil_scoped_release для скорости)
        .def("send_order", &OrderGateway::send_order, 
             py::call_guard<py::gil_scoped_release>(),
             py::arg("symbol"),
             py::arg("side"),
             py::arg("qty"),
             py::arg("price"),
             py::arg("order_link_id") = "",
             py::arg("order_type") = "Limit",
             py::arg("time_in_force") = "PostOnly",
             py::arg("reduce_only") = false
        )     
             
        .def("cancel_order", &OrderGateway::cancel_order, 
             py::call_guard<py::gil_scoped_release>(),
             py::arg("symbol"), py::arg("order_id"))
        
        // Коллбек для ответов биржи
        .def("set_on_order_update", [](OrderGateway &self, std::function<void(const std::string&)> cb) {
            self.set_on_order_update([cb](const std::string& msg) {
                // ВНИМАНИЕ: Захватываем GIL, так как входим в контекст Python
                py::gil_scoped_acquire acquire; 
                cb(msg);
            });
        });

    // --- ExchangeStreamer (оставляем как было) ---
    py::class_<ExchangeStreamer>(m, "ExchangeStreamer")
        .def(py::init<std::shared_ptr<IMessageParser>>())
        .def("add_symbol", &ExchangeStreamer::add_symbol)
        .def("start", &ExchangeStreamer::start, py::call_guard<py::gil_scoped_release>())
        .def("stop", &ExchangeStreamer::stop, py::call_guard<py::gil_scoped_release>())
        .def("set_tick_callback", [](ExchangeStreamer &self, std::function<void(const TickData&)> cb) {
            self.set_tick_callback([cb](const TickData& t) {
                py::gil_scoped_acquire acquire;
                cb(t);
            });
        })
        .def("set_orderbook_callback", [](ExchangeStreamer &self, std::function<void(const OrderBookSnapshot&)> cb) {
            self.set_orderbook_callback([cb](const OrderBookSnapshot& obs) {
                py::gil_scoped_acquire acquire;
                cb(obs);
            });
        })
        .def("set_execution_callback", [](ExchangeStreamer &self, std::function<void(const ExecutionData&)> cb) {
            self.set_execution_callback([cb](const ExecutionData& e) {
                py::gil_scoped_acquire acquire;
                cb(e);
            });
        });
}