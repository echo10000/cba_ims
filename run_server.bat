@echo off
title CBA IMS Development Server
cd /d "C:\Users\PERSONAL\Desktop\cba_ims"
echo ===================================================
echo Starting CBA IMS Development Server...
echo URL: http://127.0.0.1:8000/
echo Press Ctrl+C or close this window to stop the server.
echo ===================================================
echo.
call ".\venv\Scripts\activate.bat"
python manage.py runserver 127.0.0.1:8000
pause
