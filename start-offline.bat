@echo off
chcp 65001 >nul
title 城域底线 - 离线演示版
echo ============================================
echo   城域底线 · 城市生命线压测诊断系统
echo   离线演示版启动器
echo ============================================
echo.
cd /d "%~dp0dashboard\dist"
echo 启动本地服务: http://localhost:8080
echo 关闭窗口即停止服务
echo.
start "" http://localhost:8080
python -m http.server 8080
