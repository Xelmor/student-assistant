#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "[1/4] Проверка Python..."
if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="python"
else
  echo "Python не найден. Установи Python 3.11+."
  exit 1
fi

echo "[2/4] Подготовка виртуального окружения..."
if [ ! -f "venv/bin/python" ]; then
  "$PYTHON_CMD" -m venv venv
fi

echo "[3/4] Установка зависимостей..."
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt

echo "[4/4] Запуск сайта..."
echo "Открой в браузере: http://127.0.0.1:8000"
venv/bin/python run.py
