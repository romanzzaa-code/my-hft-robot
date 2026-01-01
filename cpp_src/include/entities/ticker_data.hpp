#pragma once
#include <string>

struct TickerData {
    std::string symbol;
    double best_bid;
    double best_ask;
    double turnover_24h;
    double volume_24h;
    
    // Поля, которые заполняет парсер
    double last_price;
    double price_24h_pcnt;
    long long timestamp;
};