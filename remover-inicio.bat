@echo off
rem Apaga a tarefa agendada "Central de demandas" (a Central deixa de ligar sozinha com o Windows).
rem A Central que ja esta ligada continua ate o PC desligar. Rode como administrador.
cd /d "%~dp0"
net session >nul 2>nul
if errorlevel 1 (
  echo ERRO: rode este arquivo como administrador: botao direito ^> "Executar como administrador".
  pause
  exit /b 1
)
schtasks /delete /tn "Central de demandas" /f
pause
