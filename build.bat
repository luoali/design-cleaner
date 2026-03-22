@echo off
cd /d "%~dp0"

echo ============================================
echo   Design Cleaner - Build Script
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [Error] Python not found.
    echo Please install Python 3.9+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/3] Installing dependencies...
pip install customtkinter send2trash pyinstaller -q

echo [2/3] Finding customtkinter path...
python -c "import customtkinter, os; open('_ctk_path.txt','w').write(os.path.dirname(customtkinter.__file__))"
set /p CTK_PATH=<_ctk_path.txt
del _ctk_path.txt
echo     Found: %CTK_PATH%
echo.

echo [3/3] Building exe (this may take 1-3 minutes)...
pyinstaller --onefile --windowed --name "DesignCleaner" --add-data "%CTK_PATH%;customtkinter" design_cleaner.py

if exist "dist\DesignCleaner.exe" (
    echo.
    echo ============================================
    echo   Build successful!
    echo   Output: dist\DesignCleaner.exe
    echo ============================================
) else (
    echo.
    echo [Error] Build failed. See messages above.
)
echo.
pause
