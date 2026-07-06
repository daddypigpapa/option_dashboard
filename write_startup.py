import os

startup_dir = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
vbs_path = os.path.join(startup_dir, 'start_dashboard.vbs')
bat_in_startup = os.path.join(startup_dir, 'start_dashboard.bat')

content = 'Set WshShell = CreateObject("WScript.Shell")\nresult = WshShell.Run("C:\\Users\\leejaegeon\\claude\\dashboard_project\\start_dashboard.bat", 0, True)\n'

try:
    # Delete the test batch file in the Startup folder if it exists
    if os.path.exists(bat_in_startup):
        os.remove(bat_in_startup)
    
    with open(vbs_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Success: start_dashboard.vbs successfully written to Startup folder!")
    print("Path:", vbs_path)
except Exception as e:
    print("Error writing startup script:", e)
