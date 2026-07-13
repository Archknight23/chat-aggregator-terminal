@echo off
REM Build standalone executable for Windows
REM Requires: Python 3.11+, Node.js 18+, pip, npm

echo [1/5] Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

echo [2/5] Installing Python dependencies...
python -m pip install --upgrade pip
pip install -e ".[dev]"
pip install pyinstaller

echo [3/5] Installing Node.js dependencies...
npm install

echo [4/5] Building Python executable with PyInstaller...
pyinstaller --clean chat_aggregator.spec

echo [5/5] Verifying build...
if exist "dist\chat-aggregator.exe" (
    echo √ Executable built: dist\chat-aggregator.exe
    echo.
    echo Distribution contents:
    echo   - dist\chat-aggregator.exe (Python TUI executable)
    echo   - server\ (Node.js backend - run with 'npm run server')
    echo   - package.json, pyproject.toml (for source installs)
    echo.
    echo To test locally:
    echo   cd dist ^&^& chat-aggregator.exe
    echo.
    echo Note: The Node.js backend still requires Node.js 18+ at runtime.
    echo Users can either:
    echo   1. Install Node.js and run 'npm install ^&^& npm run server' alongside the executable
    echo   2. Use the source install method (pip install -e .)
) else (
    echo x Build failed - dist\chat-aggregator.exe not found
    exit /b 1
)
