#ifndef INC_PSU_CONTROL_H_
#define INC_PSU_CONTROL_H_

#include "main.h"
#include <stdbool.h>
#include <stdint.h>

#define PSU_MAX_ADDR        2
#define PSU_MAX_MODULES     2

#ifndef MIN_VOLTAGE
#define MIN_VOLTAGE         150
#endif

typedef struct {
    uint8_t codes[3];   /* [0]=новейший, [2]=старейший; 0 = пустой слот */
} PSU_StatusHistory_t;

typedef struct {
    uint16_t outputVoltage;
    int16_t  outputCurrent;
    uint32_t outputPower;
    uint8_t  temperature;
    uint8_t  status0;
    uint8_t  status1;
    uint8_t  status2;
    uint8_t  mode;          // 1 = включен (есть выход), 0 = выключен
    bool     online;
    bool     updated;
    bool     forceApply;
    PSU_StatusHistory_t history;
} PSU_State_t;

extern PSU_State_t PSU_State[PSU_MAX_ADDR];
extern uint8_t     PSU_ActiveAddrs[PSU_MAX_MODULES];
extern uint8_t     PSU_ActiveCount;
// В секции extern глобальных переменных
extern int32_t  PSU_TotalCurrent;   // мА
extern uint16_t PSU_TotalVoltage;   // В

/* Суммарные значения для вывода на экран */
extern int32_t  PSU_TotalCurrent;   // мА
extern uint16_t PSU_TotalVoltage;   // В

void PSU_PushStatusCode(uint8_t addr, uint8_t code);

void PSU_Init(void);
void PSU_CAN2_BridgeInit(void);
void PSU_Loop(void);
void PSU_UpdateAll(uint16_t voltage, uint16_t current, uint8_t enable);
void PSU_Enable(uint8_t addr, uint8_t enable);
void PSU_SetHVMode(uint8_t addr, uint8_t enable);
void PSU_SetVoltageCurrent(uint8_t addr, uint16_t voltage, uint32_t current_ma);
void PSU_ClearFault(uint8_t addr);
uint8_t PSU_DecodeStatusBits(uint8_t s0, uint8_t s1, uint8_t s2);

#endif
