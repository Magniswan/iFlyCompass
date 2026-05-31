@echo off
chcp 65001 >nul
title iFlyCompass 项目更新工具
cd /d "%~dp0"

echo ========================================
echo      iFlyCompass 项目更新工具
echo ========================================
echo.

echo [1/4] 检查 Git 是否安装...
where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================
    echo         [错误] 未检测到 Git！
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
    echo      [错误] 非 Git 仓库目录！
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
git diff --quiet 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo   [提示] 检测到本地有未提交的修改
    echo   正在暂存本地修改...
    git stash >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo   [错误] 暂存失败，请手动处理后再试
        pause
        exit /b 1
    )
    set "STASHED=1"
    echo   [成功] 本地修改已暂存
) else (
    set "STASHED=0"
    echo   [成功] 工作区干净
)
echo.

echo [4/4] 正在从远程仓库拉取更新...
echo.
git pull
set PULL_EXIT_CODE=%ERRORLEVEL%

if "%STASHED%"=="1" (
    echo.
    echo   正在恢复本地修改...
    git stash pop >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo   [警告] 恢复本地修改时出现冲突，请手动解决
        echo   可运行 git stash list 查看暂存记录
    ) else (
        echo   [成功] 本地修改已恢复
    )
)

echo.
echo ========================================
if %PULL_EXIT_CODE% EQU 0 (
    echo         [成功] 更新完成！
    echo ========================================
    echo.
    echo 提示：代码已成功从远程仓库更新
    echo 如有需要，请重新启动应用程序
) else (
    echo         [错误] 更新失败！
    echo ========================================
    echo.
    echo 可能原因：
    echo   - 网络连接问题
    echo   - 远程仓库不可访问
    echo   - 合并冲突
    echo.
    echo 建议：
    echo   1. 运行 git status 查看详细状态
    echo   2. 运行 git log 查看提交历史
    echo   3. 如有冲突，请手动解决后再更新
)

echo.
echo 按任意键退出...
pause >nul
exit /b %PULL_EXIT_CODE%
