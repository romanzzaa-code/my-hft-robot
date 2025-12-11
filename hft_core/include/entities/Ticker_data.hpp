// hft_core/include/entities/ticker_data.hpp
#pragma once
#include <string>

struct TickerData {
    std::string symbol;
    double last_price;
    double turnover_24h;    // Оборот в валюте котировки (USDT)
    double price_24h_pcnt;  // Изменение цены за 24ч
    long long timestamp;
};