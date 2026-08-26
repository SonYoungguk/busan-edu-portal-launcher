@echo off
chcp 65001 >nul
pip install -r requirements.txt
pyinstaller --onefile --noconsole --name EduPortalLauncher ^
    --exclude-module tkinter ^
    --exclude-module unittest ^
    --exclude-module pydoc ^
    --exclude-module doctest ^
    --exclude-module distutils ^
    --exclude-module xmlrpc ^
    --exclude-module lib2to3 ^
    --exclude-module test ^
    main.py
echo.
echo Build done: dist\EduPortalLauncher.exe (copy just this one file to use it)
echo Only add config.json next to the exe if you want to override the defaults.
