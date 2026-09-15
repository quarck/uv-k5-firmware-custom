/* Copyright 2023 fagci
 * https://github.com/fagci
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 *     Unless required by applicable law or agreed to in writing, software
 *     distributed under the License is distributed on an "AS IS" BASIS,
 *     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *     See the License for the specific language governing permissions and
 *     limitations under the License.
 */

#ifndef SPECTRUM_H
#define SPECTRUM_H

#pragma once

#include "keyboard_state.h"

#include "../bitmaps.h"
#include "../board.h"
#include "../bsp/dp32g030/gpio.h"
#include "../driver/bk4819-regs.h"
#include "../driver/bk4819.h"
#include "../driver/gpio.h"
#include "../driver/keyboard.h"
#include "../driver/st7565.h"
#include "../driver/system.h"
#include "../driver/systick.h"
#include "../external/printf/printf.h"
#include "../font.h"
#include "../helper/battery.h"
#include "../misc.h"
#include "../radio.h"
#include "../settings.h"
#include "../ui/helper.h"
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

static const uint8_t DrawingEndY  = 40;
static const uint8_t DrawingTopY  =  8;  // Reserve top 8px for frequency display (gFrameBuffer[0])

static const uint8_t U8RssiMap[] = {
    121,
    115,
    109,
    103,
    97,
    91,
    85,
    79,
    73,
    63,
};

static const uint16_t scanStepValues[] = {
    1,
    10,
    50,
    100,
    250,
    500,
    625,
    833,
    1000,
    1250,
    1500,
    2000,
    2500,
    5000,
    10000,
};

static const uint16_t scanStepBWRegValues[] = {
    //     RX  RXw TX  BW
    // 0b0 000 000 001 01 1000
    // 1    (S_STEP_0_01kHz, index 0)
    0b0000000001011000, // 6.25
    // 10   (S_STEP_0_1kHz,  index 1)
    0b0000000001011000, // 6.25
    // 50   (S_STEP_0_5kHz,  index 2)
    0b0000000001011000, // 6.25
    // 100  (S_STEP_1_0kHz,  index 3)
    0b0000000001011000, // 6.25
    // 250  (S_STEP_2_5kHz,  index 4)
    0b0000000001011000, // 6.25
    // 500  (S_STEP_5_0kHz,  index 5)
    0b0010010001011000, // 6.25
    // 625  (S_STEP_6_25kHz, index 6)
    0b0100100001011000, // 6.25
    // 833  (S_STEP_8_33kHz, index 7)
    0b0110110001001000, // 6.25
    // 1000 (S_STEP_10_0kHz, index 8)
    0b0110110001001000, // 6.25
    // 1250 (S_STEP_12_5kHz, index 9)
    0b0111111100001000, // 6.25
    // 1500 (S_STEP_15_0kHz, index 10)
    0b0011011000101000, // 25
    // 2000 (S_STEP_20_0kHz, index 11)
    0b0011011000101000, // 25
    // 2500 (S_STEP_25_0kHz, index 12)
    0b0011011000101000, // 25
    // 5000 (S_STEP_50_0kHz, index 13)
    0b0011011000101000, // 25
    // 10000 (S_STEP_100_0kHz, index 14)
    0b0011011000101000, // 25
};

static const uint16_t listenBWRegValues[] = {
    0b0011011000101000, // 25
    0b0111111100001000, // 12.5
    0b0100100001011000, // 6.25
};

typedef enum State
{
    SPECTRUM,
    FREQ_INPUT,
    STILL,
} State;

typedef enum StepsCount
{
    STEPS_128,
    STEPS_64,
    STEPS_32,
    STEPS_16,
} StepsCount;

typedef enum ScanStep
{
    S_STEP_0_01kHz,
    S_STEP_0_1kHz,
    S_STEP_0_5kHz,
    S_STEP_1_0kHz,

    S_STEP_2_5kHz,
    S_STEP_5_0kHz,
    S_STEP_6_25kHz,
    S_STEP_8_33kHz,
    S_STEP_10_0kHz,
    S_STEP_12_5kHz,
    S_STEP_15_0kHz,
    S_STEP_20_0kHz,
    S_STEP_25_0kHz,
    S_STEP_50_0kHz,
    S_STEP_100_0kHz,
} ScanStep;

typedef struct SpectrumSettings
{
    uint32_t frequencyChangeStep;
    StepsCount stepsCount;
    ScanStep scanStepIndex;
    uint16_t scanDelay;
    uint16_t rssiTriggerLevel;
    BK4819_FilterBandwidth_t bw;
    BK4819_FilterBandwidth_t listenBw;
    int dbMin;
    int dbMax;
    ModulationMode_t modulationType;
    bool backlightState;
} SpectrumSettings;

typedef struct ScanInfo
{
    uint16_t rssi, rssiMin, rssiMax;
    uint16_t i, iPeak;
    uint32_t f, fPeak;
    uint16_t scanStep;
    uint16_t measurementsCount;
} ScanInfo;

typedef struct PeakInfo
{
    uint16_t t;
    uint16_t rssi;
    uint32_t f;
    uint16_t i;
} PeakInfo;

void APP_RunSpectrum(void);

// F+7 runs the same analyser with the live UART stream on: once a second it
// sends the strongest reading each bin saw in that second. A maximum, not a
// mean, so nothing here needs floating point - the firmware has no room for
// the soft-float that a power average drags in.
//
// One packet per second, little-endian, 152 bytes:
//
//   0   2  magic "K5"
//   2   1  stream format version (2; 1 was a 10 s power mean)
//   3   1  bins actually measured, 16/32/64/128 - the rest of the payload is 0
//   4   2  sequence, wraps at 65536 - a gap means packets were lost
//   6   4  seconds since the stream started
//  10   4  frequency of bin 0, 10 Hz units
//  14   2  bin spacing, 10 Hz units
//  16   2  sweeps completed in this second (0 = the analyser was listening)
//  18   2  dBm of a zero byte (int16, -185)
//  20   1  dB per step (1)
//  21   1  band correction already applied (int8, informational)
//  22 128  one byte per bin, byte = dBm + 185, always 128 bytes
// 150   2  CRC-16/XMODEM over bytes 0..149 (CRC_Calculate1, driver/crc.c)
//
#define SPECTRUM_STREAM_VERSION  2
#define SPECTRUM_STREAM_HEAD     22
#define SPECTRUM_STREAM_BINS     128
#define SPECTRUM_STREAM_BYTES    (SPECTRUM_STREAM_HEAD + SPECTRUM_STREAM_BINS + 2)
#define SPECTRUM_STREAM_DBM_BASE (-185)
#define SPECTRUM_STREAM_RSSI_OFF (-160)   // dBm = rssi/2 + this + band correction

void APP_RunSpectrumStream(void);

// Reached into by the Si4732 app (app/si.c), which reuses the spectrum's
// frequency entry and its battery indicator rather than carrying its own.
extern uint32_t   tempFreq;
extern char       freqInputString[11];
extern uint8_t    freqInputIndex;
extern uint8_t    freqInputDotIndex;
extern KEY_Code_t freqInputArr[10];
extern State      currentState, previousState;

void SetState(State state);
void ResetFreqInput(void);
void UpdateFreqInput(KEY_Code_t key);
void RenderFreqInput(void);
void FreqInput(void);
void DrawPower(void);

#endif /* ifndef SPECTRUM_H */

// vim: ft=c
