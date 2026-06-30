# IL-50 DC PSU Controller — STM32 Firmware

STM32F107VC firmware for a controller board that manages and monitors **IL-50 DC power supply modules** over CAN bus. Supports two modules simultaneously, with CAN1 bridged to CAN2 for PC visibility.

## Hardware

- **MCU**: STM32F107VC (Cortex-M3, 72 MHz, 256 KB Flash, 64 KB SRAM)
- **CAN1**: PSU module bus (primary commands and telemetry)
- **CAN2**: PC bridge (all CAN1 frames mirrored; PC commands forwarded to CAN1)
- **Display**: OLED SSD1306 128×128 (3 interactive screens) + E-Paper 200×200 (status code history)
- **Bus speed**: 125 kbaud
- **Module addresses**: 0 and 1 (configurable in `PSU_ActiveAddrs[]`)

## CAN Protocol

29-bit extended frame, 125 kbaud.

### CAN ID Structure

The 29-bit extended CAN ID is interpreted as a packed struct (LSB-first in memory):

```c
typedef struct {
    uint8_t source;       // sender address (PC = 0xF0, board = 0xAA)
    uint8_t destination;  // target module address (0 or 1)
    uint8_t command : 6;  // command code
    uint8_t device  : 4;  // always 0x0A for these modules
    uint8_t error   : 3;  // 0 = no error
} CanId_t;
```

All DLC=8, big-endian multi-byte fields.

### Commands (PC/Board → Module, FIFO0)

| Cmd | Name | Data layout | Notes |
|-----|------|-------------|-------|
| `0x04` | Poll status | 8 bytes zero | Response: temp @ byte 4, status2 @ byte 6, status1 @ byte 7 |
| `0x06` | Poll phase voltages | 8 bytes zero | Response: VAB @ bytes 0–1, VBC @ 2–3, VCA @ 4–5 (0.1 V, uint16 BE) |
| `0x09` | Poll output V/I | 8 bytes zero | Response: voltage mV @ bytes 0–3, current mA @ bytes 4–7 (uint32 BE) |
| `0x1A` | Enable/disable output | `data[0]`: **0=ON, 1=OFF** (inverted logic) | Idempotent: ignored if state unchanged |
| `0x1C` | Set voltage + current | Voltage mV @ bytes 0–3, current mA @ bytes 4–7 (uint32 BE) | Voltage range: 150–1000 V |
| `0x1D` | Set HV/LV mode | `data[0]`: **0=HV, 1=LV** (inverted logic) | HV mode when setpoint > 500 V |
| `0x2A` | Keep-alive | Board → PC reply on CAN2; not forwarded to CAN1 | Payload: module online bitmap + last status codes |

> **Note:** Commands 0x1A, 0x1C, 0x1D are also mirrored to CAN2 so the PC monitoring tool sees setpoints and enable state from the board.

### Polling Sequence (1 s cycle)

```
for each module:
    Send 0x04 (status)    → wait 2 ms
    Send 0x06 (phases)    → wait 2 ms
    Send 0x09 (output V/I) → wait 2 ms
    Set HV/LV mode if changed
    Send 0x1C (voltage + current setpoint)
    Send 0x1A (enable/disable)
```

### Module Response Frames (CAN1 → CAN2 bridge)

All CAN1 responses are transparently forwarded to CAN2 (PC visibility). No explicit request-response pairing — the board uses `CanId.source` to identify which module responded.

### Status Byte Decoding (`0x04` response)

`PSU_DecodeStatusBits(status0, status1, status2)` maps hardware fault bits to numeric codes:

| Code | Meaning | Status byte/bit |
|------|---------|-----------------|
| 5 | Output short circuit | s2[2] or s0[0] |
| 6 | Overheating | s1[4] |
| 7 | Fan failure | s1[3] |
| 8 | CAN link interrupted | s1[7] |
| 9 | PFC module off | s2[7] |
| 10 | Input overvoltage | s2[6] |
| 11 | Low input voltage | s2[5] |
| 12 | Phase imbalance | s2[4] |
| 13 | Phase loss | s2[3] |
| 14 | Power limiting mode | s2[0] |
| 15 | Output overcurrent | s1[6] |
| 16 | Output overvoltage | s1[5] |
| 17 | Module protection alarm | s1[2] |
| 18 | Module fault alarm | s1[1] |
| 19 | DC-side module off | s1[0] |
| 20 | Discharge error | s0[5] |
| 21 | Internal communication fault | s0[2] |

Codes 5–20 cause fault latch (`psu_faulted`): module stays off until operator clears via `PSU_ClearFault()`. Code 5 (short circuit) causes hard latch (`psu_kz_faulted`) — cleared only by board power cycle.

### Phase Voltage Diagnostics (`0x06` response)

The firmware diagnoses phase loss in software because the hardware does not always set status bits 12/13:
```
if (Vmin / Vmax < 70%)  → code 13 (phase loss)
if (Vmin / Vmax < 85%)  → code 12 (phase imbalance)
```
Only pushed to history if module was commanded ON.

### HV/LV Mode

Modules have two voltage ranges:
- **LV mode**: up to 499 V
- **HV mode**: 500–1000 V

Mode is selected automatically based on the voltage setpoint in `PSU_UpdateAll()`.

### Voltage/Current Setpoint Encoding

`0x1C` frame:
```
Bytes 0–3: voltage in mV (uint32 big-endian)
Bytes 4–7: current in mA per module (uint32 big-endian)
```

When PC sends a `0x1C` frame on CAN2, the board reads it back and updates its own `Set_Voltage`/`Set_Current` state (current per module × module count = total).

### PC Communication (CAN2, FIFO1)

The board listens on CAN2 FIFO1 for commands from the PC:
- `0x2A` (keep-alive, dst=0xAA): board replies directly on CAN2 with online status + last status codes; never forwarded to CAN1.
- `0x1A`, `0x1C`: board syncs its internal state and then forwards to CAN1 immediately so the module executes without waiting for the next superloop tick.

## OLED UI (3 Screens)

| Screen | Content |
|--------|---------|
| 1 | Output voltage, current, power; Middle button = toggle output (with debounce) |
| 2 | Setpoint entry — voltage (step 1/10 V) and current (A) |
| 3 | Module status / history display |

## Flash Settings

Settings saved to Flash page 127 (`0x0803F800`), 24-byte struct with magic `0xA55A5AA5`. Loaded at startup, saved on every setpoint change.

## File Structure

```
Core/
  Inc/
    main.h                      — peripheral handles, global declarations
    can.h                       — CAN handle declarations
  Src/
    main.c                      — OLED UI, button logic, superloop, Flash settings
    can.c                       — CAN peripheral init (MX_CAN1_Init, MX_CAN2_Init)
Drivers/
  PSU_Control/
    psu_control.h               — PSU_State_t, API declarations
    psu_control.c               — PSU_UpdateAll, CAN RX/TX, fault logic, bridge
  OLED/
    ssd1306.c / .h              — SSD1306 128×128 driver
    ssd1306_fonts.c / .h        — Font_16x26 with Cyrillic glyphs
    ssd1306_conf.h              — display configuration
  Epaper/
    epaper_text.c / .h          — E-paper 200×200 text rendering
    YRD0150BBS810*.c / .h       — E-paper panel driver
VSource_2.ioc                   — STM32CubeMX peripheral config
```

## Building

Open in **STM32CubeIDE** (GNU Tools for STM32 12.3+). Flash via ST-Link over SWD.
