@echo off
chcp 65001 >nul
title iFlyCompass 项目启动器
cd /d "%~dp0"

echo ========================================
echo        iFlyCompass 项目启动器
echo ========================================
echo.

echo [1/4] 正在检查 Python 环境...
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [错误] 未检测到 Python，请先安装
    pause
    exit /b 1
)
echo   [成功] Python 已安装
echo.

echo [2/4] 正在检查并终止旧进程...
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq pythonw.exe" /NH 2^>nul ^| find /I "pythonw.exe"') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo   [完成] 旧进程已清理
echo.

echo [3/4] 正在启动 app.py...
start "" /B pythonw app.py

echo   等待服务启动...
timeout /t 3 /nobreak >nul

echo.
echo [4/4] 正在检查启动状态...
tasklist /FI "IMAGENAME eq pythonw.exe" /NH 2>nul | find /I "pythonw.exe" >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo      [成功] 项目已成功启动！
    echo ========================================
    echo.
    echo 提示：项目正在后台运行
    echo 如需停止，请运行停止脚本或手动结束 pythonw.exe 进程
) else (
    echo.
    echo ========================================
    echo      [错误] 项目启动失败！
    echo ========================================
    echo.
    echo 请检查：
    echo   1. Python 是否正确安装
    echo   2. 项目依赖是否完整 ^(pip install -r requirements.txt^)
    echo   3. 端口是否被占用
    echo.
    pause
    exit /b 1
)

echo.
echo 窗口将在 3 秒后自动关闭...
timeout /t 3 /nobreak >nul
exit /b 0
