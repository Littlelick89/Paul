@echo off
chcp 65001 > nul
title RAG Education Q&A Server

echo ============================================================
echo  RAG Education Q^&A Server
echo  Chat:  http://localhost:5000/
echo  Admin: http://localhost:5000/admin
echo ============================================================
echo.

cd /d "%~dp0"
python rag_app.py

echo.
echo 서버가 종료되었습니다.
pause
