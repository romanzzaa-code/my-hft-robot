// hft_core/include/exchange_streamer.hpp
#pragma once
#include <string>
#include <functional>
#include <memory>
#include <ixwebsocket/IXWebSocket.h>
#include "entities/tick_data.hpp"
#include "entities/market_depth.hpp" // <-- Добавили
#include "parsers/imessage_parser.hpp"

class ExchangeStreamer {
public:
    ExchangeStreamer(std::shared_ptr<IMessageParser> parser);
    ~ExchangeStreamer();

    void connect(std::string url);
    void start();
    void stop();
    void send_message(std::string msg);

    // Старый коллбек для тиков
    void set_tick_callback(std::function<void(const TickData&)> cb);
    // Новый коллбек для стаканов
    void set_depth_callback(std::function<void(const OrderBookSnapshot&)> cb);

private:
    ix::WebSocket webSocket;
    std::shared_ptr<IMessageParser> parser;
    
    // Два отдельных коллбека
    std::function<void(const TickData&)> tick_callback;
    std::function<void(const OrderBookSnapshot&)> depth_callback;
};