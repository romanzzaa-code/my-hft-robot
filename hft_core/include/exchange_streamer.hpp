#pragma once

#include <string>
#include <functional>
#include <ixwebsocket/IXWebSocket.h>
#include <ixwebsocket/IXNetSystem.h>

struct TickData {
    std::string symbol;
    double price;
    double volume;
    // Добавим timestamp, он критически важен для HFT
    long long timestamp; 
};

class ExchangeStreamer {
public:
    ExchangeStreamer();
    ~ExchangeStreamer();

    void connect(std::string url);
    void start();
    void stop();
    
    // [NEW] Метод отправки сообщений (для подписки на Bybit)
    void send_message(std::string msg);

    void set_callback(std::function<void(const TickData&)> cb);

private:
    ix::WebSocket webSocket;
    std::function<void(const TickData&)> callback;
};