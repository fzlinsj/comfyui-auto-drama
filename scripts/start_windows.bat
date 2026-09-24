@echo off
rem Windows 前台启动控制台（后台常驻请用 python start_daemons.py）
chcp 65001 >nul
rem 只清理占用控制台端口的旧进程，避免更新代码后仍连接旧后端
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p = (Get-NetTCPConnection -LocalPort 8890 -State Listen -ErrorAction SilentlyContinue).OwningProcess; if ($p) { Stop-Process -Id $p -Force }"
cd /d "%~dp0..\console"
echo 正在启动控制台: http://127.0.0.1:8890
python batch_console.py 8890
pause
