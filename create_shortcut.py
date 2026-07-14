import os
from win32com.client import Dispatch

project_dir = os.path.dirname(os.path.abspath(__file__))
exe_path    = os.path.join(project_dir, "dist", "SadnessVPN", "SadnessVPN.exe")
icon_path   = os.path.join(project_dir, "app.ico")
desktop     = r"C:\Users\andre\OneDrive\Desktop"

# Удаляем старые ярлыки
for old_name in ["Snow VPN.lnk", "Sadness VPN.lnk"]:
    old = os.path.join(desktop, old_name)
    if os.path.exists(old):
        os.remove(old)
        print(f"Удалён старый ярлык: {old_name}")

shell    = Dispatch('WScript.Shell')
shortcut = shell.CreateShortCut(os.path.join(desktop, "Sadness VPN.lnk"))
shortcut.Targetpath       = exe_path
shortcut.Arguments        = ""
shortcut.WorkingDirectory = os.path.join(project_dir, "dist", "SadnessVPN")
shortcut.IconLocation     = icon_path
shortcut.Description      = "Sadness VPN"
shortcut.save()

print("Готово! Ярлык создан на рабочем столе.")