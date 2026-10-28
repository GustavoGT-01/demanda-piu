@echo off
rem Cria a tarefa agendada "Central de demandas": a Central liga sozinha quando o Windows liga (antes de alguem
rem entrar) e religa se parar. Rode UMA vez com o botao direito > "Executar como administrador".
rem Pede a senha da conta que vai rodar a Central (a sua). Para desfazer: remover-inicio.bat.
cd /d "%~dp0"
title Central de demandas - iniciar com o Windows

net session >nul 2>nul
if errorlevel 1 (
  echo ERRO: rode este arquivo como administrador: botao direito ^> "Executar como administrador".
  pause
  exit /b 1
)

set "PY="
set "PYARG="
where py >nul 2>nul && set "PY=py" && set "PYARG=-3"
if not defined PY if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
if not defined PY set "PY=python"
"%PY%" %PYARG% -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 (
  echo ERRO: e preciso o Python 3.10 ou mais novo, e ele nao foi encontrado.
  pause
  exit /b 1
)
rem caminho completo do python.exe: a tarefa roda sem o PATH desta janela
"%PY%" %PYARG% -c "import sys; print(sys.executable)" > "%TEMP%\central-python.txt"
set /p PYEXE=<"%TEMP%\central-python.txt"
del "%TEMP%\central-python.txt" >nul 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-inicio.ps1" -Python "%PYEXE%"
echo.
pause
