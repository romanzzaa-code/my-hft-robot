# Dockerfile
FROM python:3.11-slim

# Ставим инструменты для сборки C++ (gcc, cmake)
RUN apt-get update && \
    apt-get install -y gcc g++ cmake make git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала копируем зависимости (для кэширования)
COPY requirements.txt .
COPY pyproject.toml .

# Устанавливаем библиотеки Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта
COPY . .

# Компилируем C++ ядро (hft_core)
RUN pip install .

# Запускаем робота
CMD ["python", "-u", "hft_strategy/live_bot.py"]