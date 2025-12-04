# Используем официальный образ Python 3.11 с оптимизациями
FROM python:3.11-slim

# Устанавливаем компиляторы и CMake (для сборки C++ модуля)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc g++ cmake make pkg-config git wget curl && \
    rm -rf /var/lib/apt/lists/*

# Устанавливаем pybind11 через pip (будет использоваться для биндингов)
RUN pip install pybind11

# Копируем всю папку проекта внутрь контейнера (кроме .git и .dockerignore)
COPY . /app

# Переходим в папку проекта
WORKDIR /app

# Устанавливаем зависимости Python (если будут)
# RUN pip install -r requirements.txt

# Команда по умолчанию — просто показать, что всё работает
CMD ["python", "-c", "print('✅ Dockerfile работает!')"]