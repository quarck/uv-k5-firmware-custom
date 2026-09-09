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
#include "driver/eeprom.h"
#include <string.h>
#include <stdlib.h>  // abs()
#include "bitmaps.h"
#include "driver/uart.h"
#include "app/dtmf.h"
#include "app/menu.h"
#include "board.h"
#include "dcs.h"
#include "driver/backlight.h"
#include "driver/bk4819.h"
#include "driver/st7565.h"
#include "external/printf/printf.h"
#include "frequencies.h"
#include "helper/battery.h"
#include "misc.h"
#include "settings.h"
#include "ui/helper.h"
#include "ui/inputbox.h"
#include "ui/menu.h"
#include "ui/ui.h"
#include "chinese.h"

void insertNewline(char a[], int index, int len) {

    if (index < 0 || index >= len || len >= 63) {
        return;
    }
    for (int i = len; i >= index; i--) {
        a[i + 1] = a[i];
    }
    a[index] = '\n';
    a[len + 1] = '\0'; // Null-terminate the string
}

const t_menu_item MenuList[] =
        {
//   text,     voice ID,                               menu ID
                {/*"Step",*/   VOICE_ID_FREQUENCY_STEP, MENU_STEP, STR_STEP_FREQ},
                {/*"RxDCS",*/  VOICE_ID_DCS, MENU_R_DCS, STR_RX_DCS}, // was "R_DCS"
                {/*"RxCTCS",*/ VOICE_ID_CTCSS, MENU_R_CTCS, STR_RX_CTCSS}, // was "R_CTCS"
                {/*"TxDCS",*/  VOICE_ID_DCS, MENU_T_DCS, STR_TX_DCS}, // was "T_DCS"
                {/*"TxCTCS",*/ VOICE_ID_CTCSS, MENU_T_CTCS, STR_TX_CTCSS}, // was "T_CTCS"
                {/*"TxODir",*/ VOICE_ID_TX_OFFSET_FREQUENCY_DIRECTION, MENU_SFT_D, STR_TX_OFFSET_DIR}, // was "SFT_D"
                {/*"TxOffs",*/ VOICE_ID_TX_OFFSET_FREQUENCY, MENU_OFFSET, STR_TX_OFFSET_FREQ}, // was "OFFSET"
#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS

                {/*"W/N",*/    VOICE_ID_CHANNEL_BANDWIDTH,             MENU_W_N           ,STR_BANDWIDTH},
#endif

                {/*"BusyCL",*/ VOICE_ID_BUSY_LOCKOUT, MENU_BCL, STR_BUSY_CHANNEL_LOCKOUT}, // was "BCL"
                {/*"Compnd",*/ VOICE_ID_INVALID, MENU_COMPAND, STR_COMPANDER},
                {/*"ChSave",*/ VOICE_ID_MEMORY_CHANNEL, MENU_MEM_CH, STR_SAVE_CHANNEL}, // was "MEM-CH"
                {/*"ChDele",*/ VOICE_ID_DELETE_CHANNEL, MENU_DEL_CH, STR_DELETE_CHANNEL}, // was "DEL-CH"
                {/*"ChName",*/ VOICE_ID_INVALID, MENU_MEM_NAME, STR_NAME_CHANNEL},
                {/*"SList",*/  VOICE_ID_INVALID, MENU_S_LIST, STR_CHANNEL_SCAN_LIST},
                {/*"SList1",*/ VOICE_ID_INVALID, MENU_SLIST1, STR_SCAN_LIST1},
                {/*"SList2",*/ VOICE_ID_INVALID, MENU_SLIST2, STR_SCAN_LIST2},
                {/*"ScnRev",*/ VOICE_ID_INVALID, MENU_SC_REV, STR_SCAN_RESUME_MODE},
                {/*"TxTOut",*/ VOICE_ID_TRANSMIT_OVER_TIME, MENU_TOT, STR_TX_TIMEOUT}, // was "TOT"
                {/*"BatSav",*/ VOICE_ID_SAVE_MODE, MENU_SAVE, STR_POWER_SAVE_MODE}, // was "SAVE"
                {/*"Mic",*/    VOICE_ID_INVALID, MENU_MIC, STR_MIC_GAIN},
                {/*"CWTone",*/ VOICE_ID_INVALID, MENU_CWPITCH, STR_CW_TONE},
                {/*"ChDisp",*/ VOICE_ID_INVALID, MENU_MDF, STR_CHANNEL_DISPLAY_MODE}, // was "MDF"
                {/*"BackLt",*/ VOICE_ID_INVALID, MENU_ABR, STR_AUTO_BACKLIGHT}, // was "ABR"
                {/*"BLMax",*/  VOICE_ID_INVALID, MENU_ABR_MAX, STR_BACKLIGHT_BRIGHTNESS},

                {/*"Roger",*/  VOICE_ID_INVALID, MENU_ROGER, STR_ROGER_BEEP},

                {/*"STE",*/    VOICE_ID_INVALID, MENU_STE, STR_TAIL_TONE_ELIM},
                {/*"RP STE",*/ VOICE_ID_INVALID, MENU_RP_STE, STR_REPEATER_TAIL_TONE_ELIM},
                {/*"1 Call",*/ VOICE_ID_INVALID, MENU_1_CALL, STR_ONE_KEY_CALL},

#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS
                {/*"F1Shrt",*/ VOICE_ID_INVALID,                       MENU_F1SHRT        ,STR_SIDE_KEY1_SHORT_PRESS},
                {/*"F1Long",*/ VOICE_ID_INVALID,                       MENU_F1LONG        ,STR_SIDE_KEY1_LONG_PRESS},
                {/*"F2Shrt",*/ VOICE_ID_INVALID,                       MENU_F2SHRT        ,STR_SIDE_KEY2_SHORT_PRESS},
                {/*"F2Long",*/ VOICE_ID_INVALID,                       MENU_F2LONG        ,STR_SIDE_KEY2_LONG_PRESS},
                {/*"M Long",*/ VOICE_ID_INVALID,                       MENU_MLONG         ,STR_M_KEY_LONG_PRESS},
#endif

#ifdef ENABLE_DTMF_CALLING

                {/*"ANI ID",*/ VOICE_ID_ANI_CODE,                      MENU_ANI_ID        ,DTMF_ID},
#endif
                {/*"UPCode",*/ VOICE_ID_INVALID, MENU_UPCODE, STR_DTMF_UP_CODE},
                {/*"DWCode",*/ VOICE_ID_INVALID, MENU_DWCODE, STR_DTMF_DOWN_CODE},
                {/*"PTT ID",*/ VOICE_ID_INVALID, MENU_PTT_ID, STR_DTMF_PTT_ID},
                {/*"D ST",*/   VOICE_ID_INVALID, MENU_D_ST, STR_DTMF_SIDETONE},
#ifdef ENABLE_DTMF_CALLING

                {/*"D Resp",*/ VOICE_ID_INVALID,                       MENU_D_RSP         ,STR_DTMF_RESPONSE},
                {/*"D Hold",*/ VOICE_ID_INVALID,                       MENU_D_HOLD        ,STR_DTMF_HOLD},
#endif
                {/*"D Prel",*/ VOICE_ID_INVALID, MENU_D_PRE, STR_DTMF_PRELOAD},
#ifdef ENABLE_DTMF_CALLING
#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS

                {/*"D Decd",*/ VOICE_ID_INVALID,                       MENU_D_DCD         ,STR_DTMF_DECODE},
#endif
                {/*"D List",*/ VOICE_ID_INVALID,                       MENU_D_LIST        ,STR_DTMF_CONTACTS},
#endif
                {/*"D Live",*/ VOICE_ID_INVALID, MENU_D_LIVE_DEC, STR_DTMF_LIVE_DISPLAY}, // live DTMF decoder
#ifdef ENABLE_AM_FIX//1
                {/*"AM Fix",*/ VOICE_ID_INVALID,                       MENU_AM_FIX        ,STR_AM_AUTO_GAIN},
#endif
#ifdef ENABLE_AM_FIX_TEST1//0
                {/*"AM FT1",*/ VOICE_ID_INVALID,                       MENU_AM_FIX_TEST1  ,""},
#endif

                {/*"RxMode",*/ VOICE_ID_DUAL_STANDBY, MENU_TDR, STR_RX_TX_MODE},
                {/*"Sql",*/    VOICE_ID_SQUELCH, MENU_SQL, STR_SQUELCH_LEVEL},

                // hidden menu items from here on
                // enabled if pressing both the PTT and upper side button at power-on
                {/*"F Lock",*/ VOICE_ID_INVALID, MENU_F_LOCK, STR_BAND_UNLOCK},
//                {/*"Tx 200",*/ VOICE_ID_INVALID,                       MENU_200TX         ,STR_TX_200M}, // was "200TX"
//                {/*"Tx 350",*/ VOICE_ID_INVALID,                       MENU_350TX         ,STR_TX_350M}, // was "350TX"
//                {/*"Tx 500",*/ VOICE_ID_INVALID,                       MENU_500TX         ,STR_TX_500M}, // was "500TX"
//                {/*"350 En",*/ VOICE_ID_INVALID,                       MENU_350EN         ,STR_RX_350M}, // was "350EN"
#ifdef ENABLE_F_CAL_MENU//0
                {/*"FrCali",*/ VOICE_ID_INVALID,                       MENU_F_CALI        ,""}, // reference xtal calibration
#endif
                {/*"BatCal",*/ VOICE_ID_INVALID, MENU_BATCAL, STR_BATTERY_CALIBRATION}, // battery voltage calibration
                {/*"BatTyp",*/ VOICE_ID_INVALID, MENU_BATTYP, STR_BATTERY_CAPACITY}, // battery type 1600/2200mAh
                {/*"Reset",*/  VOICE_ID_INITIALISATION, MENU_RESET,
                               STR_SETTINGS_RESET}, // might be better to move this to the hidden menu items ?

                {/*"",*/       VOICE_ID_INVALID, 0xff, "\x00"}  // end of list - DO NOT delete or move this this
        };

#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS
const char gSubMenu_W_N[][7] =//7

        {
//                "WIDE",
//                "NARROW"
                STR_WIDE_BAND,
               STR_NARROW_BAND
        };
#endif
const char gSubMenu_SFT_D[][4] =

        {
//                "OFF",
//                "+",
//                "-"
                STR_TX_EQ_RX,
                STR_TX_EQ_RX_PLUS_OFFSET,
                STR_TX_EQ_RX_MINUS_OFFSET

        };


const char gSubMenu_OFF_ON[][4] =


        {
//                "OFF",
//                "ON"
                STR_OFF,
                STR_ON
        };

const char gSubMenu_SAVE[][4] =//4
        {
//                "OFF",
//                "1:1",
//                "1:2",
//                "1:3",
//                "1:4"

                STR_OFF,
                STR_LEVEL_ONE,
                STR_LEVEL_TWO,
                STR_LEVEL_THREE,
                STR_LEVEL_FOUR

        };
const char gSubMenu_TOT[][7] = //7
        {
//                "30 sec",
//                "1 min",
//                "2 min",
//                "3 min",
//                "4 min",
//                "5 min",
//                "6 min",
//                "7 min",
//                "8 min",
//                "9 min",
//                "15 min"

                STR_THIRTY_SECONDS,
                STR_ONE_MINUTE,
                STR_TWO_MINUTES,
                STR_THREE_MINUTES,
                STR_FOUR_MINUTES,
                STR_FIVE_MINUTES,
                STR_SIX_MINUTES,
                STR_SEVEN_MINUTES,
                STR_EIGHT_MINUTES,
                STR_NINE_MINUTES,
                STR_FIFTEEN_MINUTES

        };

const char *const gSubMenu_RXMode[] =
        {

//                "MAIN\nONLY",        // TX and RX on main only
//                "DUAL RX\nRESPOND", // Watch both and respond
//                "CROSS\nBAND",        // TX on main, RX on secondary
//                "MAIN TX\nDUAL RX"    // always TX on main, but RX on both
                STR_MAIN_CH_RX_TX,        // TX and RX on main only
                STR_DUAL_CH_RX, // Watch both and respond
                STR_MAIN_TX_SUB_RX,        // TX on main, RX on secondary
                STR_MAIN_TX_DUAL_RX    // always TX on main, but RX on both

        };

#ifdef ENABLE_VOICE
const char gSubMenu_VOICE[][4] =
{
    "OFF",
    "CHI",
    "ENG"
};
#endif
const char gSubMenu_SC_REV[][8] =//8


        {
//                "TIMEOUT",
//                "CARRIER",
//                "STOP"
                STR_RESUME_5S_AFTER_SIGNAL,
                STR_RESUME_WHEN_CARRIER_STOPS,
                STR_STOP_ON_SIGNAL

        };

const char *const gSubMenu_MDF[] =
        {
//                "FREQ",
//                "CHANNEL\nNUMBER",
//                "NAME",
//                "NAME\n+\nFREQ"
                STR_FREQUENCY,
                STR_CHANNEL_NUMBER,
                STR_NAME,
                STR_NAME_PLUS_FREQ
        };

#ifdef ENABLE_ALARM
const char gSubMenu_AL_MOD[][5] =
{
    "SITE",
    "TONE"
};
#endif
#ifdef ENABLE_DTMF_CALLING

const char gSubMenu_D_RSP[][11] =//11

        {
//                "DO\nNOTHING",
//                "RING",
//                "REPLY",
//                "BOTH"
                STR_NO_RESPONSE,
                STR_LOCAL_RING,
                STR_REPLY_RESPONSE,
               STR_LOCAL_RING_AND_REPLY
        };
#endif

const char *const gSubMenu_PTT_ID[] =
        {
//                "OFF",
//                "UP CODE",
//                "DOWN CODE",
//                "UP+DOWN\nCODE",
//                "APOLLO\nQUINDAR"
                STR_NO_SEND,
                STR_UP_CODE,
                STR_DOWN_CODE,
                STR_UP_PLUS_DOWN_CODE,
                STR_QUINDAR_CODE
        };




const char gSubMenu_ROGER[][15] =

        {
//                "OFF",
//                "ROGER",
//                "MDC"

                STR_OFF,
                STR_ROGER_END_TONE
        };

const char gSubMenu_RESET[][4] =//4


        {
//                "VFO",
//                "ALL"
                STR_VFO_SETTINGS,
                STR_ALL_SETTINGS
        };

const char *const gSubMenu_F_LOCK[] =
        {
                "DEFAULT+\n137-174\n400-470",
                "FCC HAM\n144-148\n420-450",
                "CE HAM\n144-146\n430-440",
                "GB HAM\n144-148\n430-440",

//                "DISABLE\nALL",
//                "UNLOCK\nALL",
                STR_DISABLE_ALL,
                STR_UNLOCK_ALL,
        };

const char gSubMenu_BACKLIGHT[][7] =//7

        {
//                "OFF",
//                "5 sec",
//                "10 sec",
//                "20 sec",
//                "1 min",
//                "2 min",
//                "4 min",
//                "ON"
                STR_OFF,
                STR_FIVE_SECONDS,
                STR_TEN_SECONDS,
                STR_TWENTY_SECONDS,
                STR_ONE_MINUTE,
                STR_TWO_MINUTES,
                STR_FOUR_MINUTES,
                STR_ON

        };


const char gSubMenu_RX_TX[][6] =//6

        {
//                "OFF",
//                "TX",
//                "RX",
//                "TX/RX"
                STR_OFF,
                STR_ON_TX,
                STR_ON_RX,
                STR_ON_TX_AND_RX
        };

#ifdef ENABLE_AM_FIX_TEST1
const char gSubMenu_AM_fix_test1[][8] =
{
    "LNA-S 0",
    "LNA-S 1",
    "LNA-S 2",
    "LNA-S 3"
};
#endif


const char gSubMenu_BATTYP[][8] =
        {
                "1600mAh",
                "2200mAh"
        };

#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS
const t_sidefunction SIDEFUNCTIONS[] =
        {
               {STR_OFF, ACTION_OPT_NONE},
#ifdef ENABLE_FLASHLIGHT
               {STR_FLASHLIGHT, ACTION_OPT_FLASHLIGHT},
#endif
               {STR_SWITCH_TX_POWER, ACTION_OPT_POWER},
               {STR_MONITOR, ACTION_OPT_MONITOR},
               {STR_SCAN, ACTION_OPT_SCAN},
#ifdef ENABLE_VOX
               {STR_VOX_TX,				ACTION_OPT_VOX},
#endif
#ifdef ENABLE_ALARM
                {"ALARM",			ACTION_OPT_ALARM},
#endif
#ifdef ENABLE_FMRADIO
               {STR_FM_RADIO,		ACTION_OPT_FM},
#endif
#ifdef ENABLE_TX1750
                {"1750HZ",			ACTION_OPT_1750},
#endif
               {STR_LOCK_KEYPAD, ACTION_OPT_KEYLOCK},
               {STR_SWITCH_VFO, ACTION_OPT_A_B},
               {STR_SWITCH_VFO_MR_MODE, ACTION_OPT_VFO_MR},
               {STR_SWITCH_MODULATION, ACTION_OPT_SWITCH_DEMODUL},
               {STR_DTMF_DECODE, ACTION_OPT_D_DCD},
               {STR_SWITCH_BANDWIDTH, ACTION_OPT_WIDTH},
#ifdef ENABLE_SQL_ADJUST
               {STR_SQL_ADJUST, ACTION_OPT_SQL},
#endif
#ifdef ENABLE_SIDEFUNCTIONS_SEND
               {STR_MAIN_CH_TX, ACTION_OPT_SEND_CURRENT},
               {STR_SUB_CH_TX, ACTION_OPT_SEND_OTHER},
#endif
#ifdef ENABLE_BLMIN_TMP_OFF
                {"BLMIN\nTMP OFF",  ACTION_OPT_BLMIN_TMP_OFF}, 		//BackLight Minimum Temporay OFF
#endif
        };
const t_sidefunction *gSubMenu_SIDEFUNCTIONS = SIDEFUNCTIONS;
const uint8_t gSubMenu_SIDEFUNCTIONS_size = ARRAY_SIZE(SIDEFUNCTIONS);
#endif

// Derived from the table itself so it tracks the ENABLE_* guards in MenuList[].
// MenuList[] ends with a 0xff sentinel entry that is not a selectable item,
// so the usable count is one less than the array size.
const uint8_t gMenuListSize = ARRAY_SIZE(MenuList) - 1;

bool gIsInSubMenu;
uint8_t gMenuCursor;

int UI_MENU_GetCurrentMenuId() {

    if (gMenuCursor < ARRAY_SIZE(MenuList))
        return MenuList[gMenuCursor].menu_id;
    else
        return MenuList[ARRAY_SIZE(MenuList) - 1].menu_id;
}

uint8_t UI_MENU_GetMenuIdx(uint8_t id) {
    for (uint8_t i = 0; i < ARRAY_SIZE(MenuList); i++)
        if (MenuList[i].menu_id == id)
            return i;
    return 0;
}

int32_t gSubMenuSelection;

// edit box
char edit_original[17]; // a copy of the text before editing so that we can easily test for changes/difference
char edit[17];
int edit_index;


void UI_DisplayMenu(void) {
    const unsigned int menu_list_width = 6; // max no. of characters on the menu list (left side)
    const unsigned int menu_item_x1 = (8 * menu_list_width);//+ 2;
    const unsigned int menu_item_x2 = LCD_WIDTH - 1;
    unsigned int i;
    char String[64];  // bigger cuz we can now do multi-line in one string (use '\n' char)
#ifdef ENABLE_DTMF_CALLING
    char               Contact[16];
#endif

    // clear the screen buffer
    UI_DisplayClear();

#if 1
    // original menu layout



    // invert the current menu list item pixels反转当前菜单项的像素值 ： (invert the pixels of the current menu item)


    // draw vertical separating dotted line绘制垂直分隔的点线 ： (draw the vertical separating dotted line)
//    for (i = 0; i < 7; i++)
//        gFrameBuffer[i][(8 * menu_list_width) + 1] = 0xAA;


    // draw the little sub-menu triangle marker绘制子菜单三角标志： (draw the sub-menu triangle marker)
    //const void *BITMAP_CurrentIndicator = BITMAP_MARKER;

    if (gIsInSubMenu)
        memmove(gFrameBuffer[2] + 41, BITMAP_VFO_Default, sizeof(BITMAP_VFO_Default));
    sprintf(String, "%2u/%u", 1 + gMenuCursor, gMenuListCount);


    UI_PrintStringSmall(String, 2, 0, 6);


    {
    uint8_t size_menu = strlen(MenuList[gMenuCursor].name)*7;
    UI_PrintStringSmall(MenuList[gMenuCursor].name, size_menu < 48 ? (48 - size_menu) / 2 : 0, 0, 0);
    }

#else
    {	// new menu layout .. experimental & unfinished

        const int menu_index = gMenuCursor;  // current selected menu item
        i = 1;

        if (!gIsInSubMenu)
        {
            while (i < 2)
            {	// leading menu items - small text
                const int k = menu_index + i - 2;
                if (k < 0)
                    UI_PrintStringSmall(MenuList[gMenuListCount + k].name, 0, 0, i);  // wrap-a-round
                else
                if (k >= 0 && k < (int)gMenuListCount)
                    UI_PrintStringSmall(MenuList[k].name, 0, 0, i);
                i++;
            }

            // current menu item - keep big n fat
            if (menu_index >= 0 && menu_index < (int)gMenuListCount)
                UI_PrintStringSmall(MenuList[menu_index].name, 0, 0, 2);
            i++;

            while (i < 4)
            {	// trailing menu item - small text
                const int k = menu_index + i - 2;
                if (k >= 0 && k < (int)gMenuListCount)
                    UI_PrintStringSmall(MenuList[k].name, 0, 0, 1 + i);
                else
                if (k >= (int)gMenuListCount)
                    UI_PrintStringSmall(MenuList[gMenuListCount - k].name, 0, 0, 1 + i);  // wrap-a-round
                i++;
            }

            // draw the menu index number/count
            sprintf(String, "%2u.%u", 1 + gMenuCursor, gMenuListCount);
            UI_PrintStringSmall(String, 2, 0, 6);
        }
        else
        if (menu_index >= 0 && menu_index < (int)gMenuListCount)
        {	// current menu item

            UI_PrintStringSmall(MenuList[menu_index].name, 0, 0, 0);
//			UI_PrintStringSmall(String, 0, 0, 0);
        }
    }
#endif

    // **************

    memset(String, 0, sizeof(String));

    bool already_printed = false;
/* Brightness is set to max in some entries of this menu. Return it to the configured brightness
	   level the "next" time we enter here.I.e., when we move from one menu to another.
	   It also has to be set back to max when pressing the Exit key. */

    BACKLIGHT_TurnOn();
    switch (UI_MENU_GetCurrentMenuId()) {
        case MENU_SQL:
            sprintf(String, "%d", gSubMenuSelection);
            break;

        case MENU_CWPITCH:    // stored in 10 Hz units, shown in Hz
            sprintf(String, "%dHz", gSubMenuSelection * 10);
            break;

        case MENU_MIC: {    // display the mic gain in actual dB rather than just an index number
            const uint8_t mic = gMicGain_dB2[gSubMenuSelection];
            sprintf(String, "+%u.%01udB", mic / 2, mic % 2);
        }
            break;

//#ifdef ENABLE_AUDIO_BAR
//            case MENU_MIC_BAR:
//                strcpy(String, gSubMenu_OFF_ON[gSubMenuSelection]);
//                break;
//#endif

        case MENU_STEP: {
            uint16_t step = gStepFrequencyTable[FREQUENCY_GetStepIdxFromSortedIdx(gSubMenuSelection)];
            sprintf(String, "%d.%02ukHz", step / 100, step % 100);
            break;
        }

//        case MENU_TXP:
//            strncpy(String, gSubMenu_TXP[gSubMenuSelection], sizeof(gSubMenu_TXP[gSubMenuSelection]));
//            String[sizeof(gSubMenu_TXP[gSubMenuSelection])] = '\0';
//
//
//            break;

        case MENU_R_DCS:
        case MENU_T_DCS:
            if (gSubMenuSelection == 0)
                //translate
#ifdef test
                strcpy(String, "OFF");

#else
                strcpy(String, STR_OFF);

#endif


            else if (gSubMenuSelection < 105)
                sprintf(String, "D%03oN", DCS_Options[gSubMenuSelection - 1]);
            else
                sprintf(String, "D%03oI", DCS_Options[gSubMenuSelection - 105]);

            break;

        case MENU_R_CTCS:
        case MENU_T_CTCS: {
            if (gSubMenuSelection == 0)
                // translate
#ifdef test
                strcpy(String, "OFF");

#else
                //关闭 (off)
                strcpy(String, STR_OFF);

#endif

            else {
                sprintf(String, "%u.%uHz", CTCSS_Options[gSubMenuSelection - 1] / 10,
                        CTCSS_Options[gSubMenuSelection - 1] % 10);
            }

            break;
        }

        case MENU_SFT_D:
            strncpy(String, gSubMenu_SFT_D[gSubMenuSelection], sizeof(gSubMenu_SFT_D[gSubMenuSelection]));
            String[sizeof(gSubMenu_SFT_D[gSubMenuSelection])] = '\0';
            break;

        case MENU_OFFSET:
            if (!gIsInSubMenu || gInputBoxIndex == 0) {
                sprintf(String, "%3d.%05u", gSubMenuSelection / 100000, abs(gSubMenuSelection) % 100000);
                UI_PrintStringSmall(String, menu_item_x1, menu_item_x2, 2);
            } else {
                const char *ascii = INPUTBOX_GetAscii();
                sprintf(String, "%.3s.%.3s  ", ascii, ascii + 3);
                UI_PrintStringSmall(String, menu_item_x1, menu_item_x2, 2);
            }

            UI_PrintStringSmall("MHz", menu_item_x1, menu_item_x2, 4);

            already_printed = true;
            break;
#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS

            case MENU_W_N:

                strcpy(String, gSubMenu_W_N[gSubMenuSelection]);
                break;
#endif

        case MENU_ABR:
            strcpy(String, gSubMenu_BACKLIGHT[gSubMenuSelection]);


//            BACKLIGHT_SetBrightness(-1);
            break;

            // case MENU_ABR_MIN:
        case MENU_ABR_MAX:
            sprintf(String, "%d", gSubMenuSelection);
            if (gIsInSubMenu)
                BACKLIGHT_SetBrightness(gSubMenuSelection);
//            else
//                BACKLIGHT_SetBrightness(-1);
            break;

//        case MENU_AM:
//            strcpy(String, gModulationStr[gSubMenuSelection]);
//
//            break;

#ifdef ENABLE_AM_FIX_TEST1
            case MENU_AM_FIX_TEST1:
                strcpy(String, gSubMenu_AM_fix_test1[gSubMenuSelection]);
//				gSetting_AM_fix = gSubMenuSelection;
                break;
#endif


        case MENU_COMPAND:
            strcpy(String, gSubMenu_RX_TX[gSubMenuSelection]);


            break;

#ifdef ENABLE_AM_FIX
            case MENU_AM_FIX:
#endif
        case MENU_BCL:
            //     case MENU_BEEP:
//        case MENU_S_ADD1:
//        case MENU_S_ADD2:
        case MENU_STE:
        case MENU_D_ST:
#ifdef ENABLE_DTMF_CALLING
#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS

            case MENU_D_DCD:
#endif
#endif
        case MENU_D_LIVE_DEC:
#ifdef ENABLE_NOAA
            case MENU_NOAA_S:
#endif
//        case MENU_350TX:
//        case MENU_200TX:
//        case MENU_500TX:
//        case MENU_350EN:
            strcpy(String, gSubMenu_OFF_ON[gSubMenuSelection]);

            break;

        case MENU_MEM_CH:
        case MENU_1_CALL:
        case MENU_DEL_CH: {
            const bool valid = RADIO_CheckValidChannel(gSubMenuSelection, false, 1);

            UI_GenerateChannelStringEx(String, valid, gSubMenuSelection);
            UI_PrintStringSmall(String, menu_item_x1 - 12, menu_item_x2, 2);

            if (valid && !gAskForConfirmation) {    // show the frequency so that the user knows the channels frequency
                const uint32_t frequency = SETTINGS_FetchChannelFrequency(gSubMenuSelection);
                sprintf(String, "%u.%05u", frequency / 100000, frequency % 100000);
                UI_PrintStringSmall(String, menu_item_x1 - 12, menu_item_x2, 5);
            }
            SETTINGS_FetchChannelName(String, gSubMenuSelection);
            UI_PrintStringSmall(String[0] ? String : "--", menu_item_x1 - 12, menu_item_x2, 3);
            already_printed = true;
            break;
        }
        case MENU_MEM_NAME: { //输入法显示 (input method display)
//ok


            const bool valid = RADIO_CheckValidChannel(gSubMenuSelection, false, 1);
            UI_GenerateChannelStringEx(String, valid, gSubMenuSelection);
            UI_PrintStringSmall(String, menu_item_x1 - 12, menu_item_x2, 2);

            if (valid) {
                const uint32_t frequency = SETTINGS_FetchChannelFrequency(gSubMenuSelection);
                //bug way
                char tmp_name[17] = {0};
                SETTINGS_FetchChannelName(tmp_name, gSubMenuSelection);

                if (!gIsInSubMenu)
                    edit_index = -1;
                if (edit_index < 0) {    // show the channel name
                    SETTINGS_FetchChannelName(String, gSubMenuSelection);
                    char *pPrintStr = String[0] ? String : "--";
                    UI_PrintStringSmall(pPrintStr, menu_item_x1 - 12, menu_item_x2, 3);

                }

//
                else {


                    UI_PrintStringSmall(edit, menu_item_x1 - 12, menu_item_x2, 3);

                    if (edit_index < MAX_EDIT_INDEX) {
//#if ENABLE_CHINESE_FULL == 4
//                        show_move_flag=1;
//#endif


                        gFrameBuffer[4][menu_item_x1 - 12 + 7 * edit_index +
                                        (((menu_item_x2 - menu_item_x1 + 12) - (7 * MAX_EDIT_INDEX)) + 1) / 2 + 3] |=
                                3 << 6;
                        gFrameBuffer[4][menu_item_x1 - 12 + 7 * edit_index +
                                        (((menu_item_x2 - menu_item_x1 + 12) - (7 * MAX_EDIT_INDEX)) + 1) / 2 + 4] |=
                                3 << 6;



                    }
                }

//NOT OK
//                sprintf(String, "%d", edit_index);
//                UI_PrintStringSmall(String, 0, 0, 1);
//                sprintf(String, "%d", gIsInSubMenu);
//                UI_PrintStringSmall(String, 20, 0, 1);
//
//                sprintf(String,"%d",edit[2]);
//                UI_PrintStringSmall(String, 0, 0, 3);


                if (!gAskForConfirmation) {    // show the frequency so that the user knows the channels frequency
                    sprintf(String, "%u.%05u", frequency / 100000, frequency % 100000);
                    {
//                        show_move_flag = 1;
                        UI_PrintStringSmall(String, menu_item_x1 - 12, menu_item_x2, 5);
                    }
                }
            }

            already_printed = true;

            break;
        }

        case MENU_SAVE:
            strcpy(String, gSubMenu_SAVE[gSubMenuSelection]);


            break;

        case MENU_TDR:
            strcpy(String, gSubMenu_RXMode[gSubMenuSelection]);


            break;

        case MENU_TOT:
            strcpy(String, gSubMenu_TOT[gSubMenuSelection]);


            break;

#ifdef ENABLE_VOICE
            case MENU_VOICE:
                strcpy(String, gSubMenu_VOICE[gSubMenuSelection]);
                break;
#endif

        case MENU_SC_REV:


            strcpy(String, gSubMenu_SC_REV[gSubMenuSelection]);


            break;

        case MENU_MDF:


            strcpy(String, gSubMenu_MDF[gSubMenuSelection]);


            break;

        case MENU_RP_STE:
            if (gSubMenuSelection == 0)
//translate
#ifdef test
                strcpy(String, "OFF");

#else
                //关闭 (off)
                strcpy(String, STR_OFF);

#endif


            else
                sprintf(String, "%d*100ms", gSubMenuSelection);
            break;

        case MENU_S_LIST:
            if (gSubMenuSelection < 2)

                //translate

#ifdef test
                sprintf(String, "list %u", 1 + gSubMenuSelection);

#else  //！！列表 (!! list)
                sprintf(String, STR_LIST" %u", 1 + gSubMenuSelection);

#endif

            else

#ifdef test
                strcpy(String, "ALL");

#else
                //全部 (all)
                strcpy(String, STR_ALL);

#endif
            break;

#ifdef ENABLE_ALARM
            case MENU_AL_MOD:
                sprintf(String, gSubMenu_AL_MOD[gSubMenuSelection]);
                break;
#endif
#ifdef ENABLE_DTMF_CALLING
            case MENU_ANI_ID:

                strcpy(String, gEeprom.ANI_DTMF_ID);
                break;
#endif

        case MENU_UPCODE:

            sprintf(String, "%.8s\n%.8s", gEeprom.DTMF_UP_CODE, gEeprom.DTMF_UP_CODE + 8);
            break;

        case MENU_DWCODE:
            sprintf(String, "%.8s\n%.8s", gEeprom.DTMF_DOWN_CODE, gEeprom.DTMF_DOWN_CODE + 8);
            break;
#ifdef ENABLE_DTMF_CALLING
            case MENU_D_RSP:
                strcpy(String, gSubMenu_D_RSP[gSubMenuSelection]);


                break;

            case MENU_D_HOLD:
                sprintf(String, "%ds", gSubMenuSelection);
                break;
#endif
        case MENU_D_PRE:
            sprintf(String, "%d*10ms", gSubMenuSelection);
            break;

        case MENU_PTT_ID:
            strcpy(String, gSubMenu_PTT_ID[gSubMenuSelection]);


            break;

//        case MENU_BAT_TXT:
//            strcpy(String, gSubMenu_BAT_TXT[gSubMenuSelection]);
//
//
//            break;
#ifdef ENABLE_DTMF_CALLING
            case MENU_D_LIST:
                gIsDtmfContactValid = DTMF_GetContact((int) gSubMenuSelection - 1, Contact);
                if (!gIsDtmfContactValid)
                    strcpy(String, "NULL");
                else
                    memcpy(String, Contact, 8);
                break;
#endif
        case MENU_ROGER:
            strcpy(String, gSubMenu_ROGER[gSubMenuSelection]);


            break;

//        case MENU_VOL:
//            sprintf(String, "%u.%02uV\n%u%%",
//                    gBatteryVoltageAverage / 100, gBatteryVoltageAverage % 100,
//                    BATTERY_VoltsToPercent(gBatteryVoltageAverage));
//            break;

        case MENU_RESET:
            strcpy(String, gSubMenu_RESET[gSubMenuSelection]);


            break;

        case MENU_F_LOCK:
//            if (!gIsInSubMenu && gUnlockAllTxConfCnt > 0&& gUnlockAllTxConfCnt < 10)
//                strcpy(String, "READ\nMANUAL");
//
//            else
            strcpy(String, gSubMenu_F_LOCK[gSubMenuSelection]);


            break;

#ifdef ENABLE_F_CAL_MENU
            case MENU_F_CALI:
                {
                    const uint32_t value   = 22656 + gSubMenuSelection;
                    const uint32_t xtal_Hz = (0x4f0000u + value) * 5;

                    writeXtalFreqCal(gSubMenuSelection, false);

                    sprintf(String, "%d\n%u.%06u\nMHz",
                        gSubMenuSelection,
                        xtal_Hz / 1000000, xtal_Hz % 1000000);
                }
                break;
#endif

        case MENU_BATCAL: {
            const uint16_t vol = (uint32_t) gBatteryVoltageAverage * gBatteryCalibration[3] / gSubMenuSelection;
            sprintf(String, "%u.%02uV\n%u", vol / 100, vol % 100, gSubMenuSelection);
            break;
        }

        case MENU_BATTYP:
            strcpy(String, gSubMenu_BATTYP[gSubMenuSelection]);

            break;

#ifdef ENABLE_CUSTOM_SIDEFUNCTIONS
            case MENU_F1SHRT:
            case MENU_F1LONG:
            case MENU_F2SHRT:
            case MENU_F2LONG:
            case MENU_MLONG:
                strcpy(String, gSubMenu_SIDEFUNCTIONS[gSubMenuSelection].name);
                break;
#endif

    }

    if (!already_printed) {    // we now do multi-line text in a single string

        unsigned int y;
        unsigned int lines = 1;
        unsigned int len = strlen(String);
        bool small = false;

        if (len > 0) {
            // count number of lines
            for (i = 0; i < len; i++) {
                if (String[i] == '\n' && i < (len - 1)) {    // found new line char
                    lines += 1;
                    String[i] = 0;  // null terminate the line
                }
            }

            if (lines > 3) {    // use small text
                small = true;
                if (lines > 7)
                    lines = 7;
            }

            // center vertically'ish
            if (small)
                y = 3 - ((lines + 0) / 2);  // untested
            else
                y = 2 - ((lines + 0) / 2);

            // draw the text lines
            for (i = 0; i < len && lines > 0; lines--) {
                if (small)
                    UI_PrintStringSmall(String + i, menu_item_x1, menu_item_x2, y + 1);
                else
                    UI_PrintStringSmall(String + i, menu_item_x1, menu_item_x2, y + 1);

                // look for start of next line
                while (i < len && String[i] != 0 && String[i] != '\n')
                    i++;

                // hop over the null term char(s)
                while (i < len && (String[i] == 0 || String[i] == '\n'))
                    i++;

                y += small ? 1 : 2;
            }
        }
    }

    if (UI_MENU_GetCurrentMenuId() == MENU_SLIST1 || UI_MENU_GetCurrentMenuId() == MENU_SLIST2) {
        i = (UI_MENU_GetCurrentMenuId() == MENU_SLIST1) ? 0 : 1;

        char *pPrintStr = String;

        if (gSubMenuSelection < 0) {
            pPrintStr = "NULL";
        } else {
            UI_GenerateChannelStringEx(String, true, gSubMenuSelection);
            pPrintStr = String;
        }

        // channel number
        UI_PrintStringSmall(pPrintStr, menu_item_x1 - 12, menu_item_x2, 2);

        SETTINGS_FetchChannelName(String, gSubMenuSelection);
        pPrintStr = String[0] ? String : "--";


// channel name and scan-list
        if (gSubMenuSelection < 0 || !gEeprom.SCAN_LIST_ENABLED[i]) {
            UI_PrintStringSmall(pPrintStr, menu_item_x1 - 12, menu_item_x2, 4);
        } else {
            UI_PrintStringSmall(pPrintStr, menu_item_x1 - 12, menu_item_x2, 4);

//
//            if (IS_MR_CHANNEL(gEeprom.SCANLIST_PRIORITY_CH1[i])) {
//                sprintf(String, "PRI%d:%u", 1, gEeprom.SCANLIST_PRIORITY_CH1[i] + 1);
//                UI_PrintStringSmall(String, menu_item_x1 - 12, menu_item_x2, 3);
//            }
//
//            if (IS_MR_CHANNEL(gEeprom.SCANLIST_PRIORITY_CH2[i])) {
//                sprintf(String, "PRI%d:%u", 2, gEeprom.SCANLIST_PRIORITY_CH2[i] + 1);
//                UI_PrintStringSmall(String, menu_item_x1 - 12, menu_item_x2, 6);
//            }

        }
    }


    if ((UI_MENU_GetCurrentMenuId() == MENU_R_CTCS || UI_MENU_GetCurrentMenuId() == MENU_R_DCS) && gCssBackgroundScan)
        //扫描 (scan)
        UI_PrintStringSmall(STR_SCAN, menu_item_x1, menu_item_x2, 5);

//
//    if (UI_MENU_GetCurrentMenuId() == MENU_UPCODE)
//        if (strlen(gEeprom.DTMF_UP_CODE) > 12)
//            UI_PrintStringSmall(gEeprom.DTMF_UP_CODE + 12, menu_item_x1, menu_item_x2, 5);
//
//    if (UI_MENU_GetCurrentMenuId() == MENU_DWCODE)
//        if (strlen(gEeprom.DTMF_DOWN_CODE) > 12)
//            UI_PrintStringSmall(gEeprom.DTMF_DOWN_CODE + 12, menu_item_x1, menu_item_x2, 5);
#ifdef ENABLE_DTMF_CALLING
    if (UI_MENU_GetCurrentMenuId() == MENU_D_LIST && gIsDtmfContactValid) {

        Contact[11] = 0;
        memcpy(&gDTMF_ID, Contact + 8, 4);
        sprintf(String, "ID:%4s", gDTMF_ID);
        UI_PrintStringSmall(String, menu_item_x1, menu_item_x2, 5);
    }
#endif
    if (UI_MENU_GetCurrentMenuId() == MENU_R_CTCS ||
        UI_MENU_GetCurrentMenuId() == MENU_T_CTCS ||
        UI_MENU_GetCurrentMenuId() == MENU_R_DCS ||
        UI_MENU_GetCurrentMenuId() == MENU_T_DCS
#ifdef ENABLE_DTMF_CALLING
        || UI_MENU_GetCurrentMenuId() == MENU_D_LIST
#endif
            ) {

        sprintf(String, "%2d", gSubMenuSelection);
        UI_PrintStringSmall(String, 105, 0, 1);//small
    }

    if ((UI_MENU_GetCurrentMenuId() == MENU_RESET ||
         UI_MENU_GetCurrentMenuId() == MENU_MEM_CH ||
         UI_MENU_GetCurrentMenuId() == MENU_MEM_NAME ||
         UI_MENU_GetCurrentMenuId() == MENU_DEL_CH) && gAskForConfirmation) {    // display confirmation
        char *pPrintStr = (gAskForConfirmation == 1) ? "SURE?" : "WAIT!";
        if (UI_MENU_GetCurrentMenuId() == MENU_MEM_CH || UI_MENU_GetCurrentMenuId() == MENU_MEM_NAME ||
             UI_MENU_GetCurrentMenuId() == MENU_DEL_CH)
            UI_PrintStringSmall(pPrintStr, menu_item_x1 - 12, menu_item_x2, 5);
        else UI_PrintStringSmall(pPrintStr, menu_item_x1, menu_item_x2, 5);

        gRequestSaveSettings = 1;

    }

    ST7565_BlitFullScreen();
}

//

