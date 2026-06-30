#ifndef EPAPER_TEXT_H
#define EPAPER_TEXT_H

#include <stdint.h>

// Шрифт 8x8 (95 символов: ASCII 32..126)
extern const uint8_t font8x8_basic[95][8];

// Работа с буфером
void epaper_clear_buffer(uint8_t *buf);   // заполнить белым (0xFF)
void epaper_set_pixel(uint8_t *buf, uint16_t x, uint16_t y, uint8_t color); // color: 0=чёрный, 1=белый

// Рисование символов с масштабированием
// scale = 1 -> 8x8, scale = 2 -> 16x16, scale = 3 -> 24x24 ...
void epaper_draw_char(uint8_t *buf, uint16_t x, uint16_t y, char ch,
                      const uint8_t (*font)[8], uint8_t scale);
void epaper_draw_string(uint8_t *buf, uint16_t x, uint16_t y, const char *str,
                        const uint8_t (*font)[8], uint8_t scale);

#endif
