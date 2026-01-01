#include "../include/order_gateway.hpp"
#include <iostream>
#include <chrono>
#include <sstream>
#include <iomanip>
#include <openssl/hmac.h>
#include <nlohmann/json.hpp>
#include <ixwebsocket/IXNetSystem.h>

// Хелпер для создания подписи HMAC SHA256
// Bybit требует подписывать запросы секретным ключом
std::string hmac_sha256(const std::string& key, const std::string& data) {
    unsigned char* digest;
    unsigned int len = 0;
    
    // Используем OpenSSL для генерации хеша
    digest = HMAC(EVP_sha256(), 
                  (const void*)key.c_str(), key.length(), 
                  (const unsigned char*)data.c_str(), data.length(), 
                  NULL, &len);
    
    std::stringstream ss;
    for(unsigned int i = 0; i < len; i++) {
        // Конвертируем байты в hex-строку
        ss << std::hex << std::setw(2) << std::setfill('0') << (int)digest[i];
    }
    return ss.str();
}

OrderGateway::OrderGateway(std::string key, std::string secret, bool testnet) 
    : api_key_(key), api_secret_(secret) 
{
    // Инициализация сетевой подсистемы (важно для Windows/Mac)
    ix::initNetSystem();

    // Выбираем URL: Trade WebSocket (V5)
    url_ = testnet ? "wss://stream-testnet.bybit.com/v5/trade" 
                   : "wss://stream.bybit.com/v5/trade";
    
    webSocket.setUrl(url_);
    
    // Пинг каждые 20 секунд, чтобы Bybit не разорвал соединение
    webSocket.setPingInterval(20); 

    // Привязываем обработчик сообщений
    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        this->on_message(msg);
    });
}

OrderGateway::~OrderGateway() {
    stop();
}

void OrderGateway::connect() {
    std::cout << "[C++] OrderGateway connecting to " << url_ << "..." << std::endl;
    webSocket.start();
    // Аутентификация произойдет автоматически в on_message при событии Open
}

void OrderGateway::stop() {
    webSocket.stop();
}

void OrderGateway::set_on_order_update(std::function<void(const std::string&)> cb) {
    on_order_update_cb_ = cb;
}

std::string OrderGateway::generate_signature(long long expires) {
    // Формат подписи для Websocket Bybit V5:
    // param = "GET/realtime" + expires
    std::string val = "GET/realtime" + std::to_string(expires);
    return hmac_sha256(api_secret_, val);
}

void OrderGateway::authenticate() {
    // Expires = текущее время + 5000 мс (окно валидности)
    auto now = std::chrono::system_clock::now();
    long long expires = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count() + 5000;
    
    std::string signature = generate_signature(expires);
    
    // Формируем JSON для auth
    nlohmann::json auth_msg;
    auth_msg["op"] = "auth";
    auth_msg["args"] = {api_key_, expires, signature};
    
    webSocket.send(auth_msg.dump());
}

void OrderGateway::send_order(const std::string& symbol, const std::string& side, double qty, double price) {
    if (!authenticated_) {
        std::cerr << "[C++] ERROR: Cannot send order - Wait for Auth!" << std::endl;
        return;
    }

    // Сборка JSON ордера
    nlohmann::json order;
    order["category"] = "linear";
    order["symbol"] = symbol;
    order["side"] = side; // "Buy" или "Sell"
    order["orderType"] = "Limit";
    
    // Важно: Bybit API требует числа в виде строк во избежание потери точности float
    order["qty"] = std::to_string(qty); 
    order["price"] = std::to_string(price);
    
    order["timeInForce"] = "PostOnly"; // Мы мейкеры, мы не платим за вход в позицию (обычно)

    nlohmann::json msg;
    msg["op"] = "order.create"; 
    msg["args"] = {order};
    
    // Моментальная отправка
    webSocket.send(msg.dump());
}

void OrderGateway::cancel_order(const std::string& symbol, const std::string& order_id) {
    if (!authenticated_) return;

    nlohmann::json cancel_req;
    cancel_req["category"] = "linear";
    cancel_req["symbol"] = symbol;
    cancel_req["orderId"] = order_id;

    nlohmann::json msg;
    msg["op"] = "order.cancel";
    msg["args"] = {cancel_req};

    webSocket.send(msg.dump());
}

void OrderGateway::on_message(const ix::WebSocketMessagePtr& msg) {
    if (msg->type == ix::WebSocketMessageType::Open) {
        std::cout << "[C++] Trade Stream Connected. Sending Auth..." << std::endl;
        authenticate();
    } 
    else if (msg->type == ix::WebSocketMessageType::Message) {
        // Обработка ответов
        try {
            auto j = nlohmann::json::parse(msg->str);
            
            // 1. Проверяем ответ на Аутентификацию
            if (j.contains("op") && j["op"] == "auth") {
                if (j.value("success", false)) {
                    authenticated_ = true;
                    std::cout << "[C++] ✅ AUTH SUCCESS! Ready to trade." << std::endl;
                } else {
                    std::cerr << "[C++] ❌ AUTH FAILED: " << msg->str << std::endl;
                }
            }
            
            // 2. Пробрасываем все сообщения (подтверждения ордеров) в Python
            if (on_order_update_cb_) {
                on_order_update_cb_(msg->str);
            }
        } catch (...) {
            // Игнорируем битый JSON
        }
    }
    else if (msg->type == ix::WebSocketMessageType::Error) {
        std::cerr << "[C++] WS Error: " << msg->errorInfo.reason << std::endl;
    }
}