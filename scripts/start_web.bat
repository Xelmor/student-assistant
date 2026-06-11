@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

echo [1/4] Проверка Python...
where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PYTHON_CMD=python"
    ) else (
        echo Не найден Python.
        echo Установи Python 3.11+ и включи опцию "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

echo [2/4] Подготовка виртуального окружения...
if not exist "venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
)

echo [3/4] Установка зависимостей...
venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
    echo Ошибка при обновлении pip.
    pause
    exit /b 1
)

venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo Ошибка при установке зависимостей.
    pause
    exit /b 1
)

echo [4/4] Запуск сайта...
echo Открой в браузере: http://127.0.0.1:8000
venv\Scripts\python.exe run.py

pause
