@echo off
chcp 65001 >nul
title iFlyCompass 项目启动器

echo ========================================
echo        iFlyCompass 项目启动器
echo ========================================
echo.

echo [1/3] 正在检查并终止正在运行的 app.py 进程...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq app.py*" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   [成功] 已终止所有正在运行的 app.py 进程
) else (
    echo   [提示] 未找到正在运行的 app.py 进程
)

echo.
echo [2/3] 正在启动 app.py（静默模式）...
start /B pythonw app.py

timeout /t 2 /nobreak >nul

echo.
echo [3/3] 正在检查启动状态...
tasklist /FI "IMAGENAME eq pythonw.exe" 2>NUL | find /I /N "pythonw.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo.
    echo ========================================
    echo      [SUCCESS] 项目已成功启动！
    echo ========================================
    echo.
    echo 提示：项目正在后台运行
    echo 如需停止，请运行停止脚本或手动结束 pythonw.exe 进程
    echo.
) else (
    echo.
    echo ========================================
    echo      [ERROR] 项目启动失败！
    echo ========================================
    echo.
    echo 请检查：
    echo 1. Python 是否正确安装
    echo 2. 项目依赖是否完整（pip install -r requirements.txt）
    echo 3. 端口是否被占用
    echo.
    pause
    exit /b 1
)

echo 窗口将在 3 秒后自动关闭...
timeout /t 3 /nobreak >nul
exit
