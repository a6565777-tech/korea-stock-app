@echo off
schtasks /create /tn "StockBrief_Overnight" /tr "\"%~dp0run_briefing.bat\" overnight" /sc DAILY /st 00:00 /f
schtasks /query /tn "StockBrief_Overnight" /fo LIST
