@echo off
cd /d "C:\Users\leejaegeon\claude\dashboard_project"
.venv\Scripts\python.exe -m webapp.app > server.log 2>&1
