"""Local process names and icons; never expose paths, PIDs or command lines."""
import io
import ntpath
from functools import lru_cache
from pathlib import Path
from engine.routing_rules import BLOCKED_PROCESSES


def process_catalog():
    import psutil
    from engine.apps import POPULAR_APPS
    friendly={p['exe'].lower():p['name'] for p in POPULAR_APPS}
    found={}
    for process in psutil.process_iter(['name']):
        name=process.info.get('name') or ''
        if not name.lower().endswith('.exe') or name.lower() in BLOCKED_PROCESSES:continue
        found[name.lower()]=dict(exe=name,name=friendly.get(name.lower(),name[:-4]))
    return sorted(found.values(),key=lambda p:p['name'].lower())[:500]


def process_icon(name):
    import psutil
    if not isinstance(name,str) or ntpath.basename(name)!=name or name.lower() in BLOCKED_PROCESSES or not name.lower().endswith('.exe'):return None
    for process in psutil.process_iter(['name','exe']):
        if (process.info.get('name') or '').lower()!=name.lower():continue
        path=process.info.get('exe')
        if not path or path.startswith('\\\\'):continue
        try:return _icon(path,Path(path).stat().st_mtime_ns)
        except Exception:continue
    return None


@lru_cache(maxsize=128)
def _icon(path,mtime):
    import win32gui
    import win32ui
    from PIL import Image
    large,small=win32gui.ExtractIconEx(path,0)
    icons=large+small
    if not icons:return None
    dc=memory=bitmap=None
    try:
        dc=win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        memory=dc.CreateCompatibleDC();bitmap=win32ui.CreateBitmap();bitmap.CreateCompatibleBitmap(dc,32,32)
        old=memory.SelectObject(bitmap)
        memory.FillSolidRect((0,0,32,32),0x29213d)
        win32gui.DrawIconEx(memory.GetSafeHdc(),0,0,icons[0],32,32,0,None,3)
        pixels=bitmap.GetBitmapBits(True)
        image=Image.frombuffer('RGB',(32,32),pixels,'raw','BGRX',0,1)
        output=io.BytesIO();image.save(output,format='PNG')
        memory.SelectObject(old)
        return output.getvalue()
    finally:
        if bitmap:win32gui.DeleteObject(bitmap.GetHandle())
        if memory:memory.DeleteDC()
        if dc:win32gui.ReleaseDC(0,dc.GetSafeHdc())
        for icon in icons:win32gui.DestroyIcon(icon)
