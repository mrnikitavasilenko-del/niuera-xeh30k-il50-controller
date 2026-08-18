"""Main application window — 7 blocks per the PC screen spec (Full HD layout)."""
import tkinter as tk
from tkinter import ttk

import sys, os, ctypes
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import protocol
from ui.numpad import NumpadDialog
from ui.service_dialog import ServiceDialog

# ── Colour palette ────────────────────────────────────────────────────────────
CLR_BG       = '#ECEFF1'
CLR_CARD     = '#FFFFFF'
CLR_GREEN    = '#27AE60'
CLR_RED      = '#E74C3C'
CLR_YELLOW   = '#E67E22'
CLR_DISABLED = '#9E9E9E'
CLR_TEXT     = '#212121'
CLR_GRAY     = '#757575'

# ── Fonts — base sizes calibrated so 2K (1440px) gives the reference look ────
# At 1440px: scale=1.333 → CODE/VAL=49pt, TITLE=27pt. FullHD gets a separate
# correction factor so 2K/4K are unaffected.
FONT_TITLE   = ('Segoe UI', 20, 'bold')
FONT_LBL     = ('Segoe UI', 18)
FONT_VAL     = ('Segoe UI', 37, 'bold')
FONT_UNIT    = ('Segoe UI', 24)
FONT_BTN     = ('Segoe UI', 13, 'bold')
FONT_IND_DOT = ('Segoe UI', 20)
FONT_IND_TXT = ('Segoe UI', 16)
FONT_CODE    = ('Segoe UI', 37, 'bold')
FONT_DESC    = ('Segoe UI', 20)
FONT_KB      = ('Segoe UI', 20)       # keyboard icon — smaller than FONT_VAL
FONT_BTN_TOP = ('Segoe UI', 16, 'bold')  # top bar buttons (Включить / Сервис / Лог)


def _scale_fonts(root) -> None:
    """Rescale all FONT_* globals to the current logical screen height."""
    global FONT_TITLE, FONT_LBL, FONT_VAL, FONT_UNIT, FONT_BTN
    global FONT_IND_DOT, FONT_IND_TXT, FONT_CODE, FONT_DESC, FONT_KB, FONT_BTN_TOP
    h = root.winfo_screenheight()
    s = max(0.5, min(2.0, h / 1080.0))
    # Distinguish genuine FullHD (physical 1080px) from 4K at 200% DPI
    # (also logical 1080px but physical 2160px). Use SM_CYSCREEN for physical height.
    try:
        phys_h = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        phys_h = h
    if phys_h <= 1200:
        # FullHD — фиксированные размеры, без формулы
        FONT_TITLE   = ('Segoe UI', 19, 'bold')
        FONT_LBL     = ('Segoe UI', 17)
        FONT_VAL     = ('Segoe UI', 31, 'bold')
        FONT_UNIT    = ('Segoe UI', 24)
        FONT_BTN     = ('Segoe UI', 12, 'bold')
        FONT_IND_DOT = ('Segoe UI', 20)
        FONT_IND_TXT = ('Segoe UI', 17)
        FONT_CODE    = ('Segoe UI', 31, 'bold')
        FONT_DESC    = ('Segoe UI', 19)
        FONT_KB      = ('Segoe UI', 16)
        FONT_BTN_TOP = ('Segoe UI', 16, 'bold')
        return
    if h <= 1080:
        s *= 0.81    # high-DPI screen (4K@200%) — mild reduction
    def f(n): return max(8, round(n * s))
    FONT_TITLE   = ('Segoe UI', f(20), 'bold')
    FONT_LBL     = ('Segoe UI', f(18))
    FONT_VAL     = ('Segoe UI', f(37), 'bold')
    FONT_UNIT    = ('Segoe UI', f(24))
    FONT_BTN     = ('Segoe UI', f(13), 'bold')
    FONT_IND_DOT = ('Segoe UI', f(20))
    FONT_IND_TXT = ('Segoe UI', f(16))
    FONT_CODE    = ('Segoe UI', f(37), 'bold')
    FONT_DESC    = ('Segoe UI', f(20))
    FONT_KB      = ('Segoe UI', f(20))
    FONT_BTN_TOP = ('Segoe UI', f(16), 'bold')

REFRESH_MS = 300
def _i_limit(v: int) -> int:
    """Max current for given voltage: Iз = 50kW / Uз, clamped [10, 150]."""
    return min(150, max(10, int(50000 / max(v, 1))))


def _card(parent, **kw) -> tk.Frame:
    return tk.Frame(parent, bg=CLR_CARD, bd=1, relief='groove', **kw)


class _Indicator(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=CLR_CARD, **kw)
        self._dot = tk.Label(self, text='●', font=FONT_IND_DOT, bg=CLR_CARD)
        self._dot.pack(side='left', padx=(0, 8))
        self._lbl = tk.Label(self, text='', font=FONT_IND_TXT, bg=CLR_CARD)
        self._lbl.pack(side='left')

    def set_ok(self, text: str, ok: bool):
        self._dot.config(fg=CLR_GREEN if ok else CLR_RED)
        self._lbl.config(text=text, fg=CLR_TEXT)

    def set_neutral(self, text: str):
        self._dot.config(fg=CLR_DISABLED)
        self._lbl.config(text=text, fg=CLR_GRAY)


class MainWindow:
    def __init__(self, root: tk.Tk, model, comm=None):
        self._root = root
        self._model = model
        self._comm = comm
        self._service_win = None

        root.title('ИЛ-50 — Система управления')
        root.configure(bg=CLR_BG)
        root.geometry('1280x720')
        root.state('zoomed')

        _scale_fonts(root)

        root.bind_all('<Button-1>', self._defocus, add='+')

        self._build()
        self._refresh()

    def _defocus(self, event):
        if not isinstance(event.widget, (tk.Entry, ttk.Entry)):
            self._root.focus_set()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        outer = tk.Frame(self._root, bg=CLR_BG)
        outer.pack(fill='both', expand=True, padx=16, pady=8)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=0)  # top bar
        outer.rowconfigure(1, weight=1)  # b7 — выходные значения
        outer.rowconfigure(2, weight=1)  # b3 — установка значений
        outer.rowconfigure(3, weight=1)  # b6 — статус модулей

        # ── Top bar ──────────────────────────────────────────────────────────
        top = tk.Frame(outer, bg=CLR_BG)
        top.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        top.columnconfigure(0, weight=1, uniform='top')
        top.columnconfigure(1, weight=0)
        top.columnconfigure(2, weight=1, uniform='top')

        # Blocks 1+2 — indicators (LEFT)
        left = tk.Frame(top, bg=CLR_BG)
        left.grid(row=0, column=0, sticky='nsw')
        ind_panel = _card(left, padx=16, pady=12)
        ind_panel.pack(anchor='w', fill='y', expand=True)
        self._ind_conn = _Indicator(ind_panel)
        self._ind_conn.pack(anchor='w', pady=4)
        self._ind_sys = _Indicator(ind_panel)
        self._ind_sys.pack(anchor='w', pady=4)

        # Block 5 — Start/Stop (CENTER, выровнен по середине окна)
        self._btn_ss = tk.Button(
            top, text='Пуск ИЛ-50', font=FONT_TITLE,
            bg=CLR_GREEN, fg='white', activeforeground='white',
            activebackground='#1e8449', disabledforeground='#a8d5b7',
            relief='flat', bd=0, padx=20, pady=18, cursor='hand2',
            command=self._toggle_output,
        )
        self._btn_ss.grid(row=0, column=1)

        # Service / Log / Connect (RIGHT)
        right = tk.Frame(top, bg=CLR_BG)
        right.grid(row=0, column=2, sticky='e')
        self._btn_service = tk.Button(
            right, text='Сервис', font=FONT_TITLE,
            bg='#607D8B', fg='white', activeforeground='white',
            activebackground='#455A64', disabledforeground='white',
            relief='flat', bd=0, padx=16, pady=18, cursor='hand2',
            command=self._open_service,
        )
        self._btn_service.pack(side='left')

        self._btn_log = tk.Button(
            right, text='Лог', font=FONT_TITLE,
            bg='#37474F', fg='white', activeforeground='white',
            activebackground='#263238', disabledforeground='white',
            relief='flat', bd=0, padx=16, pady=18, cursor='hand2',
            command=self._open_log,
        )
        self._btn_log.pack(side='left', padx=(8, 0))

        self._btn_conn = tk.Button(
            right, text='Подключить', font=FONT_TITLE,
            bg='#1565C0', fg='white', activeforeground='white',
            activebackground='#0D47A1', disabledforeground='white',
            relief='flat', bd=0, padx=16, pady=18, cursor='hand2',
            command=self._open_connect_dialog,
        )
        self._btn_conn.pack(side='left', padx=(8, 0))
        if self._comm is None:
            self._btn_conn.pack_forget()

        # ── Block 6 — Статус модулей (row=4, всегда снизу) ───────────────────
        b6 = _card(outer, padx=14, pady=8)
        b6.grid(row=3, column=0, sticky='nsew', pady=(6, 0))
        b6.columnconfigure(0, weight=1, uniform='mod')
        b6.columnconfigure(1, weight=0)
        b6.columnconfigure(2, weight=1, uniform='mod')
        b6.rowconfigure(0, weight=0)
        b6.rowconfigure(1, weight=1)

        tk.Label(b6, text='Статус модулей', font=FONT_TITLE,
                 bg=CLR_CARD, fg=CLR_GRAY).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))

        self._mod_cells = []
        for i in range(2):
            cell = tk.Frame(b6, bg=CLR_CARD)
            cell.grid(row=1, column=i * 2, sticky='nsew')

            inner = tk.Frame(cell, bg=CLR_CARD)
            inner.pack(expand=True)  # вертикальное центрирование в ячейке

            tk.Label(inner, text=f'Модуль {i + 1}',
                     font=FONT_TITLE, bg=CLR_CARD, fg=CLR_GRAY).pack(anchor='center', pady=(0, 4))

            code_lbl = tk.Label(inner, text='—', font=FONT_CODE,
                                bg=CLR_CARD, fg=CLR_DISABLED)
            code_lbl.pack(anchor='center')

            desc_lbl = tk.Label(inner, text='Нет связи', font=FONT_DESC,
                                bg=CLR_CARD, fg=CLR_DISABLED)
            desc_lbl.pack(anchor='center', pady=(2, 4))

            temp_lbl = tk.Label(inner, text='T = — °C', font=FONT_DESC,
                                bg=CLR_CARD, fg=CLR_DISABLED)
            temp_lbl.pack(anchor='center')

            self._mod_cells.append((code_lbl, desc_lbl, temp_lbl))

        tk.Frame(b6, bg='#BDBDBD', width=2).grid(
            row=1, column=1, sticky='ns', padx=4, pady=2)

        # ── Block 7 — Выходные значения (row=1) ──────────────────────────────
        b7 = _card(outer, padx=16, pady=8)
        b7.grid(row=1, column=0, sticky='nsew', pady=(0, 6))
        self._b7 = b7

        out_center = tk.Frame(b7, bg=CLR_CARD)
        out_center.pack(expand=True)
        self._out_center = out_center

        tk.Label(out_center, text='Выходные значения', font=FONT_TITLE,
                 bg=CLR_CARD, fg=CLR_GRAY).pack(fill='x', pady=(0, 8))
        out_grid = tk.Frame(out_center, bg=CLR_CARD)
        out_grid.pack(fill='x')
        self._out_grid = out_grid
        self._out_v = self._make_output_row(out_grid, 0, 'U =', 'В')
        self._out_i = self._make_output_row(out_grid, 1, 'I =', 'А')
        self._out_p = self._make_output_row(out_grid, 2, 'P =', 'кВт')

        # ── Block 3 — Установка значений (row=2) ─────────────────────────────
        b3 = _card(outer, padx=16, pady=8)
        b3.grid(row=2, column=0, sticky='nsew')

        sp_center = tk.Frame(b3, bg=CLR_CARD)
        sp_center.pack(fill='both', expand=True)
        self._sp_center = sp_center

        self._volt_var = tk.StringVar(value='500')
        self._curr_var = tk.StringVar(value='37')
        self._last_volt_sync = self._volt_var.get()
        self._last_curr_sync = self._curr_var.get()

        content = tk.Frame(sp_center, bg=CLR_CARD)
        content.pack(fill='x')
        self._content = content

        gf = tk.Frame(content, bg=CLR_CARD)
        gf.pack(anchor='center')
        gf.columnconfigure(1, weight=1)
        self._gf = gf

        tk.Label(gf, text='Установка значений', font=FONT_TITLE,
                 bg=CLR_CARD, fg=CLR_GRAY).grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 8))

        volt_lbl = tk.Label(gf, text='Uз =', font=FONT_UNIT, bg=CLR_CARD)
        volt_lbl.grid(row=1, column=0, sticky='e', padx=(0, 20), pady=4)
        volt_entry = ttk.Entry(gf, textvariable=self._volt_var, font=FONT_VAL, width=4, justify='right')
        volt_entry.grid(row=1, column=1, sticky='ew', pady=4)
        volt_uf = tk.Frame(gf, bg=CLR_CARD)
        volt_uf.grid(row=1, column=2, sticky='w', padx=(12, 0))
        volt_unit = tk.Label(volt_uf, text='В', font=FONT_UNIT, bg=CLR_CARD)
        volt_unit.pack(side='left')
        volt_kb = tk.Button(volt_uf, text='⌨', font=FONT_KB, relief='flat',
                            bg=CLR_CARD, bd=0, activebackground=CLR_CARD, cursor='hand2',
                            command=self._open_volt_numpad)
        volt_kb.pack(side='left', padx=(8, 0))
        volt_entry.bind('<Return>',   lambda _: self._on_volt_commit())
        volt_entry.bind('<KP_Enter>', lambda _: self._on_volt_commit())

        curr_lbl = tk.Label(gf, text='Iз =', font=FONT_UNIT, bg=CLR_CARD)
        curr_lbl.grid(row=2, column=0, sticky='e', padx=(0, 20), pady=4)
        curr_entry = ttk.Entry(gf, textvariable=self._curr_var, font=FONT_VAL, width=4, justify='right')
        curr_entry.grid(row=2, column=1, sticky='ew', pady=4)
        curr_uf = tk.Frame(gf, bg=CLR_CARD)
        curr_uf.grid(row=2, column=2, sticky='w', padx=(12, 0))
        curr_unit = tk.Label(curr_uf, text='А', font=FONT_UNIT, bg=CLR_CARD)
        curr_unit.pack(side='left')
        curr_kb = tk.Button(curr_uf, text='⌨', font=FONT_KB, relief='flat',
                            bg=CLR_CARD, bd=0, activebackground=CLR_CARD, cursor='hand2',
                            command=self._open_curr_numpad)
        curr_kb.pack(side='left', padx=(8, 0))
        curr_entry.bind('<Return>',   lambda _: self._on_curr_commit())
        curr_entry.bind('<KP_Enter>', lambda _: self._on_curr_commit())

        self._volt_w = {'entry': volt_entry, 'btn': volt_kb, 'label': volt_lbl, 'unit': volt_unit}
        self._curr_w = {'entry': curr_entry, 'btn': curr_kb, 'label': curr_lbl, 'unit': curr_unit}

        # Предупреждение лежит в content (на всю ширину карточки), а НЕ в gf —
        # иначе его ширина растягивала бы колонки центрируемого грида и сдвигала
        # цифры. height=1 резервирует одну строку всегда, поэтому появление/скрытие
        # текста при вводе не меняет ни высоту, ни ширину блока, а Uз/Iз остаются
        # отцентрованы по содержимому gf, как и было.
        self._power_warn = tk.Label(content, text='', font=('Segoe UI', 14),
                                    height=1, bg=CLR_CARD, fg=CLR_YELLOW)
        self._power_warn.pack(anchor='center', pady=(4, 0))

        btn_row = tk.Frame(content, bg=CLR_CARD)
        btn_row.pack(fill='x', pady=(8, 0))
        btn_row.columnconfigure(0, weight=1, uniform='send')
        btn_row.columnconfigure(2, weight=1, uniform='send')
        self._btn_send = tk.Button(
            btn_row, text='Отправить уставки', font=FONT_TITLE,
            bg='#1565C0', fg='white', activeforeground='white',
            activebackground='#0D47A1', disabledforeground='white',
            relief='flat', bd=0, padx=24, pady=18, cursor='hand2',
            command=self._send_setpoints,
        )
        self._btn_send.grid(row=0, column=1)

        self._ui_controls = [
            self._btn_ss,
            self._volt_w['entry'],
            self._curr_w['entry'],
            self._btn_send,
        ]
        self._root.after(50, self._align_block_widths)

    def _align_block_widths(self):
        self._root.update_idletasks()
        # gf row 0 is the title with columnspan=3 — its bbox covers the full span.
        # Use row=1 (first row with actual widgets) to get true per-column widths.
        # Sync cols 0, 1, 2 so = signs, values, and units line up across both blocks.
        for col in (0, 1, 2):
            w_out = self._out_grid.grid_bbox(col, 0)[2]
            w_gf  = self._gf.grid_bbox(col, 1)[2]
            max_w = max(w_out, w_gf)
            self._out_grid.columnconfigure(col, minsize=max_w)
            self._gf.columnconfigure(col, minsize=max_w)
        self._root.update_idletasks()
        w = max(self._out_center.winfo_reqwidth(), self._gf.winfo_reqwidth())
        h_oc = self._out_center.winfo_reqheight()
        h_gf = self._gf.winfo_reqheight()
        self._out_center.config(width=w, height=h_oc)
        self._out_center.pack_propagate(False)
        self._gf.config(width=w, height=h_gf)
        self._gf.pack_propagate(False)
        # Equal top/bottom padding in the setpoint block
        self._root.update_idletasks()
        sp_h   = self._sp_center.winfo_height()
        cont_h = self._content.winfo_reqheight()
        v_pad  = max(0, (sp_h - cont_h) // 2)
        self._content.pack_configure(pady=(v_pad, v_pad))

    def _make_setpoint_row(self, parent, label, var, unit, numpad_cmd, commit_cmd):
        inner = tk.Frame(parent, bg=CLR_CARD)
        inner.pack(pady=4, anchor='w')

        label_w = tk.Label(inner, text=label, font=FONT_LBL, bg=CLR_CARD)
        label_w.pack(side='left', padx=(0, 20))

        entry = ttk.Entry(inner, textvariable=var, font=FONT_VAL, width=5,
                          justify='right')
        entry.pack(side='left', padx=(0, 12))

        unit_w = tk.Label(inner, text=unit, font=FONT_UNIT, bg=CLR_CARD)
        unit_w.pack(side='left', padx=(0, 12))

        btn = tk.Button(inner, text='⌨', font=FONT_KB,
                        relief='flat', bg=CLR_CARD, bd=0,
                        activebackground=CLR_CARD, cursor='hand2',
                        command=numpad_cmd)
        btn.pack(side='left')
        entry.bind('<Return>',   lambda _: commit_cmd())
        entry.bind('<KP_Enter>', lambda _: commit_cmd())

        return {'entry': entry, 'btn': btn, 'label': label_w, 'unit': unit_w}

    def _make_output_row(self, grid, row, label, unit) -> tk.Label:
        tk.Label(grid, text=label, font=FONT_UNIT, bg=CLR_CARD, anchor='e').grid(
            row=row, column=0, sticky='e', padx=(0, 20), pady=4)
        val = tk.Label(grid, text='—', font=FONT_VAL, bg=CLR_CARD, fg=CLR_DISABLED, anchor='e')
        val.grid(row=row, column=1, sticky='ew', pady=4)
        tk.Label(grid, text=unit, font=FONT_UNIT, bg=CLR_CARD).grid(
            row=row, column=2, sticky='w', padx=(12, 8), pady=4)
        return val

    # ── Periodic refresh ──────────────────────────────────────────────────────

    def _refresh(self):
        self._model.tick()
        snap = self._model.snapshot()
        self._sync_setpoint_vars(snap)
        self._update_indicators(snap)
        self._update_module_status(snap)
        self._update_output(snap)
        self._update_controls(snap)
        self._root.after(REFRESH_MS, self._refresh)

    def _sync_setpoint_vars(self, snap):
        """Sync field with model only if user hasn't typed anything new.
        Поле считается «грязным» (редактируется), если текст не совпадает с тем,
        что мы туда последний раз записали."""
        v_str = str(int(snap['set_voltage']))
        if self._volt_var.get() == self._last_volt_sync:
            if self._volt_var.get() != v_str:
                self._volt_var.set(v_str)
            self._last_volt_sync = v_str
        i_str = str(int(snap['set_current']))
        if self._curr_var.get() == self._last_curr_sync:
            if self._curr_var.get() != i_str:
                self._curr_var.set(i_str)
            self._last_curr_sync = i_str

    def _update_indicators(self, snap):
        # «Online» = плата на связи с ПК (даже если модули не отвечают).
        board = snap['board_online']
        self._ind_conn.set_ok('Online' if board else 'Offline', board)
        any_mod = any(m['online'] for m in snap['modules'])
        if not board:
            self._ind_sys.set_neutral('Нет данных')
        elif snap['has_fault']:
            self._ind_sys.set_ok('Авария', False)
        elif any_mod:
            self._ind_sys.set_ok('Работа в норме', True)
        else:
            # Плата на связи, но модулей на CAN нет.
            self._ind_sys.set_neutral('Нет данных')

    def _update_module_status(self, snap):
        for i, m in enumerate(snap['modules']):
            code_lbl, desc_lbl, temp_lbl = self._mod_cells[i]
            if not m['online']:
                # Плата на связи, но модуль не отвечает → показываем код 04 «Нет данных».
                if snap['board_online']:
                    code_lbl.config(text='04', fg=CLR_DISABLED)
                    desc_lbl.config(text='Нет данных', fg=CLR_DISABLED)
                else:
                    code_lbl.config(text='—', fg=CLR_DISABLED)
                    desc_lbl.config(text='Нет связи', fg=CLR_DISABLED)
                temp_lbl.config(text='T = — °C', fg=CLR_DISABLED)
            else:
                code = m['current_code']
                if code in protocol.BLOCKING_FAULT_CODES:
                    code_color = CLR_RED
                elif code in protocol.WARNING_CODES:
                    code_color = CLR_YELLOW
                elif code == 0:
                    code_color = CLR_GREEN
                else:
                    code_color = CLR_TEXT
                code_lbl.config(text=f'{code:02d}', fg=code_color)
                desc = protocol.STATUS_DESCRIPTIONS.get(code, f'Код {code}')
                desc_lbl.config(text=desc, fg=code_color)
                t = m['temperature']
                temp_lbl.config(text=f'T = {t} °C', fg=CLR_GRAY)

    def _update_output(self, snap):
        if snap['any_online']:
            self._out_v.config(text=f"{snap['total_voltage']:.0f}", fg=CLR_TEXT)
            self._out_i.config(text=f"{snap['total_current']:.1f}", fg=CLR_TEXT)
            p_kw = snap['total_voltage'] * snap['total_current'] / 1000.0
            self._out_p.config(text=f"{p_kw:.1f}", fg=CLR_TEXT)
        else:
            self._out_v.config(text='—', fg=CLR_DISABLED)
            self._out_i.config(text='—', fg=CLR_DISABLED)
            self._out_p.config(text='—', fg=CLR_DISABLED)

    def _update_controls(self, snap):
        online = snap['system_online']

        if snap['output_on']:
            self._btn_ss.config(text='Стоп ИЛ-50', bg='#1565C0',
                                fg='white', activebackground='#0D47A1',
                                activeforeground='white', relief='flat', bd=0)
        else:
            self._btn_ss.config(text='Пуск ИЛ-50', bg=CLR_GREEN,
                                fg='white', activebackground='#1e8449',
                                activeforeground='white', relief='flat', bd=0)

        # CV/CC подсветка: если хоть один модуль упёрся в ограничение
        # по напряжению (код 01) или току (код 02) — выделяем соответствующее поле
        cv_active = any(m['online'] and m['current_code'] == 1 for m in snap['modules'])
        cc_active = any(m['online'] and m['current_code'] == 2 for m in snap['modules'])
        self._set_limit_highlight(self._volt_w, cv_active)
        self._set_limit_highlight(self._curr_w, cc_active)

        if not snap['any_online']:
            self._set_enabled(False)
            self._btn_service.config(state='normal')
        elif snap['has_fault']:
            self._set_enabled(False)
            self._btn_service.config(state='normal')
        else:
            self._set_enabled(True)
            self._btn_service.config(state='normal')

        # Live-проверка лимита мощности по введённым в поля значениям
        field_v = self._safe_int(self._volt_var.get(), int(snap['set_voltage']))
        field_i = self._safe_int(self._curr_var.get(), int(snap['set_current']))
        limit = _i_limit(field_v)
        if field_i > limit:
            self._power_warn.config(
                text=f'Ограничение: ток будет снижен до {limit} А')
        else:
            self._power_warn.config(text='')

        if self._comm is not None:
            if self._comm.connected:
                self._btn_conn.config(text='Отключить', bg=CLR_RED,
                                      activebackground='#c0392b')
            else:
                self._btn_conn.config(text='Подключить', bg='#1565C0',
                                      activebackground='#0D47A1')

    def _set_enabled(self, enabled: bool):
        state = 'normal' if enabled else 'disabled'
        for w in self._ui_controls:
            try:
                w.config(state=state)
            except tk.TclError:
                pass

    def _set_limit_highlight(self, w_dict, active):
        """Перекрашиваем строку уставки в предупреждающий цвет, когда модуль
        упёрся в её ограничение (CV для U, CC для I)."""
        color = CLR_YELLOW if active else CLR_TEXT
        w_dict['label'].config(fg=color)
        w_dict['unit'].config(fg=color)
        try:
            w_dict['entry'].configure(foreground=color)
        except tk.TclError:
            pass

    # ── User actions ──────────────────────────────────────────────────────────

    def _toggle_output(self):
        self._model.send_enable(not self._model.is_output_active())

    def _send_setpoints(self):
        # Считываем оба поля ДО _apply_voltage, иначе apply_voltage перезатрёт
        # _curr_var значением модели и пользовательский ток потеряется.
        v = self._safe_int(self._volt_var.get(), int(self._model.set_voltage))
        i = self._safe_int(self._curr_var.get(), int(self._model.set_current))
        self._apply_voltage(v)
        self._apply_current(i)
        self._model.send_setpoints()

    def _open_connect_dialog(self):
        if self._comm is None:
            return
        from ui.connect_dialog import ConnectDialog
        ConnectDialog(self._root, self._comm)

    def _open_service(self):
        if self._service_win and self._service_win.winfo_exists():
            self._service_win.lift()
            return
        self._service_win = ServiceDialog(self._root, self._model)

    def _open_log(self):
        from ui.log_window import LogWindow
        LogWindow(self._root)

    def _open_volt_numpad(self):
        cur = self._safe_int(self._volt_var.get(), int(self._model.set_voltage))
        dlg = NumpadDialog(self._root, 'Уставка напряжения', cur, 200, 1000)
        if dlg.result is not None:
            # Записываем только в поле, без apply_voltage — модель обновляется
            # лишь при «Передать». Иначе echo от платы перетрёт значение, и
            # на тике refresh поле (с last_sync == значению) подтянется обратно.
            self._volt_var.set(str(dlg.result))

    def _on_volt_commit(self):
        v = self._safe_int(self._volt_var.get(), int(self._model.set_voltage))
        v = max(self._model.MIN_VOLTAGE, min(self._model.MAX_VOLTAGE, v))
        self._volt_var.set(str(v))
        self._root.focus_set()

    def _apply_voltage(self, v: int):
        self._model.apply_voltage(v)
        v_str = str(int(self._model.set_voltage))
        i_str = str(int(self._model.set_current))
        self._volt_var.set(v_str)
        self._curr_var.set(i_str)
        self._last_volt_sync = v_str
        self._last_curr_sync = i_str

    def _open_curr_numpad(self):
        cur = self._safe_int(self._curr_var.get(), int(self._model.set_current))
        # Лимит мощности считаем по живому значению поля напряжения,
        # а не по модели — иначе при V в поле 1000, но модели 500 пользователь
        # увидит max_i=100А, хотя реально допустимо 50А.
        field_v = self._safe_int(self._volt_var.get(), int(self._model.set_voltage))
        max_i = _i_limit(field_v)
        dlg = NumpadDialog(self._root, 'Уставка тока', cur, 10, min(self._model.MAX_CURRENT, max_i))
        if dlg.result is not None:
            self._curr_var.set(str(dlg.result))

    def _on_curr_commit(self):
        i = self._safe_int(self._curr_var.get(), int(self._model.set_current))
        field_v = self._safe_int(self._volt_var.get(), int(self._model.set_voltage))
        max_i = min(self._model.MAX_CURRENT, _i_limit(field_v))
        i = max(self._model.MIN_CURRENT, min(max_i, i))
        self._curr_var.set(str(i))
        self._root.focus_set()

    def _apply_current(self, i: int):
        self._model.apply_current(i)
        i_str = str(int(self._model.set_current))
        self._curr_var.set(i_str)
        self._last_curr_sync = i_str

    @staticmethod
    def _safe_int(text: str, fallback: int) -> int:
        try:
            return int(text)
        except ValueError:
            return fallback
