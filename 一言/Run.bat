@echo off
:: 切到 UTF-8 代码页
chcp 65001 >nul
title Smart-Vocab
echo 正在启动 A word ...
python "%~dp0A word.py"
pause