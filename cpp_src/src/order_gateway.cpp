#include "../include/order_gateway.hpp"
#include <iostream>
#include <chrono>
#include <sstream>
#include <iomanip>
#include <openssl/hmac.h>
#include <nlohmann/json.hpp>
#include <ixwebsocket/IXNetSystem.h>

std::string hmac_sha256(const std::string& key, const std::string& data) {
    unsigned char* digest;
    unsigned int len = 0;
    digest = HMAC(EVP_sha256(), 
                  (const void*)key.c_str(), key.length(), 
                  (const unsigned char*)data.c_str(), data.length(), 
                  NULL, &len);
    std::stringstream ss;
    for(unsigned int i = 0; i < len; i++) {
        ss << std::hex << std::setw(2) << std::setfill('0') << (int)digest[i];
    }
    return ss.str();
}

OrderGateway::OrderGateway(std::string key, std::string secret, bool testnet) 
    : api_key_(key), api_secret_(secret) 
{
    ix::initNetSystem();
    url_ = testnet ? "wss://stream-testnet.bybit.com/v5/trade" 
                   : "wss://stream.bybit.com/v5/trade";
    webSocket.setUrl(url_);
    webSocket.setPingInterval(20); 
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
}

void OrderGateway::stop() {
    webSocket.stop();
}

void OrderGateway::set_on_order_update(std::function<void(const std::string&)> cb) {
    on_order_update_cb_ = cb;
}

std::string OrderGateway::generate_signature(long long expires) {
    std::string val = "GET/realtime" + std::to_string(expires);
    return hmac_sha256(api_secret_, val);
}

void OrderGateway::authenticate() {
    auto now = std::chrono::system_clock::now();
    long long expires = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count() + 5000;
    std::string signature = generate_signature(expires);
    
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
    nlohmann::json order;
    order["category"] = "linear";
    order["symbol"] = symbol;
    order["side"] = side; 
    order["orderType"] = "Limit";
    order["qty"] = std::to_string(qty); 
    order["price"] = std::to_string(price);
    order["timeInForce"] = "PostOnly"; 

    nlohmann::json msg;
    msg["op"] = "order.create"; 
    msg["args"] = {order};
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
        try {
            auto j = nlohmann::json::parse(msg->str);
            
            // [CRITICAL FIX] Поддержка обоих форматов ответа (success: true ИЛИ retCode: 0)
            if (j.contains("op") && j["op"] == "auth") {
                bool ok_bool = j.value("success", false);
                int ret_code = j.value("retCode", -1);
                
                if (ok_bool || ret_code == 0) {
                    authenticated_ = true;
                    std::cout << "[C++] ✅ AUTH SUCCESS! Ready to trade." << std::endl;
                } else {
                    std::cerr << "[C++] ❌ AUTH FAILED: " << msg->str << std::endl;
                }
            }
            
            if (on_order_update_cb_) {
                on_order_update_cb_(msg->str);
            }
        } catch (...) {}
    }
    else if (msg->type == ix::WebSocketMessageType::Error) {
        std::cerr << "[C++] WS Error: " << msg->errorInfo.reason << std::endl;
    }
}