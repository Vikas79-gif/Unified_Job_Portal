@echo off
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting Unified Job Portal...
echo.
echo Admin Login:
echo Username: admin
echo Password: admin123
echo.
echo Open your browser and go to: http://localhost:5000
echo.
python app.py
pause

