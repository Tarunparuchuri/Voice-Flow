import os
import sys
import ctypes
import subprocess
from PySide6.QtWidgets import QApplication

def create_desktop_shortcut():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        
    project_dir = os.path.dirname(os.path.abspath(__file__))
    import config
    from widgets import get_rounded_pixmap
    
    logo_path = config.LOGO_PATH
    ico_path = os.path.join(project_dir, "voiceflow_app.ico")
    pythonw_path = os.path.join(project_dir, ".venv", "Scripts", "pythonw.exe")
    main_py_path = os.path.join(project_dir, "main.py")
    
    # Get user desktop directory
    desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    shortcut_path = os.path.join(desktop_dir, "Voice Flow.lnk")
    
    # 1. Generate high-res 256x256 rounded ico file with curved edges from Logo.png
    if os.path.exists(logo_path):
        pixmap = get_rounded_pixmap(logo_path, size=256, radius=52, padding=16)
        pixmap.save(ico_path, "ICO")
        print(f"Generated curved desktop icon from {logo_path} at: {ico_path}")
        
    # 2. Create/Update Windows Desktop Shortcut (.lnk) using PowerShell WScript.Shell
    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $Shortcut = $WshShell.CreateShortcut("$DesktopPath\\Voice Flow.lnk")
    $Shortcut.TargetPath = '{pythonw_path}'
    $Shortcut.Arguments = '"{main_py_path}"'
    $Shortcut.WorkingDirectory = '{project_dir}'
    $Shortcut.IconLocation = '{ico_path},0'
    $Shortcut.Description = 'Voice Flow - Voice Typist & AI Assistant'
    $Shortcut.Save()
    """
    
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # 3. Force Windows Explorer Shell to immediately flush IconCache and reload desktop icons
    if sys.platform == "win32":
        try:
            # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_FLUSH = 0x1000
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)
            print("Notified Windows Shell to refresh desktop icon cache.")
        except Exception as e:
            print(f"Shell notify warning: {e}")
            
    if result.returncode == 0 and os.path.exists(shortcut_path):
        print(f"Successfully created Desktop shortcut at: {shortcut_path}")
        return True
    else:
        print(f"Error creating shortcut: {result.stderr}")
        return False

if __name__ == "__main__":
    create_desktop_shortcut()
