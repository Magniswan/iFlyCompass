@echo off
chcp 65001 >nul
title iFlyCompass 项目更新工具

echo ========================================
echo      iFlyCompass 项目更新工具
echo ========================================
echo.

cd /d "%~dp0"

echo [1/4] 检查 Git 是否安装...
where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================
    echo         [ERROR] 未检测到 Git！
    echo ========================================
    echo.
    echo 请先安装 Git：https://git-scm.com/
    echo.
    pause
    exit /b 1
)

echo   [成功] Git 已安装
echo.

echo [2/4] 检查是否为 Git 仓库...
if not exist ".git" (
    echo.
    echo ========================================
    echo      [ERROR] 非 Git 仓库目录！
    echo ========================================
    echo.
    echo 请确保在项目根目录下运行此脚本
    echo.
    pause
    exit /b 1
)

echo   [成功] 当前目录为 Git 仓库
echo.

echo [3/4] 检查本地状态...
git status --short
echo.

echo [4/4] 正在从远程仓库拉取更新...
echo.
git pull
set PULL_EXIT_CODE=%ERRORLEVEL%

echo.
echo ========================================
if %PULL_EXIT_CODE% EQU 0 (
    echo         [SUCCESS] 更新完成！
    echo ========================================
    echo.
    echo 提示：代码已成功从远程仓库更新
    echo 如有需要，请重新启动应用程序
) else (
    echo         [ERROR] 更新失败！
    echo ========================================
    echo.
    if %PULL_EXIT_CODE% EQU 1 (
        echo 可能原因：
        echo - 本地有未提交的修改导致冲突
        echo - 网络连接问题
        echo - 远程仓库不可访问
        echo.
        echo 建议：
        echo 1. 运行 'git status' 查看详细状态
        echo 2. 如有冲突，请手动解决后再更新
    )
)

echo.
echo 按任意键退出...
pause >nul
exit
