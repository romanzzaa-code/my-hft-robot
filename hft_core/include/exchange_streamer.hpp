#pragma once

#include <string>
#include <vector>
#include <thread>


struct TickData {
    std::string symbol;
    double price;
    double volume;
    long long timestamp;
};

class ExchangeStreamer {
public:
    ExchangeStreamer();
    ~ExchangeStreamer();

    void connect(std::string url);
    void start();

private:
    std::vector<std::string> urls;
    std::thread app_thread;
    bool running;
};