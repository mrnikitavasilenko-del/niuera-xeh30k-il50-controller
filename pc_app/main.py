"""Entry point for ИЛ-50 PC monitoring and control application.

Usage:
    python main.py            # real mode — Offline until CAN-USB connected
    python main.py --simulate # simulator mode — two virtual PSU modules
"""
import sys
import tkinter as tk

from psu_model import PSUModel
from ui.main_window import MainWindow


def main():
    simulate = '--simulate' in sys.argv

    if simulate:
        from comm.simulator import Simulator
        comm = Simulator()
    else:
        from comm.slcan import SLCANInterface
        comm = SLCANInterface()

    model = PSUModel(comm)

    root = tk.Tk()

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = MainWindow(root, model, comm if not simulate else None)

    if simulate:
        comm.connect()

    def on_close():
        comm.disconnect()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', on_close)
    root.mainloop()


if __name__ == '__main__':
    main()
