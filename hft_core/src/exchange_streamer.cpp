#include "exchange_streamer.hpp"
#include <iostream>
// !!! ДОБАВЛЕН ВАЖНЫЙ ИНКЛЮД !!!
#include <ixwebsocket/IXNetSystem.h> 

ExchangeStreamer::ExchangeStreamer(std::shared_ptr<IMessageParser> p) 
    : parser(p) // shared_ptr просто копируется, move не нужен
{
    ix::initNetSystem(); // Теперь эта функция будет найдена
}

ExchangeStreamer::~ExchangeStreamer() {
    stop();
    ix::uninitNetSystem();
}

void ExchangeStreamer::set_callback(std::function<void(const TickData&)> cb) {
    callback = cb;
}

void ExchangeStreamer::connect(std::string url) {
    webSocket.setUrl(url);
    webSocket.setPingInterval(45);

    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        if (msg->type == ix::WebSocketMessageType::Message) {
            TickData tick;
            // Безопасный вызов парсера
            if (parser && parser->parse(msg->str, tick)) {
                 if (callback) callback(tick);
            }
        }
        else if (msg->type == ix::WebSocketMessageType::Open) {
            std::cout << "[CPP] Connected!" << std::endl;
        }
    });
}

void ExchangeStreamer::send_message(std::string msg) {
    webSocket.send(msg);
}

void ExchangeStreamer::start() {
    webSocket.start();
}

void ExchangeStreamer::stop() {
    webSocket.stop();
}