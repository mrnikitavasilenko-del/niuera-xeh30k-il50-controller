"""Application-level PSU state model."""
import time
import threading

import protocol
from applog import app_log

MODULE_TIMEOUT = 2.0      # seconds without a frame → module offline
BOARD_TIMEOUT = 2.0       # seconds without any board frame → board link lost
_KEEPALIVE_INTERVAL = 0.5 # seconds between keep-alive frames PC→board
_SEND_LOCK = 5.0          # seconds after PC sends before board echoes can resync
_OUTPUT_ACTIVE_V = 20.0   # V; output considered active when voltage exceeds this


class ModuleState:
    def __init__(self, addr: int):
        self.addr = addr
        self.online = False
        self.temperature = 0
        self.output_voltage = 0.0
        self.output_current = 0.0
        self.vab = 0.0
        self.vbc = 0.0
        self.vca = 0.0
        self.status0 = 0
        self.status1 = 0
        self.status2 = 0
        self.current_code = 0          # live decoded code from latest 0x04
        self.phase_code = 0            # code derived from 0x06 phase voltage analysis (0/12/13)
        self.history = [None] * 5  # last 5 event codes, [0]=newest; None = empty slot, 0 = "норма"
        self._last_seen = 0.0          # monotonic timestamp

    def mark_seen(self):
        self._last_seen = time.monotonic()
        if not self.online:
            self.online = True
            app_log.log('STATE', f'Модуль {self.addr}: online')

    def check_timeout(self):
        if self.online and self._last_seen > 0:
            if (time.monotonic() - self._last_seen) > MODULE_TIMEOUT:
                self.online = False
                self.output_voltage = 0.0
                self.output_current = 0.0
                self.current_code = 4   # CAN link lost
                app_log.log('STATE', f'Модуль {self.addr}: offline (таймаут CAN)')

    def push_history(self, code: int):
        if self.history[0] == code:
            return
        self.history = [code] + self.history[:4]

    def snapshot(self) -> dict:
        return {
            'addr':            self.addr,
            'online':          self.online,
            'temperature':     self.temperature,
            'output_voltage':  self.output_voltage,
            'output_current':  self.output_current,
            'vab': self.vab, 'vbc': self.vbc, 'vca': self.vca,
            'status0':         self.status0,
            'status1':         self.status1,
            'status2':         self.status2,
            'current_code':    self.current_code,
            'phase_code':      self.phase_code,
            'history':         list(self.history),
        }


class PSUModel:
    MAX_VOLTAGE = 1000
    MIN_VOLTAGE = 200
    MIN_CURRENT = 10
    MAX_CURRENT = 150
    MAX_POWER_W = 50_000

    def __init__(self, comm):
        self._comm = comm
        self._lock = threading.Lock()
        self.modules = [ModuleState(0), ModuleState(1)]
        self.set_voltage = 500.0
        self.set_current = 37.0
        self._active_count = protocol.PSU_ACTIVE_COUNT
        # Setpoints sync: always track board's actual setpoints from 0x1C echoes,
        # except for _SEND_LOCK seconds after the PC explicitly sent new values.
        self._send_timestamp = 0.0   # monotonic time of last PC send
        # Board liveness: любой кадр от платы (ответ keep-alive, эхо команд, форвард
        # ответов модулей) обновляет _board_last_seen. «Online» = плата на связи,
        # независимо от того, отвечают ли модули на CAN-1.
        self._board_last_seen = 0.0
        self._last_keepalive_sent = 0.0
        # Track last commanded output state to suppress transient spurious codes
        # (codes 07, 13) that appear during enable/disable ramp transitions.
        self._commanded_on = False
        comm.set_rx_callback(self._on_frame)

    # ── External control ──────────────────────────────────────────────────

    def is_output_active(self) -> bool:
        """True when at least one online module reports output voltage above threshold."""
        with self._lock:
            return any(
                m.online and m.output_voltage > _OUTPUT_ACTIVE_V
                for m in self.modules
            )

    def send_enable(self, enable: bool):
        state_str = 'ВКЛ' if enable else 'ВЫКЛ'
        app_log.log('STATE', f'Команда вывода: {state_str}')
        with self._lock:
            self._commanded_on = enable
        for addr in range(self._active_count):
            can_id, data = protocol.build_enable_frame(addr, enable)
            self._comm.send_frame(can_id, data)

    def send_setpoints(self):
        """Send current set_voltage / set_current to all modules via CAN."""
        per_module = self.set_current / self._active_count
        app_log.log('STATE', f'Отправка уставок: U={self.set_voltage:.0f}В  I={self.set_current:.0f}А  (на модуль: {per_module:.1f}А)')
        for addr in range(self._active_count):
            can_id, data = protocol.build_setpoint_frame(addr, self.set_voltage, per_module)
            self._comm.send_frame(can_id, data)
        self._send_timestamp = time.monotonic()

    def apply_voltage(self, v: int) -> bool:
        """Validate and store new voltage setpoint locally (no CAN send).
        Returns True if current was power-clamped."""
        v = max(self.MIN_VOLTAGE, min(self.MAX_VOLTAGE, int(v)))
        with self._lock:
            self.set_voltage = float(v)
            clamped = self._clamp_current()
        return clamped

    def apply_current(self, i: int) -> bool:
        """Validate and store new current setpoint locally (no CAN send).
        Returns True if it was power-clamped."""
        i = max(self.MIN_CURRENT, min(self.MAX_CURRENT, int(i)))
        with self._lock:
            clamped = self._clamp_current(proposed=float(i))
        return clamped

    def _clamp_current(self, proposed: float = None) -> bool:
        """Apply Iз = 50кВт/Uз limit. Returns True if clamped."""
        if proposed is not None:
            self.set_current = proposed
        limit = min(150.0, 50000.0 / max(self.set_voltage, 1.0))
        if self.set_current > limit:
            self.set_current = float(int(limit))
            return True
        return False

    # ── Display code ──────────────────────────────────────────────────────

    @staticmethod
    def _raw_has_blocking_fault(s0: int, s1: int, s2: int) -> bool:
        """True if any blocking-fault bit is set in raw status bytes.
        Needed because decode_status_bits returns only the highest-priority code,
        which can be code 14 (non-blocking warning) while a blocking fault bit
        (e.g. s1 bit 7 = code 8) is simultaneously active."""
        return bool(s2 & 0xF8) or bool(s1) or bool(s0 & 0x20)

    def _code14_is_genuine(self) -> bool:
        """True when the 50 kW physical power limit could actually be engaged.
        Code 14 (s2 bit 0) also appears transiently during start/stop ramps at
        any power level — suppress it unless the setpoint exceeds the limit."""
        return self.set_voltage * self.set_current > self.MAX_POWER_W

    def _display_code(self, m) -> int:
        """Return display code: 4=offline, 14=power-limiting, 1=CV, 2=CC, else raw fault."""
        if not m.online:
            return 4
        # Ramp-down detection: module was commanded off but output hasn't died yet.
        # Transient bits (phase imbalance codes 12/13, fan code 07) fire during ramp-down
        # just like code 14 — suppress them when we know the stop was commanded.
        ramping_down = (not self._commanded_on) and (m.output_voltage > _OUTPUT_ACTIVE_V)
        # Phase fault derived from 0x06 data takes priority — the PSU hardware often
        # does not set s2[3]/s2[4] (codes 13/12) even with an obviously missing phase.
        # Suppress when: (a) ramp-down in progress (output still dying), OR (b) module
        # is idle / commanded off — phase voltages are meaningless when output is off and
        # the 0x06 capacitor-discharge transient can outlast the DC ramp-down by 20+ s.
        if m.phase_code in protocol.BLOCKING_FAULT_CODES and not ramping_down and self._commanded_on:
            return m.phase_code
        raw = m.current_code
        if m.output_voltage > _OUTPUT_ACTIVE_V:
            # Code 14 during genuine power-limiting (setpoint exceeds 50 kW physical cap).
            if raw == 14 and self._code14_is_genuine():
                return 14
            if raw not in protocol.BLOCKING_FAULT_CODES:
                # Code 14 (non-blocking) can mask a blocking s1/s0 code in the priority
                # decode.  Re-decode with s2 bit 0 cleared to let it surface.
                # Suppress secondary during ramp-down: s1 bits (e.g. fan, s1[3]) also
                # fire transiently during power-down alongside s2[0].
                if raw == 14 and not ramping_down:
                    secondary = protocol.decode_status_bits(
                        m.status0, m.status1, m.status2 & ~0x01)
                    if secondary in protocol.BLOCKING_FAULT_CODES:
                        return secondary
                # CV/CC decision mirrors firmware compute_mode_code:
                # compare per-module voltage (Set_Voltage / active_count) so that series
                # modules at ~half-setpoint voltage are correctly classified.
                per_module   = self.set_current / self._active_count if self._active_count > 0 else 0
                per_module_v = self.set_voltage  # modules are parallel: each outputs full set_voltage
                v_thr = max(0.0, per_module_v - 10.0)
                i_thr = max(0.0, per_module - 1.0)
                if m.output_voltage >= v_thr and m.output_current < i_thr:
                    return 1  # CV — voltage regulation
                if m.output_current >= i_thr and m.output_voltage < v_thr:
                    return 2  # CC — current limiting
                return 1      # default: output active, ambiguous → CV
            return raw
        # Output not active: code 14 appears transiently during ramp-down — suppress it.
        # A blocking fault hiding behind it is only surfaced when actually commanded on:
        # s1 bits (fan code 07, etc.) fire as initialization/idle noise when commanded off.
        if raw == 14:
            secondary = protocol.decode_status_bits(
                m.status0, m.status1, m.status2 & ~0x01)
            if secondary in protocol.BLOCKING_FAULT_CODES and self._commanded_on:
                return secondary
            raw = 0  # suppressed ramp-down code 14 → treat as 0, fall through to sticky check

        if raw == 0:
            # КЗ (code 5) was the last event: keep it visible until the module successfully
            # restarts (output active → code 1/2 pushed to history).
            # This prevents the fault from disappearing when firmware autonomously sends OFF
            # after detecting КЗ, causing the module to clear its КЗ status bit within ~1 s.
            # Clears naturally when push_history gets code 1/2 (output active after user
            # presses Включить and КЗ is resolved).
            if m.history[0] == 5:
                return 5
            return 0

        return raw

    # ── Periodic tick (call from UI thread) ──────────────────────────────

    def tick(self):
        # Keep-alive шлём вне локов (send_frame может блокировать на serial).
        now = time.monotonic()
        if self._comm.connected and (now - self._last_keepalive_sent) >= _KEEPALIVE_INTERVAL:
            self._last_keepalive_sent = now
            can_id, data = protocol.build_keepalive_frame()
            self._comm.send_frame(can_id, data)
        with self._lock:
            if not self._comm.connected:
                self._send_timestamp = 0.0
            for m in self.modules:
                m.check_timeout()
                m.push_history(self._display_code(m))

    # ── State snapshot (thread-safe read for UI) ─────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            all_online = all(m.online for m in self.modules)
            # _display_code handles all fault disambiguation: code-14 masking,
            # phase-fault priority, ramp-down suppression, and sticky code-05.
            # Code 05 (КЗ) is now a blocking fault — cleared only by power cycle.
            has_fault = any(
                m.online and self._display_code(m) in protocol.BLOCKING_FAULT_CODES
                for m in self.modules
            )
            total_v = max((m.output_voltage for m in self.modules if m.online), default=0.0)
            total_i = sum(m.output_current for m in self.modules if m.online)
            modules = []
            for m in self.modules:
                snap = m.snapshot()
                snap['current_code'] = self._display_code(m)
                modules.append(snap)
            any_online = self._comm.connected and any(m.online for m in self.modules)
            board_online = self._comm.connected and \
                (time.monotonic() - self._board_last_seen) < BOARD_TIMEOUT
            return {
                'board_connected': self._comm.connected,
                'board_online':    board_online,
                'system_online':   self._comm.connected and all_online,
                'any_online':      any_online,
                'has_fault':       has_fault,
                'output_on':       any(m.online and m.output_voltage > _OUTPUT_ACTIVE_V for m in self.modules),
                'set_voltage':     self.set_voltage,
                'set_current':     self.set_current,
                'total_voltage':   total_v,
                'total_current':   total_i,
                'modules':         modules,
            }

    # ── CAN RX handler (called from background thread) ───────────────────

    def _on_frame(self, can_id: int, data: bytes):
        p = protocol.parse_can_id(can_id)
        src = p['src']
        cmd = p['cmd']

        # Любой принятый кадр означает, что плата на связи (она его прислала/переслала):
        # ответ keep-alive (src=BOARD_ADDR), эхо команд (src=0xF0), форвард ответов модулей.
        self._board_last_seen = time.monotonic()

        # Only process frames FROM PSU modules (src = 0 or 1)
        if src >= len(self.modules):
            return

        with self._lock:
            m = self.modules[src]
            m.mark_seen()

            if cmd == protocol.CMD_READ_STATUS:
                parsed = protocol.parse_0x04(data)
                if parsed:
                    m.temperature = parsed['temp']
                    old_s0, old_s1, old_s2 = m.status0, m.status1, m.status2
                    m.status0 = parsed['status0']
                    m.status1 = parsed['status1']
                    m.status2 = parsed['status2']
                    code = protocol.decode_status_bits(
                        parsed['status0'], parsed['status1'], parsed['status2']
                    )
                    if (old_s0, old_s1, old_s2) != (m.status0, m.status1, m.status2):
                        app_log.log('STATE', (
                            f'Модуль {src} 0x04: T={m.temperature}°C '
                            f's0={m.status0:#04x} s1={m.status1:#04x} s2={m.status2:#04x} '
                            f'→ код {code}'
                        ))
                    old_code = m.current_code
                    m.current_code = code
                    if code != old_code:
                        app_log.log('STATE', f'Модуль {src}: код {old_code} → {code}')
                    if code in protocol.FAULT_CODES:
                        # Code 14 (power limiting, s2 bit 0) also fires transiently during
                        # start/stop ramps at any power level.  Only record it in history
                        # when the setpoint actually exceeds the 50 kW physical limit.
                        if code != 14 or self._code14_is_genuine():
                            m.push_history(code)

            elif cmd == protocol.CMD_READ_OUTPUT:
                parsed = protocol.parse_0x09(data)
                if parsed:
                    m.output_voltage = parsed['voltage_v']
                    m.output_current = parsed['current_a']

            elif cmd == protocol.CMD_READ_PHASE_V:
                parsed = protocol.parse_0x06(data)
                if parsed:
                    m.vab = parsed['vab']
                    m.vbc = parsed['vbc']
                    m.vca = parsed['vca']
                    # Detect phase loss / imbalance from line voltages.
                    # The PSU hardware does not always set s2[3]/s2[4] (codes 13/12) on
                    # phase faults — it may just sit with s2[0]=14 and refuse to start.
                    # An open phase makes the two line-voltages that include it drop to
                    # ~50% of the healthy line (capacitive coupling through input filter).
                    vvals = [v for v in (m.vab, m.vbc, m.vca) if v > 0]
                    vmax = max((m.vab, m.vbc, m.vca), default=0.0)
                    if vmax >= 100.0 and len(vvals) == 3:
                        ratio = min(vvals) / vmax
                        new_phase_code = 13 if ratio < 0.70 else (12 if ratio < 0.85 else 0)
                    else:
                        new_phase_code = 0
                    if new_phase_code != m.phase_code:
                        old_pc = m.phase_code
                        m.phase_code = new_phase_code
                        app_log.log('STATE', (
                            f'Модуль {src} фазы: Vab={m.vab:.0f}В Vbc={m.vbc:.0f}В '
                            f'Vca={m.vca:.0f}В → фаза-код {old_pc}→{new_phase_code}'
                        ))
                    # Only push to history when output is active and not ramping down.
                    if m.phase_code > 0 and m.output_voltage > _OUTPUT_ACTIVE_V and self._commanded_on:
                        m.push_history(m.phase_code)

            elif cmd == protocol.CMD_SET_ENABLE:
                # PSU echoes 0x1A back: data[0]=0 → ON, data[0]=1 → OFF (инверсия).
                # Синхронизируем _commanded_on по реальному состоянию PSU, в том числе
                # при подключении к уже работающей установке.
                self._commanded_on = (len(data) > 0 and data[0] == 0)

            elif cmd == protocol.CMD_SET_VC:
                # PSU echoes back its current accepted setpoints on every 0x1C.
                # Always sync the UI to what the board actually has, UNLESS the PC
                # just sent new setpoints (lockout of _SEND_LOCK seconds).
                parsed = protocol.parse_0x1c(data)
                if parsed:
                    v = parsed['voltage_v']
                    i_total = parsed['current_per_module_a'] * self._active_count
                    locked = (time.monotonic() - self._send_timestamp) < _SEND_LOCK
                    app_log.log('STATE', (
                        f'Модуль {src} 0x1C эхо: U={v:.1f}В  I_total={i_total:.1f}А '
                        f'(lock={locked})'
                    ))
                    if not locked:
                        changed = False
                        if self.MIN_VOLTAGE <= v <= self.MAX_VOLTAGE:
                            if abs(v - self.set_voltage) > 0.5:
                                self.set_voltage = v
                                changed = True
                        if self.MIN_CURRENT <= i_total <= self.MAX_CURRENT:
                            if abs(i_total - self.set_current) > 0.5:
                                self.set_current = i_total
                                changed = True
                        if changed:
                            app_log.log('STATE', f'Уставки обновлены от платы: U={self.set_voltage:.0f}В  I={self.set_current:.0f}А')
