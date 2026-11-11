@echo off
title Renewal Blood Network Admin Panel (Port 8081)
echo ===================================================
echo   Starting Admin Panel on Port 8081...
echo ===================================================
cd admin
python server.py --port 8081
pause
