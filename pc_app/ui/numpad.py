"""Modal numeric keypad dialog."""
import tkinter as tk
from tkinter import ttk


class NumpadDialog(tk.Toplevel):
    """Shows a numeric keypad; .result contains the integer result or None if cancelled."""

    def __init__(self, parent, title: str, initial: int, min_val: int, max_val: int):
        super().__init__(parent)
        self.title(title)
        self.result = None
        self._min = min_val
        self._max = max_val

        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self._var = tk.StringVar(value=str(initial))
        self._build()
        self._center(parent)
        self.wait_window()

    def _center(self, parent):
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f'+{px}+{py}')

    def _build(self):
        pad = {'padx': 4, 'pady': 4}

        display = ttk.Entry(self, textvariable=self._var, font=('Segoe UI', 20),
                            width=8, justify='right', state='readonly')
        display.grid(row=0, column=0, columnspan=3, **pad, sticky='ew')

        info = ttk.Label(self, text=f'Диапазон: {self._min} … {self._max}',
                         font=('Segoe UI', 9), foreground='gray')
        info.grid(row=1, column=0, columnspan=3, pady=(0, 6))

        buttons = [
            ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
            ('4', 3, 0), ('5', 3, 1), ('6', 3, 2),
            ('1', 4, 0), ('2', 4, 1), ('3', 4, 2),
            ('0', 5, 0), ('⌫', 5, 1), ('C', 5, 2),
        ]
        for text, row, col in buttons:
            ttk.Button(self, text=text, width=5,
                       command=lambda t=text: self._press(t)
                       ).grid(row=row, column=col, **pad)

        ttk.Button(self, text='OK', command=self._ok
                   ).grid(row=6, column=0, columnspan=2, **pad, sticky='ew')
        ttk.Button(self, text='Отмена', command=self.destroy
                   ).grid(row=6, column=2, **pad)

        self.bind('<Return>', lambda _: self._ok())
        self.bind('<Escape>', lambda _: self.destroy())
        self.bind('<BackSpace>', lambda _: self._press('⌫'))
        for k in '0123456789':
            self.bind(k, lambda e: self._press(e.char))

    def _press(self, text: str):
        cur = self._var.get()
        if text == '⌫':
            self._var.set(cur[:-1] if len(cur) > 1 else '0')
        elif text == 'C':
            self._var.set('0')
        else:
            self._var.set(text if cur == '0' else cur + text)

    def _ok(self):
        try:
            val = int(self._var.get())
        except ValueError:
            val = self._min
        self.result = max(self._min, min(self._max, val))
        self.destroy()
