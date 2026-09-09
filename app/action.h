/* Copyright 2023 Dual Tachyon
 * https://github.com/DualTachyon
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

#ifndef APP_ACTION_H
#define APP_ACTION_H

#include "driver/keyboard.h"

//static void ACTION_FlashLight(void)
void ACTION_Power(void);

void ACTION_Monitor(void);

void ACTION_Scan(bool bRestart);

#ifdef ENABLE_VOX
void ACTION_Vox(void);
#endif

#ifdef ENABLE_FMRADIO
void ACTION_FM(void);
#endif

void ACTION_SwitchDemodul(void);

void ACTION_SwitchWidth(void);

void ACTION_SwitchDTMFDecode(void);


#ifdef ENABLE_BLMIN_TMP_OFF
void ACTION_BlminTmpOff(void);
#endif

void ACTION_D_DCD(void);

void ACTION_WIDTH(void);

void ACTION_Handle(KEY_Code_t Key, bool bKeyPressed, bool bKeyHeld);

#ifdef ENABLE_SIDEFUNCTIONS_SEND
void ACTION_SEND_CURRENT(void);
void ACTION_SEND_OTHER(void);
#endif

#ifdef ENABLE_SQL_ADJUST
// Squelch-adjust overlay: a side function latches it, UP/DOWN then step the
// squelch one point at a time until any other key or the inactivity timeout
// closes it again.
#define SQL_ADJUST_TIMEOUT_10MS 300   // 3 s of no keys closes the overlay

extern bool     gSqlAdjustMode;
extern uint16_t gSqlAdjustCountdown_10ms;

void ACTION_SqlAdjust(void);
void SQL_ADJUST_Exit(void);
void SQL_ADJUST_TimeSlice10ms(void);
// true when the key belongs to the overlay and must not be handled elsewhere
bool SQL_ADJUST_ProcessKeys(KEY_Code_t Key, bool bKeyPressed, bool bKeyHeld);
#endif

#endif

