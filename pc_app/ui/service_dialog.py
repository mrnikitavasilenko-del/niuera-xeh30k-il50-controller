"""Service dialog: detailed per-module data table (Block 4)."""
import tkinter as tk
from tkinter import ttk

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import protocol


_ROWS = [
    ('Вход A-B, В',            lambda m, _: f"{m['vab']:.1f}"),
    ('Вход B-C, В',            lambda m, _: f"{m['vbc']:.1f}"),
    ('Вход C-A, В',            lambda m, _: f"{m['vca']:.1f}"),
    ('Температура, °C',        lambda m, _: str(m['temperature'])),
    ('Уставка напряжения, В',  lambda m, s: f"{s['set_voltage']:.0f}"),
    ('Выходное напряжение, В', lambda m, _: f"{m['output_voltage']:.1f}"),
    ('Уставка тока, А',        lambda m, s: f"{s['set_current']:.0f}"),
    ('Выходной ток, А',        lambda m, _: f"{m['output_current']:.1f}"),
    ('Выходная мощность, кВт', lambda m, _: f"{m['output_voltage'] * m['output_current'] / 1000.0:.2f}"),
    ('Статус (5 кодов)',       lambda m, _: _fmt_history(m['history'])),
]


def _fmt_history(history: list) -> str:
    return '   '.join('—' if c is None else f'{c:02d}' for c in history)


class ServiceDialog(tk.Toplevel):
    def __init__(self, parent, model):
        super().__init__(parent)
        self.title('Сервисная информация')
        self.resizable(False, False)
        self.transient(parent)
        self._model = model
        self._build()
        self._center(parent)
        self._refresh()

    def _center(self, parent):
        self.update_idletasks()
        # Place to the right of the parent window
        px = parent.winfo_rootx() + parent.winfo_width() + 10
        py = parent.winfo_rooty()
        # If it goes off-screen, fall back to center
        sw = self.winfo_screenwidth()
        if px + self.winfo_width() > sw:
            px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        self.geometry(f'+{px}+{py}')

    def _build(self):
        FONT_HDR  = ('Segoe UI', 13, 'bold')
        FONT_CELL = ('Segoe UI', 13)
        FONT_ROW  = ('Segoe UI', 13)

        frm = ttk.Frame(self, padding=20)
        frm.pack(fill='both', expand=True)

        # Column headers
        ttk.Label(frm, text='Параметр', font=FONT_HDR, width=30,
                  anchor='w').grid(row=0, column=0, padx=6, pady=3, sticky='w')
        for col, lbl in enumerate(('Модуль 1', 'Модуль 2'), start=1):
            ttk.Label(frm, text=lbl, font=FONT_HDR, width=18,
                      anchor='center').grid(row=0, column=col, padx=6, pady=3)

        ttk.Separator(frm, orient='horizontal').grid(
            row=1, column=0, columnspan=3, sticky='ew', pady=6)

        self._cells: list[list[tk.Label]] = []
        for r, (name, _) in enumerate(_ROWS, start=2):
            ttk.Label(frm, text=name, font=FONT_ROW,
                      anchor='w').grid(row=r, column=0, padx=6, pady=4, sticky='w')
            row_cells = []
            for col in range(1, 3):
                lbl = ttk.Label(frm, text='—', font=FONT_CELL,
                                width=18, anchor='center')
                lbl.grid(row=r, column=col, padx=6, pady=4)
                row_cells.append(lbl)
            self._cells.append(row_cells)

        ttk.Separator(frm, orient='horizontal').grid(
            row=len(_ROWS) + 2, column=0, columnspan=3, sticky='ew', pady=6)

        ttk.Button(frm, text='Закрыть', command=self.destroy).grid(
            row=len(_ROWS) + 3, column=0, columnspan=3, pady=4)

    def _refresh(self):
        if not self.winfo_exists():
            return
        snap = self._model.snapshot()
        for row_idx, (_, fmt) in enumerate(_ROWS):
            for col_idx, m in enumerate(snap['modules']):
                self._cells[row_idx][col_idx].config(text=fmt(m, snap))
        self.after(500, self._refresh)
