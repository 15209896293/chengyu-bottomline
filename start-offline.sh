#!/usr/bin/env bash
# 城域底线 · 离线演示版启动器（macOS / Linux）
cd "$(dirname "$0")/dashboard/dist"
echo "城域底线 · 离线演示版: http://localhost:8080"
python3 -m http.server 8080
