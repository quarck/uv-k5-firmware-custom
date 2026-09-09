This code is a form from [losehu/uv-k5-firmware-custom](https://github.com/losehu/uv-k5-firmware-custom) - all credit goes there.

# [K5Web]( https://k5.vicicode.com/)
* Supports online firmware functionality compilation, no need to install the compilation environment!!
* Doppler satellite, boot image text, SI4732 SSB patch frequency writing method!
* Supports **Workshop**, register and log in to upload custom firmware and boot images!!!

Please visit: [K5Web]( https://k5.vicicode.com/)

# [Custom Bootloader](https://github.com/losehu/uv-k5-bootloader-custom)
* Achieves firmware switching by creating a bootloader loaded into RAM
* Can switch any firmware
* Currently only applicable to 4Mib EEPROM, can be easily expanded to other EEPROM sizes by modifying the code
  
# [Standalone Doppler Satellite Firmware](https://github.com/losehu/uv-k5-firmware-custom/tree/doppler)
* Can independently calculate up to 40 satellites’ angles, altitudes, speeds, distances, and frequency offsets
* Requires expansion of 2Mit or larger EEPROM
* Can display satellite positions with azimuth map
  
# [Larger Firmware System](https://github.com/losehu/uv-k5-system-custom/)
* Allows UVK5 to load firmware larger than 64KB, up to 512MB
* A larger firmware can implement all functions in a single firmware!!!
* In development... Stay tuned

# Version Description

* The current versions are: **LOSEHUxxx**, **LOSEHUxxxK**, **LOSEHUxxxH**, **LOSEHUxxxE**, **LOSEHUxxxEK**, **LOSEHUxxxHS**
* 
| Version       | Language | EEPROM Requirement | MDC1200 | Doppler Mode | Spectrum | Radio | Chinese Channel Name | Custom Boot Image | Boot Image | Chinese Input Method | SMS |
|---------------|----------|---------------------|---------|--------------|----------|-------|----------------------|-------------------|------------|----------------------|-----|
| LOSEHUxxx     | Chinese | No expansion needed  | ✅      | ❌           | ✅       | ✅    | ❌                   | ❌                | ❌         | ❌                   | ❌  |
| LOSEHUxxxK    | Chinese | 1Mib or above       | ✅      | ✅           | ✅       | ✅    | ✅                   | ✅                | ✅         | ❌                   | ❌  |
| LOSEHUxxxH    | Chinese | 2Mib or above       | ✅      | ✅           | ✅       | ✅    | ✅                   | ✅                | ✅         | ✅                   | ❌  |
| LOSEHUxxxHS   | Chinese | 2Mib or above       | ❌      | ❌           | ✅       | ✅    | ✅                   | ✅                | ✅         | ✅                   | ❌  |
| LOSEHUxxxE    | English | No expansion needed  | ✅      | ❌           | ✅       | ✅    | ❌                   | ❌                | ❌         | ❌                   | ✅  |
| LOSEHUxxxEK   | English | 1Mib or above       | ✅      | ✅           | ✅       | ✅    | ❌                   | ✅                | ✅         | ❌                   | ❌  |

### Explanation:
- ✅ means the feature is supported
- ❌ means the feature is not supported
- The "Radio" feature in the LOSEHUxxxHS version specifically refers to the SI4732 radio

# Multi-functional K5/6 Firmware

This firmware is based on modifications and merges of multiple open-source firmware, featuring the most diverse
functions:
* **Larger EEPROM capacity**
* **Automatic Doppler frequency shift**
* Custom boot logo
* **SI4732 support**
* **Chinese/English support**
* **Chinese input method**
* **GB2312 Chinese interface, channels**
* **Spectrum graph**
* **MDC1200 signaling, contacts**
* **SMS**
* **Signal strength indicator (S meter)**
* **One-touch frequency scanning**
* **Radio receiver**
* **AM fix**
* **SSB demodulation**


# Operating Instructions (Mandatory Reading!!)

| Key              | Function                                                                                                                                                 |
|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| 🐤 **Main Interface** |                                                                                                                                                          |
| **Single Press `Up/Down`** | Adjust frequency (step size is set by menu item `Step Frequency`)                                                                                        |
| **Single Press `Number`** | Quickly input frequency in frequency mode                                                                                                                |
| **Single Press `*`** | Input DTMF to be sent (`A, B, C, D, *, #` correspond to `M, Up, Down, *, F` respectively. Side Key 1 acts as backspace, press PTT key to send)           |
| **Long Press `F`** | Keyboard Lock                                                                                                                                            |
| **Long Press `M`** | Switch modulation mode                                                                                                                                   |
| **Long Press `*`** | In channel mode, activates search list, multiple long presses toggle between lists (1/2/All). In frequency mode, initiates search from current frequency |
| **Long Press `0`/`F+0`** | Open/Close radio receiver(OR SI4732)                                                                                                                     |
| **Long Press `1`/`F+1`** | In channel mode, copies current channel to another VFO                                                                                                   |
| **Long Press `2`/`F+2`** | Switch between A/B channels                                                                                                                              |
| **Long Press `3`/`F+3`** | Switch between frequency/channel                                                                                                                         |
| **Long Press `4`/`F+4`** | One-touch frequency alignment                                                                                                                            |
| **Long Press `5`** | In channel mode, toggles search list                                                                                                                     |
| **Long Press `5`** | In frequency mode, sets search frequency range (from channel A to channel B frequency), press * key to start search                                      |
| **`F+5`** | Spectrum                                                                                                                                                 |
| **Long Press `6`/`F+6`** | Switch transmit power                                                                                                                                    |
| **Long Press `7`/`F+7`** | Voice-activated transmission switch                                                                                                                      |
| **Long Press `8`/`F+8`** | One-touch reverse frequency                                                                                                                              |
| **Long Press `9`/`F+9`** | One-touch call                                                                                                                                           |
| **`F+M`** | Open SMS                                                                                                                                                 |
| **`F+UP`** | Key tone switch                                                                                                                                          |
| **`F+Down`** | Automatic Doppler shift                                                                                                                                  |
| **`F+EXIT`** | Inverts menu navigation (Up/Down)                                                                                                                        |
| **`F+*`** | Scan (Digital/Analog) sub-audio                                                                                                                          |
| **Short Press Side Key 1** | Monitor                                                                                                                                                  |
| **Long Press Side Key 1** | DTMF decoding switch                                                                                                                                     |
| **Short Press Side Key 2** | Set wide/narrow band                                                                                                                                     |
| **Long Press Side Key 2** | Flashlight                                                                                                                                               |
|**Wide/Narrow Band, DTMF decoding, FM/AM/USB Switching**| Integrated into custom **Side Key and M**                                                                                                                |
| 🎤 **SI4732 Radio**          |                                                      |
| **Short press `Side Key 1`, Short press `Side Key 2`** | Change BFO in SSB mode                                      |
| **Short press `5`**                  | Enter frequency, **short press `*`** for decimal point, **short press `MENU`** to confirm                 |
| **Short press `0`**                  | Switch mode (AM/FM/SSB), **short press `F`** to switch LSB/USB                  |
| **Short press `1`, Short press `7`**        | Change step frequency                                               |
| **Short press `4`**                  | Toggle signal strength display                                             |
| **Short press `6`**                  | Change bandwidth                                                 |
| **Short press `2`, Short press `8`**        | Toggle ATT                                                |
| **Short press `3`, Short press `9`**        | Search up/down, **short press `EXIT`** to stop search                                       |
| 🔑 **Doppler Mode**               |                                                      |
| **Short press `5`**                  | Enter time, **short press `*`** for decimal point, **short press `MENU`** to confirm                 |
| **Short press `MENU`**               | Toggle parameters, adjust up/down                                            |
| **Short press `PPT`**                | Transmit                                                   |
| **Short press `Side Key 1`**                | Enable listening                                                 |
                                                                                                                           |
# Eeprom Layout Explanation

> **This table describes upstream LOSEHU, not this fork.** Rows marked 🚫 are
> regions this fork no longer touches: MDC1200, the Chinese fonts and menu
> strings, the pinyin tables and the custom boot image. That code has been
> **deleted**, not merely disabled, so unlike upstream these regions cannot be
> brought back by flipping a build flag, and nothing this firmware does will
> collide with data you store there. See
> [EEPROM map for this fork](#eeprom-map-for-this-fork) for what it actually
> reads and writes.

| Eeprom Address                          | Description                                                                                                                                             |
|----------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| 😭 **General**                          | Version: LOSEHUxxx                                                                                                                                      |
| 0X01D00~0x02000                        | Rarely changed                                                                                                                                          |
| 0X01D00 ~ 0X01E00<br/>0X1F90 ~ 0X01FF0 | **MDC1200** - 22 MDC contacts<br/>Each contact occupies 16B, with the first 2B being MDC ID and the next 14B being contact name                         |
| 0X01FFF                                | **MDC1200** - Number of MDC contacts<br/>🚫 **Not used by this fork** — code removed |
| 0x01FFD~0x01FFE                        | **MDC1200** - MDC ID<br/>🚫 **Not used by this fork** — code removed — this fork had never used this address anyway, it kept the ID at `0x0E91` |
| 0x01FF8~0x01FFC                        | Side key functions                                                                                                                                      |
| 😱 **Expanded Version (K, H)**          | Version: LOSEHUxxxK, LOSEHUxxxH                                                                                                                         |
| 0x02000~0x02012                        | Boot character 1<br/>🚫 **Not used by this fork** — code removed |
| 0x02012~0x02024                        | Boot character 2<br/>🚫 **Not used by this fork** — code removed |
| 0x02024~0x02025                        | Length of boot characters 1 and 2<br/>🚫 **Not used by this fork** — code removed |
| 0x02080~0x02480                        | Boot screen, length 128 (width) * 64/8 = 1024 = 0x400<br/>🚫 **Not used by this fork** — code removed |
| 0x02480~0x0255C                        | gFontBigDigits, length 11 * 20 = 220 = 0XDC<br/>🚫 **Not used by this fork** — code removed — this fork keeps the font in flash |
| 0x0255C~0x0267C                        | gFont3x5, length 96 * 3 = 288 = 0X120<br/>🚫 **Not used by this fork** — code removed — this fork keeps the font in flash |
| 0x0267C~0x028B0                        | gFontSmall, length 96 * 6 = 564 = 0X234<br/>🚫 **Not used by this fork** — code removed — this fork keeps the font in flash |
| 0x028B0~0x02B96                        | Menu encoding, length 53 * 14 = 742 = 0X2E6<br/>🚫 **Not used by this fork** — code removed |
| 0x02BA0~0x02BA9                        | **Doppler** - Satellite names, with the first character first, up to 9 English characters, the last one being '\0'                                      |
| 0x02BAA~0x02BAF                        | **Doppler** - Year (tens and units), month, day, hour, minute, and second of start transit time                                                         |
| 0x02BB0~0x2BB5                         | **Doppler** - Year (tens and units), month, day, hour, minute, and second of departure time                                                             |
| 0x02BB6~0x02BB7                        | **Doppler** - Total transit time (seconds), with the low byte first and the high byte second                                                            |
| 0x02BB8~0x02BB9                        | **Doppler** - Transmitter sub-audio, with the low byte first and the high byte second                                                                   |
| 0x02BBA~0x02BBB                        | **Doppler** - Receiver sub-audio, with the low byte first and the high byte second                                                                      |
| 0x02C00~0x02C64                        | **Doppler** - CTCSS_Options, length 50 * 2 = 100 = 0x64                                                                                                 |
| 0x02C64~0x02D34                        | **Doppler** - DCS_Options, length 104 * 2 = 208 = 0xD0                                                                                                  |
| 0x02BBC~0X02BBF                        | **Doppler** - Difference between start transit time and UNIX timestamp of January 1, 2000, with the low byte first and the high byte second             |
| 0X02BC0~0X02BC5                        | **Doppler** - Year (tens and units), month, day, hour, minute, and second of current time                                                               |
| 0x02E00~0x1E1E6                        | GB2312 Chinese font library, total 6763 * 11 * 12/8 = 111590 = 0x1B3E6<br/>🚫 **Not used by this fork** — code removed |
| 0x1E200~0x20000(MAX)                   | **Doppler** - 2*n (even) second satellite data, 8B per second, including uplink/downlink frequency/10, with the low byte first and the high byte second |
| 😰 **2Mib Expanded Version (H)**        | Version: LOSEHUxxxH                                                                                                                                     |
| 0x20000~0x26B00                        | **Chinese Input Method** - Pinyin index, corresponding number of characters, starting address of characters<br/>🚫 **Not used by this fork** — code removed |
| 0x26B00~0X2A330                        | **Chinese Input Method** - Pinyin Chinese character table<br/>🚫 **Not used by this fork** — code removed |
| 0x3C228~0x40000                        | **SI4732**-patch，Length 0x3DD8，used to update SI4732 firmware                                                                                           |
| 0x3C210~0x3C21C                        | **SI4732**FM、AM、SSB Freq、Mode                                                                                                                           |

> **The frequency-store row above does not apply to this fork** — it lives at
> `0x1FE0`/`0x1FE4`. The SSB patch is at the documented `0x3C228`, but is 8840
> bytes rather than 0x3DD8. See [EEPROM map for this fork](#eeprom-map-for-this-fork).

[Doppler Eeprom Layout Explanation](https://github.com/losehu/uv-k5-firmware-chinese/blob/main/doc/多普勒eeprom详细说明.txt)

# Examples

<p float="left">
  <img src="/images/c1.JPG" width=300 />
  <img src="/images/c2.JPG" width=300 />
  <img src="/images/c3.JPG" width=300 />
  <img src="/images/c4.JPG" width=300 />
</p>

# User Function Customization

You can customize the firmware by enabling/disabling various compilation options.

| Compilation Option                     | Description                                                                                                                     |
|----------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| 🧰 **Quansheng Basic Functions**       | [Quansheng Basic Functions](https://github.com/egzumer/uv-k5-firmware-custom)                                                   |
| ENABLE_UART                            | UART, without this, you cannot configure the radio via PC!                                                                      |
| ENABLE_AIRCOPY                         | AirCopy wireless copy                                                                                                           |
| ENABLE_FMRADIO                         | FM radio function                                                                                                               |
| ENABLE_NOAA                            | NOAA function (only useful in the US)                                                                                           |
| ENABLE_VOICE                           | Voice broadcast                                                                                                                 |
| ENABLE_VOX                             | VOX voice-controlled transmission                                                                                               |
| ENABLE_ALARM                           | TX alarm                                                                                                                        |
| ENABLE_PWRON_PASSWORD                  | Boot password                                                                                                                   |
| ENABLE_DTMF_CALLING                    | DTMF dialing function, call initiation, call reception, group call, contact list, etc.                                          |
| ENABLE_FLASHLIGHT                      | Enable top flashlight LED light (on, blink, SOS)                                                                                |
| ⌚ **Custom Module**                    |                                                                                                                                 |
| ENABLE_BIG_FREQ                        | Large font frequency display (similar to official Quansheng firmware)                                                           |
| ENABLE_KEEP_MEM_NAME                   | Keep channel name when saving memory channel                                                                                    |
| ENABLE_WIDE_RX                         | Receive full range from 18MHz to 1300MHz (although the front end/power amplifier is not designed for the entire range)          |
| ENABLE_TX_WHEN_AM                      | Allow TX when RX is set to AM (always FM)                                                                                       |
| ENABLE_F_CAL_MENU                      | Enable hidden frequency calibration menu for radio                                                                              |
| ENABLE_CTCSS_TAIL_PHASE_SHIFT          | Use standard CTCSS tail phase shift instead of the unique QS 55Hz tone method                                                   |
| ENABLE_BOOT_BEEPS                      | Provide audio feedback for users at startup, indicating the position of the volume knob                                         |
| ENABLE_SHOW_CHARGE_LEVEL               | Display battery charge level while radio is charging                                                                            |
| ENABLE_REVERSE_BAT_SYMBOL              | Mirror battery symbol in status bar (positive pole on right)                                                                    |
| ENABLE_NO_CODE_SCAN_TIMEOUT            | Disable 32-second CTCSS/DCS scan timeout (exit button instead of waiting for timeout to end scan)                               |
| ENABLE_AM_FIX                          | Dynamically adjust front-end gain in AM mode to help prevent AM demodulator saturation, temporarily ignore RSSI level on screen |
| ENABLE_SQUELCH_MORE_SENSITIVE          | Slightly increase squelch sensitivity                                                                                           |
| ENABLE_FASTER_CHANNEL_SCAN             | Increase channel scan speed, but also increase squelch sensitivity                                                              |
| ENABLE_RSSI_BAR                        | Enable RSSI bar graph level in dBm/Sn units, instead of small antenna symbol                                                    |
| ENABLE_AUDIO_BAR                       | Display audio bar level while transmitting                                                                                      |
| ENABLE_COPY_CHAN_TO_VFO                | Copy current channel setting to frequency mode. Long press `1 BAND` in channel mode                                             |
| ENABLE_SPECTRUM                        | Spectrum analyzer, activated by `F` + `5 NOAA`                                                                                  |
| ENABLE_REDUCE_LOW_MID_TX_POWER         | Reduce mid and low power settings even lower                                                                                    |
| ENABLE_BYP_RAW_DEMODULATORS            | Additional BYP (bypass?) and RAW demodulation options, proven not very useful, but available if you want to experiment          |
| ENABLE_SCAN_RANGES                     | Scan range mode for frequency scanning                                                                                          |
| ENABLE_BLOCK                           | EEPROM lock                                                                                                                     |
| ENABLE_WARNING                         | Beep prompt                                                                                                                     |
| ENABLE_CUSTOM_SIDEFUNCTIONS            | Custom side key function                                                                                                        |
| ENABLE_SIDEFUNCTIONS_SEND              | Custom side key function (side key transmit function)                                                                           |
| ENABLE_AUDIO_BAR_DEFAULT               | Default audio bar style                                                                                                         |
| 📡 **Automatic Doppler**               | [Automatic Doppler](https://github.com/losehu/uv-k5-firmware-custom)                                                            |
| ENABLE_DOPPLER                         | Automatic Doppler function                                                                                                      |
| 📧 **SMS**                             | [SMS](https://github.com/joaquimorg/uv-k5-firmware-custom)                                                                      |
| ENABLE_MESSENGER                       | Send and receive short text messages (button = `F` + `MENU`)                                                                    |
| ENABLE_MESSENGER_DELIVERY_NOTIFICATION | Send notification to sender if message received                                                                                 |
| ENABLE_MESSENGER_NOTIFICATION          | Play sound when message received                                                                                                |
| 📱 **MDC1200**                         | [MDC1200](https://github.com/OneOfEleven/uv-k5-firmware-custom)                                                                 |
| ENABLE_MDC1200                         | MDC1200 transmission function                                                                                                   |
| ENABLE_MDC1200_SHOW_OP_ARG             | MDC display head/tail parameter                                                                                                 |
| ENABLE_MDC1200_SIDE_BEEP               | MDC side tone                                                                                                                   |
| ENABLE_MDC1200_CONTACT                 | MDC contact                                                                                                                     |
| 🎛️ **DOCK**                           | [DOCK](https://github.com/nicsure/QuanshengDock)                                                                                |
| ENABLE_DOCK                            | Allow control of the radio via PC, no screen display!                                                                           |
| 🚫 **Debug**                           |                                                                                                                                 |
| ENABLE_AM_FIX_SHOW_DATA                | Display debug data for AM fix                                                                                                   |
| ENABLE_AGC_SHOW_DATA                   | Display ACG parameters                                                                                                          |
| ENABLE_UART_RW_BK_REGS                 | Added two extra commands to read and write BK4819 registers                                                                     |
| ⚠️ **Compilation Options**             |                                                                                                                                 |
| ENABLE_CLANG                           | Experimental, build with clang instead of gcc (if this option is enabled, LTO will be disabled)                                 |
| ENABLE_SWD                             | Use the CPU's SWD port, required for debugging/programming                                                                      |
| ENABLE_OVERLAY                         | CPU FLASH-related content, not needed                                                                                           |
| ENABLE_LTO                             | Reduce the size of the compiled firmware, but may break EEPROM reading (OVERLAY will be disabled after enabling)                |


## Building

Install the toolchain:

```
sudo apt install gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi python3-crcmod
```

then just:

```
make build <PARAM1>=<value1> <PARAM2>=<value2>...
```

With no parameters this builds the configuration set at the top of `Makefile`.
Any `ENABLE_*` flag can be overridden on the command line, e.g.
`make build ENABLE_SPECTRUM=0`.

Two files are produced:

| File | Use |
|---|---|
| `firmware.bin` | raw image, for SWD/OpenOCD |
| `LOSEHU132*.bin` | packed image, for the uploader tools below |

The packed name follows the enabled features (`E` = English, `S` = SI4732).

### Flash budget

The firmware must fit in **61,440 bytes** (60K — the top 4K of flash belongs to
the stock bootloader; see `firmware.ld`). `fw-pack.py` prints usage on every
build:

```
Flash: 56,272 of 61,440 bytes used (91.6%), 5,168 free
```

Going over is a hard link error (`region FLASH overflowed by N bytes`), so an
oversized configuration can never produce a `.bin`.

## Flashing the firmware

This radio runs [losehu's custom bootloader](https://github.com/losehu/uv-k5-bootloader-custom),
whose flash protocol is **not** the stock Quansheng one. `k5tool -wrflash` only
speaks the stock protocol and will not work. Use the bundled `k5flash.py`:

```
python k5flash.py QRCKES.bin        # or firmware.bin
```

It accepts **either** the packed image (`QRCK*.bin`) or the raw build output
(`firmware.bin`). The bootloader programs whatever bytes it is handed straight to
flash, so a packed image is unpacked in memory first — CRC checked, de-obfuscated,
and the 16-byte version block removed. The version string is printed so you can
see what you are about to flash.

Anything that is neither is refused before the erase, with the reason for both
interpretations, rather than writing garbage to flash.

Put the radio into flash mode first. The tool then:

1. waits for the bootloader's `0x0518` beacon and prints its version
2. erases the application area (`0x0530`)
3. streams 256-byte blocks (`0x0519`), each one acknowledged
4. the bootloader reboots itself after the final block

Only flash pages 8-127 are erased. The bootloader itself is never touched, so an
interrupted or failed run is always retryable — return to flash mode and re-run.

Flash mode is selected by an **EEPROM flag, not a key combination**: the
bootloader reads one byte at `0x1FF0` and enters flash mode when it is `2`
(`main.c` in the bootloader source).

[K5Web](https://k5.vicicode.com/) can also flash from a browser.

### EEPROM map for this fork

Where this fork actually puts things, which differs from the upstream layout above:

| Address | Size | Use |
|---|---|---|
| `0x0E90` | 1 | beep control |
| `0x0E91`-`0x0E92` | 2 | *formerly MDC1200 ID* — now written as zero |
| `0x0E93` | 1 | CW pitch (`CWTone` menu item, 10 Hz units) |
| `0x0E95` | 1 | scan resume mode |
| `0x0EA9` | 1 | roger beep — now only `0` (off) or `1` (roger) |
| `0x1FE0`-`0x1FE3` | 4 | SI4732 frequency, FM |
| `0x1FE4`-`0x1FE7` | 4 | SI4732 frequency, shared by AM/LSB/USB/CW |
| `0x1FF0` | 1 | **bootloader** boot mode (`2` = flash mode) |
| `0x1FF8`-`0x1FFC` | 5 | side key functions |
| `0x3C228`-`0x3E4AF` | 8840 | **SI4732 SSB patch** (see below) |

The patch sits at the upstream address `0x3C228`, defined by `PATCH_START` in
`driver/si473x.h`. That is above 64 KB, so writing it needs the 32-bit
`0x052B`/`0x0538` UART commands — which exist only when the firmware is built
with **`ENABLE_EEPROM_32BIT = 1`** (the default here). `k5eeprom.py` picks the
32-bit commands automatically for any address past 64 KB.

#### Upgrading from a build that had MDC1200

`0x0E91`-`0x0E92` held the MDC1200 ID and are now zeroed on the next settings
write. `0x0EA9` (roger beep) previously accepted `0`-`5`, where `2`-`5` selected
the MDC variants; it now accepts `0`-`1` and anything larger reads back as
**off**. So a radio that had roger set to one of the MDC modes will come up with
the roger beep disabled after flashing. Nothing else moves.

#### Regions this fork no longer reads

These held the Chinese fonts and strings, the pinyin tables, the custom boot
image and the MDC1200 contact list. The code that read them has been deleted, so
they are free — and, unlike upstream, cannot be reclaimed by a build flag:

| Region | Size | Formerly |
|---|---|---|
| `0x01D00`-`0x01E00`, `0x1F90`-`0x1FF0` | 352 B | MDC1200 contacts |
| `0x02000`-`0x02480` | 1,152 B | boot text and boot screen |
| `0x02480`-`0x028B0` | 1,072 B | `gFontBigDigits`, `gFont3x5`, `gFontSmall` |
| `0x028B0`-`0x02B96` | 742 B | Chinese menu strings |
| `0x02E00`-`0x1E1E6` | 111,590 B | GB2312 glyph data |
| `0x20000`-`0x2A330` | 41,776 B | pinyin tables |

That is 156,684 bytes in total (~153 KiB), of which 57,078 bytes (~56 KiB) lie
below the 64 KB boundary and so are reachable with the 16-bit `0x051B`/`0x051D`
commands; the rest needs the 32-bit pair.

**`0x40000` and above is still off limits** — that is the custom bootloader's
multi-boot region (firmware table and the RAM-loaded switcher). Below `0x40000`
is safe; at or above it is not.

Two hazards worth knowing:

`settings.c` has a `SETTINGS_WriteBuildOptions()` that writes 8 bytes at `0x1FF0`.
It is currently **never called**; wiring it up would land on the bootloader's
boot-mode flag, and a value of `2` there makes the radio boot into flash mode.

Writing above 64 KB requires `ENABLE_EEPROM_32BIT = 1`. With it set to `0` the
radio simply ignores `0x052B`/`0x0538`, and `k5eeprom.py` will time out rather
than report anything useful.

## Flashing the SI4732 SSB patch (separate, one-time step)

**Flashing the firmware alone is not enough for SSB.** The Si4732 has no SSB
demodulator in ROM — SSB exists only as a Silicon Labs firmware patch that must
be uploaded into the chip's RAM at every power-up. The patch is far too large to
sit in the 60K firmware image, so it lives in EEPROM and the firmware streams it
to the chip whenever SSB mode is entered.

If the patch is missing or in the wrong place, **AM and FM work normally and SSB
is silent** — the upload fails without any error.

The patch shipped here (`ssb_patch_8byte.bin`, 8840 bytes = 1105 rows of 8) was
extracted from the `CEC_051.HF` firmware, which embeds it in flash rather than
EEPROM. Write it once with:

```
python k5eeprom.py write 0x3000 ssb_patch_8byte.bin
```

The write verifies itself by reading everything back. To re-check later:

```
python k5eeprom.py verify 0x3000 ssb_patch_8byte.bin
```

The address and length **must** match `PATCH_START` and `PATCH_SIZE` in
`driver/si473x.h`. `0x3000` sits in the GB2312 font region, which is unused when
`ENABLE_CHINESE_FULL = 0`; a Chinese build would need the patch placed elsewhere.

### Why not k5tool

`k5tool -wree` is limited to the stock 8 KB EEPROM and rejects any offset at or
above `0x2000`. The radio itself is not so limited: the `0x051B`/`0x051D` UART
commands carry a 16-bit offset, so anything below 64 KB is reachable.
`k5eeprom.py` speaks that protocol directly. It cannot go above 64 KB either —
the 32-bit variants (`0x052B`/`0x0538`) are compiled out unless
`ENABLE_CHINESE_FULL == 4`.
