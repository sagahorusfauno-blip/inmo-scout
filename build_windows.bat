@echo off
REM Genera dist\InmoScout\InmoScout.exe  (ejecutar en Windows con Python 3.11+)
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements-dev.txt
pyinstaller --noconfirm --windowed --name InmoScout ^
  --collect-submodules app ^
  --add-data "app/ui/assets;app/ui/assets" ^
  main.py
echo.
echo Listo: dist\InmoScout\InmoScout.exe
