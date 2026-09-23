"""Explicit HWND PrintWindow capture. Never grabs the desktop or a camera."""
import ctypes
from ctypes import wintypes as w
import io
import os
from PIL import Image, ImageDraw, ImageStat


def game_process_running():
    """Count a minimized/hidden match too; a missing foreground window is not absence."""
    import psutil
    return any((p.info.get('name') or '').lower()=='league of legends.exe'
               for p in psutil.process_iter(['name']))


def executable_name(hwnd):
    u,k=ctypes.windll.user32,ctypes.windll.kernel32
    pid=w.DWORD()
    u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]
    k.OpenProcess.restype=w.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.OpenProcess(0x1000,False,pid.value)
    if not handle:
        return None
    try:
        path=ctypes.create_unicode_buffer(32768)
        length=w.DWORD(len(path))
        if k.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(length)):
            return path.value.rsplit('\\',1)[-1].lower()
        return None
    finally:
        k.CloseHandle(handle)


def windows():
    if os.name != 'nt':
        return []
    u = ctypes.windll.user32
    result = []
    callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def visit(hwnd, _):
        if u.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, title, 512)
            if title.value and any(x in title.value.lower() for x in ('league of legends', '英雄联盟')):
                executable=executable_name(hwnd)
                result.append({'hwnd': int(hwnd), 'title': title.value,
                               'is_game':executable=='league of legends.exe',
                               'executable':executable})
        return True
    u.EnumWindows(callback(visit), 0)
    return result


class Capture:
    def __init__(self):
        self.hwnd = None
        self.previous = None
        self.change = 1.0
        self.title = None
        self.pid = None
        self.width = self.height = None

    def select(self, hwnd):
        selected = next((x for x in windows() if x['hwnd'] == hwnd), None)
        if not selected:
            raise ValueError('请选择当前可见的 LOL 游戏窗口')
        if not selected.get('is_game'):
            raise ValueError('这是 LOL 大厅或未确认的窗口，请进入对局后选择游戏窗口')
        self.hwnd, self.title = hwnd, selected['title']
        pid = w.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        self.pid = pid.value
        self.previous = None

    def grab(self):
        import numpy as np
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        if not self.hwnd or not u.IsWindow(self.hwnd) or u.IsIconic(self.hwnd):
            raise RuntimeError('游戏窗口未选择或已最小化')
        u.GetForegroundWindow.restype = w.HWND
        if u.GetForegroundWindow() != self.hwnd:
            raise RuntimeError('游戏不在前台，暂停窗口采集')
        pid = w.DWORD()
        u.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        if pid.value != self.pid:
            raise RuntimeError('窗口进程已改变，请重新选择')
        rect = w.RECT()
        u.GetClientRect(self.hwnd, ctypes.byref(rect))
        width, height = rect.right, rect.bottom
        if width < 300 or height < 200 or width*height > 16000000:
            raise RuntimeError('无效游戏窗口尺寸')
        self.width,self.height=width,height
        u.GetDC.restype = w.HDC
        g.CreateCompatibleDC.argtypes = [w.HDC]
        g.CreateCompatibleDC.restype = w.HDC
        g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
        g.CreateCompatibleBitmap.restype = w.HBITMAP
        g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
        g.SelectObject.restype = w.HGDIOBJ
        g.DeleteObject.argtypes = [w.HGDIOBJ]
        g.DeleteDC.argtypes = [w.HDC]
        u.ReleaseDC.argtypes = [w.HWND, w.HDC]
        u.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
        class BI(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG),
                        ('planes', w.WORD), ('bits', w.WORD), ('compression', w.DWORD),
                        ('image_size', w.DWORD), ('xppm', w.LONG), ('yppm', w.LONG),
                        ('used', w.DWORD), ('important', w.DWORD)]
        dc = u.GetDC(self.hwnd)
        mem = g.CreateCompatibleDC(dc)
        bmp = g.CreateCompatibleBitmap(dc, width, height)
        old = g.SelectObject(mem, bmp)
        try:
            if not u.PrintWindow(self.hwnd, mem, 3):
                raise RuntimeError('PrintWindow 失败，无桌面截屏回退')
            info = BI(ctypes.sizeof(BI), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
            raw = ctypes.create_string_buffer(width*height*4)
            g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.c_void_p, w.UINT]
            if not g.GetDIBits(mem, bmp, 0, height, raw, ctypes.byref(info), 0):
                raise RuntimeError('读取窗口像素失败')
            im = Image.frombuffer('RGB', (width,height), raw.raw, 'raw', 'BGRX', 0, 1)
        finally:
            g.SelectObject(mem, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mem)
            u.ReleaseDC(self.hwnd, dc)
        if max(ImageStat.Stat(im.resize((32,32))).mean) < 3:
            raise RuntimeError('窗口黑屏，画面无效')
        # Mask standard chat and top-right desktop-overlay notification zones.
        draw = ImageDraw.Draw(im)
        draw.rectangle((0,height*.45,width*.31,height*.91), fill='black')
        draw.rectangle((width*.8,0,width,height*.16), fill='black')
        small = np.asarray(im.resize((64,36)), dtype=np.float32)
        self.change = 1.0 if self.previous is None else float(np.mean(np.abs(small-self.previous))/255)
        self.previous = small
        im.thumbnail((1280,720))
        out = io.BytesIO()
        im.save(out, format='JPEG', quality=72)
        return out.getvalue()
