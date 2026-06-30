#ifndef YRD0150BBS810F0MP_M7_H
#define YRD0150BBS810F0MP_M7_H

#include "stm32f1xx_hal.h"

// ========== Пины управления ==========
#define CS_PORT      GPIOA
#define CS_PIN       GPIO_PIN_4

#define DC_PORT      GPIOB
#define DC_PIN       GPIO_PIN_0

#define RES_PORT     GPIOC
#define RES_PIN      GPIO_PIN_4

#define BUSY_PORT    GPIOC
#define BUSY_PIN     GPIO_PIN_5

// ========== Параметры дисплея ==========
#define MAX_LINE_BYTES    25
#define MAX_COLUMN_BYTES  200
#define ALLSCREEN_BYTES   5000

#define X_Addr_Start      0x00
#define X_Addr_End        0x18      // 24
#define Y_Addr_Start_H    0x00
#define Y_Addr_Start_L    0xC7      // 199
#define Y_Addr_End_H      0x00
#define Y_Addr_End_L      0x00

// ========== Callback, вызываемый во время ожидания BUSY ==========
typedef void (*EpaperBusyCb_t)(void);
void Epaper_SetBusyCallback(EpaperBusyCb_t cb);

// ========== Прототипы ==========
void EpaperIO_Init(void);
void Epaper_Initial(void);
void Epaper_Initial_partial(void);
void Epaper_Update_and_Deepsleep_full_update(void);
void Epaper_Update_and_Deepsleep_partial_update(void);
void Display_black(void);
void Display_white(void);
void Display_image_new(uint8_t *BN_DTM);
void Display_image_new_partial_update(uint8_t *BN_DTM);

#endif
