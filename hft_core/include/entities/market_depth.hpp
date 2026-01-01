#pragma once
#include <vector>
#include <string>

struct PriceLevel {
    double price;
    double qty;
};

struct OrderBookSnapshot {
    std::string symbol;
    std::vector<PriceLevel> bids;
    std::vector<PriceLevel> asks;
    long long timestamp; // Биржевое время
    long long u;         // Update ID
    
    // Поля, которые заполняет парсер
    long long local_timestamp; 
    bool is_snapshot;
};