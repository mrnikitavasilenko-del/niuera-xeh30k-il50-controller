"""COM port selection dialog for the SLCAN USB-CAN adapter."""
import tkinter as tk
from tkinter import ttk, messagebox

import serial.tools.list_ports

_CLR_BG  = '#FFFFFF'
_CLR_CON = '#27AE60'
_CLR_DIS = '#E74C3C'
_CLR_CLO = '#607D8B'
_FONT_LBL  = ('Segoe UI', 16)
_FONT_BTN  = ('Segoe UI', 14, 'bold')
_FONT_LIST = ('Segoe UI', 14)
_FONT_STS  = ('Segoe UI', 12)


class ConnectDialog(tk.Toplevel):
    """
    Modal dialog: lists COM ports, connects/disconnects the comm object.

    comm must have: .port (str property), .connect() -> bool,
    .disconnect(), .connected (bool property).
    """

    def __init__(self, parent: tk.Widget, comm):
        super().__init__(parent)
        self.title('Подключение к CAN-USB')
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)
        self.configure(bg=_CLR_BG)

        self._comm = comm
        self._ports: list[str] = []

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self._build()
        self._center(parent)
        self.wait_window()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self):
        frm = tk.Frame(self, bg=_CLR_BG, padx=24, pady=20)
        frm.pack(fill='both', expand=True)

        tk.Label(frm, text='Выберите COM-порт:', font=_FONT_LBL,
                 bg=_CLR_BG).pack(anchor='w', pady=(0, 8))

        list_frame = tk.Frame(frm, bg=_CLR_BG)
        list_frame.pack(fill='both')

        sb = ttk.Scrollbar(list_frame, orient='vertical')
        self._lb = tk.Listbox(
            list_frame, font=_FONT_LIST, selectmode='single',
            height=8, width=44,
            yscrollcommand=sb.set, activestyle='dotbox',
        )
        sb.config(command=self._lb.yview)
        self._lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        self._status = tk.StringVar()
        tk.Label(frm, textvariable=self._status, font=_FONT_STS,
                 bg=_CLR_BG, fg='#757575').pack(anchor='w', pady=(8, 0))

        btn_row = tk.Frame(frm, bg=_CLR_BG)
        btn_row.pack(fill='x', pady=(16, 0))

        self._btn_con = tk.Button(
            btn_row, text='Подключить', font=_FONT_BTN,
            bg=_CLR_CON, fg='white', activeforeground='white',
            activebackground='#1e8449', relief='flat', bd=0,
            padx=16, pady=10, cursor='hand2',
            command=self._on_connect,
        )
        self._btn_con.pack(side='left', padx=(0, 8))

        self._btn_dis = tk.Button(
            btn_row, text='Отключить', font=_FONT_BTN,
            bg=_CLR_DIS, fg='white', activeforeground='white',
            activebackground='#c0392b', relief='flat', bd=0,
            padx=16, pady=10, cursor='hand2',
            command=self._on_disconnect,
        )
        self._btn_dis.pack(side='left', padx=(0, 8))

        tk.Button(
            btn_row, text='Закрыть', font=_FONT_BTN,
            bg=_CLR_CLO, fg='white', activeforeground='white',
            activebackground='#455A64', relief='flat', bd=0,
            padx=16, pady=10, cursor='hand2',
            command=self.destroy,
        ).pack(side='right')

        self._populate()
        self._refresh_btns()

    def _populate(self):
        self._lb.delete(0, 'end')
        ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)
        self._ports = [p.device for p in ports]
        for p in ports:
            desc = p.description or p.device
            self._lb.insert('end', f'{p.device}  —  {desc}')

        if self._ports:
            self._status.set(f'Найдено портов: {len(self._ports)}')
            # Pre-select the currently configured port
            for i, dev in enumerate(self._ports):
                if dev == self._comm.port:
                    self._lb.selection_set(i)
                    self._lb.see(i)
                    break
        else:
            self._status.set('COM-порты не найдены')

    def _center(self, parent: tk.Widget):
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width()  // 2 - self.winfo_width()  // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f'+{px}+{py}')

    def _refresh_btns(self):
        if self._comm.connected:
            self._btn_con.config(state='disabled')
            self._btn_dis.config(state='normal')
        else:
            self._btn_con.config(state='normal')
            self._btn_dis.config(state='disabled')

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_connect(self):
        sel = self._lb.curselection()
        if not sel:
            messagebox.showwarning('Порт не выбран',
                                   'Выберите COM-порт из списка.', parent=self)
            return
        port = self._ports[sel[0]]
        self._status.set(f'Подключение к {port}…')
        self.update_idletasks()

        self._comm.port = port
        ok = self._comm.connect()

        if ok:
            self._status.set(f'Подключено: {port}')
        else:
            self._status.set(f'Ошибка: не удалось открыть {port}')
            messagebox.showerror(
                'Ошибка подключения',
                f'Не удалось открыть порт {port}.\n'
                'Проверьте подключение адаптера CAN-USB.',
                parent=self)
        self._refresh_btns()

    def _on_disconnect(self):
        self._comm.disconnect()
        self._status.set('Отключено')
        self._refresh_btns()

    def _on_close(self):
        if self._comm.connected:
            self._comm.disconnect()
        self.destroy()
