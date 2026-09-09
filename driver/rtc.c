//
// Created by RUPC on 2024/1/30.
//
#include "bsp/dp32g030/rtc.h"
#include "ARMCM0.h"
#include "driver/eeprom.h"
#include "driver/system.h"
#include "ui/helper.h"

uint8_t time[6];

void RTC_INIT() {

    uint32_t correct_freq = 32768 - 1 + ((((RC_FREQ_DELTA & 0x400) >> 10) ? 1 : -1) * (RC_FREQ_DELTA & 0x3ff));
    // 清空PRE_PERIOD, PRE_DECIMAL 和 PRE_ROUND相关位 (clear the PRE_PERIOD, PRE_DECIMAL and PRE_ROUND bits)
    RTC_PRE &= ~((0x7fff << 0) | (0xf << 20) | (0x1 << 24));
    RTC_PRE |= correct_freq//PRE_ROUND=32768HZ-1
               | (0 << 20)//DECIMAL=0
               | (0 << 24);//PRE_PERIOD=8s


    EEPROM_ReadBuffer(0X2BC0, time, 6);

    RTC_Set();

    NVIC_SetPriority(Interrupt2_IRQn, 0);


    RTC_IF |= (1 << 0);//清除中断标志位 (clear the interrupt flag)
    RTC_IE |= (1 << 0);//使能秒中断 (enable the seconds interrupt)

    RTC_CFG |= //(1 << 2)|//打开设置时间功能 (enable the set-time function)
            (1 << 0);//RTC使能 (RTC enable)

    NVIC_EnableIRQ(Interrupt2_IRQn);


}

void RTC_Set() {


    RTC_DR = (2 << 24)//day 2
             | (time[0] / 10 << 20)//YEAR TEN
             | (time[0] % 10 << 16) //YEAR ONE
             | (time[1] / 10 << 12)//MONTH TEN
             | (time[1] % 10 << 8)//MONTH ONE
             | (time[2] / 10 << 4)//DAY TEN
             | (time[2] % 10 << 0);//DAY ONE
    RTC_TR = (time[3] / 10 << 20) //h十位 (tens digit of the hours)
             | (time[3] % 10 << 16)//h个位 (units digit of the hours)
             | (time[4] / 10 << 12)//min十位 (tens digit of the minutes)
             | (time[4] % 10 << 8)//min个位 (units digit of the minutes)
             | (time[5] / 10 << 4)//sec十位 (tens digit of the seconds)
             | (time[5] % 10 << 0);//sec个位 (units digit of the seconds)
    RTC_CFG |= (1 << 2);//打开设置时间功能 (enable the set-time function)

}

void RTC_Get() {
    time[0] = (RTC_TSDR >> 20 & 0b1111) * 10 + (RTC_TSDR >> 16 & 0b1111);
    time[1] = (RTC_TSDR >> 12 & 0b1) * 10 + (RTC_TSDR >> 8 & 0b1111);
    time[2] = (RTC_TSDR >> 4 & 0b1111) * 10 + (RTC_TSDR >> 0 & 0b1111);

    time[3] = (RTC_TSTR >> 20 & 0b111) * 10 + (RTC_TSTR >> 16 & 0b1111);
    time[4] = (RTC_TSTR >> 12 & 0b111) * 10 + (RTC_TSTR >> 8 & 0b1111);
    time[5] = (RTC_TSTR >> 4 & 0b111) * 10 + (RTC_TSTR >> 0 & 0b1111);

}
