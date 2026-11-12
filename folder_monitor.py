# -*- coding: utf-8 -*-
"""
FolderChecker — следит за папкой и уведомляет о новых файлах.

- Иконка в трее (правый клик — меню: Настройки / Выход).
- Проверка папки каждые 10 секунд.
- При появлении нового файла — модальное системное окно (нельзя проигнорировать, закрывается только по ОК).
- При клике по иконке трея — окно настроек, где задаётся путь к папке.
- Путь сохраняется в %APPDATA%\\FolderChecker\\config.json (права на запись в папку программы не нужны).

Запуск (без консоли):  pythonw.exe folder_monitor.py
"""

import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, filedialog

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Не установлены pystray и pillow. Выполните: pip install pystray pillow")
    sys.exit(1)

APP_NAME = "FolderChecker"
CHECK_INTERVAL = 10  # секунд


def get_config_dir():
    r"""Папка для настроек — %APPDATA%\FolderChecker (или в домашней папке как запасной вариант)."""
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


CONFIG_FILE = os.path.join(get_config_dir(), "config.json")


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"folder": ""}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # Не роняем программу, если вдруг нет прав даже в APPDATA
        print(f"Не удалось сохранить настройки: {e}")


def make_icon_image():
    """Синяя папка на белом фоне, 64x64."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # тело папки
    d.rectangle([6, 18, 58, 54], fill=(66, 133, 244, 255))
    # откидная часть
    d.rectangle([6, 10, 30, 20], fill=(66, 133, 244, 255))
    d.rectangle([10, 12, 26, 18], fill=(96, 160, 250, 255))
    d.rectangle([8, 22, 56, 52], fill=(96, 160, 250, 255))
    return img


class SettingsWindow:
    """Окно настроек с выбором папки."""

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title(f"{APP_NAME} — настройки")
        self.win.geometry("520x150")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        tk.Label(self.win, text="Папка для мониторинга:").pack(anchor="w", padx=10, pady=(12, 2))

        row = tk.Frame(self.win)
        row.pack(fill="x", padx=10)
        self.var = tk.StringVar(value=app.config.get("folder", ""))
        tk.Entry(row, textvariable=self.var, width=55).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Обзор…", command=self.browse).pack(side="left", padx=(6, 0))

        btns = tk.Frame(self.win)
        btns.pack(fill="x", padx=10, pady=16)
        tk.Button(btns, text="Сохранить", width=12, command=self.save).pack(side="right")
        tk.Button(btns, text="Закрыть", width=12, command=self.close).pack(side="right", padx=(0, 6))

        self.win.update_idletasks()

    def browse(self):
        folder = filedialog.askdirectory(parent=self.win, initialdir=self.var.get() or os.path.expanduser("~"))
        if folder:
            self.var.set(folder)

    def save(self):
        path = self.var.get().strip()
        if path and not os.path.isdir(path):
            messagebox.showerror("Ошибка", "Такой папки не существует.", parent=self.win)
            return
        self.app.config["folder"] = path
        save_config(self.app.config)
        self.app.reset_baseline()
        self.close()

    def close(self):
        self.win.destroy()
        self.app.settings_window = None


class FolderMonitorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # главное окно скрыто — работаем из трея
        self.config = load_config()
        self.known_files = set()
        self.settings_window = None
        self._pending_alerts = []
        self.reset_baseline()

        # Трей
        self.icon = pystray.Icon(
            APP_NAME,
            make_icon_image(),
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("Настройки", self.open_settings, default=True),
                pystray.MenuItem("Проверить сейчас", lambda: self.check_once()),
                pystray.MenuItem("Выход", self.quit),
            ),
        )
        threading.Thread(target=self.icon.run, daemon=True).start()

        # Цикл проверки — через after, чтобы всё было в одном потоке tkinter
        self.root.after(500, self.check_loop)
        self.root.mainloop()

    # ---------- мониторинг ----------

    def reset_baseline(self):
        folder = self.config.get("folder", "")
        self.known_files = self.scan(folder)

    def scan(self, folder):
        try:
            return set(os.listdir(folder))
        except Exception:
            return set()

    def check_once(self):
        """Один проход проверки. Возвращает список новых файлов."""
        folder = self.config.get("folder", "")
        if not folder:
            return []
        current = self.scan(folder)
        new_files = sorted(current - self.known_files)
        self.known_files = current
        return new_files

    def check_loop(self):
        try:
            new_files = self.check_once()
            for name in new_files:
                self.show_alert(name)
        finally:
            self.root.after(CHECK_INTERVAL * 1000, self.check_loop)

    def show_alert(self, filename):
        folder = self.config.get("folder", "")
        # messagebox модален — закрывается только ОК
        messagebox.showinfo(
            "Новый файл!",
            f"В папке появился новый файл:\n\n{filename}\n\nПуть: {folder}",
            parent=self.root,
        )

    # ---------- GUI ----------

    def open_settings(self, icon=None, item=None):
        # tkinter не потокобезопасен — вызываем через after из потока трея
        self.root.after(0, self._open_settings_ui)

    def _open_settings_ui(self):
        if self.settings_window is not None and self.settings_window.win.winfo_exists():
            self.settings_window.win.lift()
            return
        self.settings_window = SettingsWindow(self)

    def quit(self, icon=None, item=None):
        self.root.after(0, self._quit_ui)

    def _quit_ui(self):
        try:
            self.icon.stop()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    FolderMonitorApp()
