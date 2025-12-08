#pragma once
#include <string>
#include <functional>
#include <memory>         // для std::unique_ptr
#include <ixwebsocket/IXWebSocket.h>
#include "entities/tick_data.hpp"  // Новое место TickData
#include "parsers/imessage_parser.hpp" // Интерфейс

class ExchangeStreamer {
public:
    // Конструктор теперь требует парсер!
    ExchangeStreamer(std::shared_ptr<IMessageParser> parser);
    ~ExchangeStreamer();

    void connect(std::string url);
    void start();
    void stop();
    void send_message(std::string msg);
    void set_callback(std::function<void(const TickData&)> cb);

private:
    ix::WebSocket webSocket;
    std::function<void(const TickData&)> callback;
    std::shared_ptr<IMessageParser> parser; // Храним shared_ptr
};