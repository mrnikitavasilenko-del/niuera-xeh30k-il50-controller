"""Debug log window — scrollable live CAN/state log."""
import tkinter as tk
from tkinter import ttk, filedialog
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from applog import app_log

_FONT = ('Consolas', 11)
_REFRESH_MS = 400

# Color tags: (foreground, background)
_TAGS = {
    'RX':    ('#0D47A1', '#E3F2FD'),   # blue
    'TX':    ('#1B5E20', '#E8F5E9'),   # green
    'STATE': ('#E65100', '#FFF3E0'),   # orange
    'CONN':  ('#4A148C', '#F3E5F5'),   # purple
    'WARN':  ('#B71C1C', '#FFEBEE'),   # red
    'INFO':  ('#212121', '#FFFFFF'),   # black on white
}


class LogWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('Отладочный лог')
        self.geometry('1100x600')
        self.transient(parent)
        self._autoscroll = tk.BooleanVar(value=True)
        self._build()
        self._schedule_refresh()

    def _build(self):
        toolbar = tk.Frame(self, bg='#F5F5F5', pady=4)
        toolbar.pack(fill='x', side='top')

        ttk.Checkbutton(
            toolbar, text='Авто-прокрутка',
            variable=self._autoscroll,
        ).pack(side='left', padx=8)

        ttk.Button(toolbar, text='Очистить', command=self._clear).pack(side='left', padx=4)
        ttk.Button(toolbar, text='Сохранить…', command=self._save).pack(side='left', padx=4)
        ttk.Button(toolbar, text='Закрыть', command=self.destroy).pack(side='right', padx=8)

        frm = tk.Frame(self)
        frm.pack(fill='both', expand=True)

        self._text = tk.Text(
            frm, font=_FONT, wrap='none',
            state='disabled', bg='#FFFFFF',
            relief='flat', bd=0,
        )
        sb_y = ttk.Scrollbar(frm, orient='vertical', command=self._text.yview)
        sb_x = ttk.Scrollbar(frm, orient='horizontal', command=self._text.xview)
        self._text.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)

        sb_y.pack(side='right', fill='y')
        sb_x.pack(side='bottom', fill='x')
        self._text.pack(side='left', fill='both', expand=True)

        for tag, (fg, bg) in _TAGS.items():
            self._text.tag_configure(tag, foreground=fg, background=bg)

        self._displayed = 0  # how many lines already shown

    def _pick_tag(self, line: str) -> str:
        for tag in ('RX', 'TX', 'STATE', 'CONN', 'WARN'):
            if f' {tag} ' in line or f'] {tag}' in line:
                return tag
        return 'INFO'

    def _schedule_refresh(self):
        if not self.winfo_exists():
            return
        if app_log.consume_unread():
            lines = app_log.get_lines()
            new = lines[self._displayed:]
            if new:
                self._text.configure(state='normal')
                for line in new:
                    tag = self._pick_tag(line)
                    self._text.insert('end', line + '\n', tag)
                self._displayed = len(lines)
                self._text.configure(state='disabled')
                if self._autoscroll.get():
                    self._text.see('end')
        self.after(_REFRESH_MS, self._schedule_refresh)

    def _clear(self):
        app_log.clear()
        self._displayed = 0
        self._text.configure(state='normal')
        self._text.delete('1.0', 'end')
        self._text.configure(state='disabled')

    def _save(self):
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension='.txt',
            filetypes=[('Text', '*.txt'), ('All', '*.*')],
            initialfile='can_log.txt',
        )
        if path:
            app_log.save(path)
