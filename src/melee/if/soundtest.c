#include "soundtest.h"

#include "gm/forward.h"

#include "gm/gm_unsplit.h"
#include "gm/gmmain_lib.h"
#include "if/textlib.h"
#include "if/types.h"
#include "lb/lbarchive.h"
#include "lb/lbaudio_ax.h"
#include "lb/lblanguage.h"
#include "ty/toy.h"
#include "ty/tylist.h"

#include <printf.h>
#include <dolphin/mtx.h>
#include <baselib/cobj.h>
#include <baselib/fog.h>
#include <baselib/gobj.h>
#include <baselib/gobjgxlink.h>
#include <baselib/gobjobject.h>
#include <baselib/gobjplink.h>
#include <baselib/gobjproc.h>
#include <baselib/gobjuserdata.h>
#include <baselib/lobj.h>
#include <baselib/memory.h>
#include <baselib/particle.h>
#include <baselib/sislib.h>
#include <MSL/stdio.h>
#include <MSL/string.h>

// .data
/* 3F9FD0 */ static int un_803F9FD0;
/* 3F9FDC */ static float un_803F9FDC;
/* 3FA070 */ static int un_803FA070;
/* 3FA090 */ static int un_803FA090;
/* 3FA09C */ static float un_803FA09C;
/* 3FA0B0 */ static int un_803FA0B0;
/* 3FA258 */ static struct {
    int x0;
    int x4;
    int x8;
    int xC;
    int x10;
    u8 _pad14[0x14];
    int x28;
    int x2C;
    int x30;
    u8 _pad34[0x104];
    void* x138;
} un_803FA258;
/* 3FA348 */ static u16 un_803FA348;
/* 3FA34C */ static u8 un_803FA34C;
/* 3FA658 */ static int un_803FA658;
/* 3FA8E8 */ static int un_803FA8E8;
/* 3FAA44 */ static u8 un_803FAA44[0xC0];
/* 3FB168 */ static int un_803FB168;
/* 3FB60C */ static u8 un_803FB60C[0xE0];
/* 3FB728 */ static u8 un_803FB728[0xC0];
/* 3FB870 */ static u8 un_803FB870[0xE0];
/* 3FB98C */ static u8 un_803FB98C[0xC0];
/* 3FBA9C */ static u8 un_803FBA9C[0xC0];
/* 3FBB98 */ static u8 un_803FBB98[0xC0];
/* 3FBCAC */ static u8 un_803FBCAC[0xC0];
/* 3FBDC0 */ static u8 un_803FBDC0[0xC0];
/* 3FBFFC */ static u8 un_803FBFFC[0xC0];
/* 3FC0FC */ static u8 un_803FC0FC[0xC0];
/* 3FC22C */ static u8 un_803FC22C[0x1F4];
/* 3FC63C */ static u8 un_803FC63C[0x80];
/* 3FC70C */ static u8 un_803FC70C[0x1BC];
/* 3FC8C8 */ static u8 un_803FC8C8[0x168];
/* 3FCA40 */ static u8 un_803FCA40[0x1A0];
/* 3FCC38 */ static u8 un_803FCC38[0xC0];
/* 3FCE4C */ static u8 un_803FCE4C[0xE0];
/* 3FD064 */ static u8 un_803FD064[0x1C0];
/* 3FD310 */ static u8 un_803FD310[0x1A0];
/* 3FDAF8 */ static u8 un_803FDAF8[0x80];
/* 3FDB9C */ static u8 un_803FDB9C[0x84];

// .sdata
/* 4D5850 */ static int un_804D5850 = 0x7F;
/* 4D5854 */ static int un_804D5854 = 0x7F;
/* 4D5858 */ static int un_804D5858 = 0x7F;
/* 4D585C */ static int un_804D585C = -1;

// .sbss
/* 4D6DA8 */ static int* un_804D6DA8;
/* 4D6DAC */ static int un_804D6DAC;
/* 4D6DB0 */ static int un_804D6DB0;
/* 4D6DB4 */ static int un_804D6DB4;
/* 4D6DB8 */ static int un_804D6DB8;
/* 4D6DBC */ static int un_804D6DBC;
/* 4D6DC0 */ static int un_804D6DC0;

// .sbss (extern)
/* 4D6DC8 */ extern u8 un_804D6DC8;
/* 4D6DCC */ extern s32 un_804D6DCC;
/* 4D6DD0 */ extern float un_804D6DD0;
/* 4D6DD8 */ extern s32 un_804D6DD8;
/* 4D6DDC */ extern s32 un_804D6DDC;
/* 4D6DE0 */ extern s32 un_804D6DE0;
/* 4D6DE4 */ extern s32 un_804D6DE4;
/* 4D6DE8 */ extern s32 un_804D6DE8;
/* 4D6DEC */ extern s32 un_804D6DEC;
/* 4D6DF0 */ extern s32 un_804D6DF0;
/* 4D6DF4 */ extern s32 un_804D6DF4;

// .sdata2 (extern)
/* 4DDC48 */ extern float un_804DDC48;

void un_802FF7DC(void)
{
    lbArchive_LoadSymbols("SmSt.dat", &un_804D6DA8, "smSoundTestLoadData", 0);
    un_803F9FDC = un_804D6DA8[0];
    un_803F9FD0 = un_804D6DA8[1];
    un_803FA070 = un_804D6DA8[2];
    un_803FA090 = un_804D6DA8[3];
    un_803FA09C = un_804D6DA8[4];
    un_803FA0B0 = un_804D6DA8[5];
}

bool un_802FF884(char* unused)
{
    return false;
}

int un_802FF88C(void)
{
    un_804D6DB8 = 0;
    un_804D5858 = 0x7F;
    un_804D5854 = 0x7F;
    un_804D5850 = 0x7F;
    un_804D6DB4 = 0;
    un_804D6DB0 = 0;
    un_804D6DC0 = 0;
    un_804D585C = -1;
    un_804D6DBC = lbAudioAx_80024BD0();
    lbAudioAx_800236DC();
    lbAudioAx_800245D4(0x7F);
    lbAudioAx_800245F4(0x7F);
    lbAudioAx_80024614(0x7F);
    if (un_80302DF0()) {
        un_80302DF8(un_80302DF0(), fn_802FFCC8);
    }
    {
        un_80304138_objalloc_t* x = un_80302DF0();
        x->x4->scale_x = 16.0f;
        x->x4->scale_y = 32.0f;
    }
    return 1;
}

void un_802FF934(void)
{
    lbAudioAx_80024C08(un_804D6DBC);
}

int un_802FF958(void)
{
    u8 tmp = un_804D5854;
    lbAudioAx_800245F4(tmp);
    tmp = un_804D5858;
    lbAudioAx_80024614(tmp);
    tmp = un_804D5850;
    lbAudioAx_800245D4(tmp);
    return 0;
}

int un_802FF99C(int arg0)
{
    u8 tmp = un_804D6DAC;
    lbAudioAx_80024634(tmp);
    un_802FFB58(arg0);
    return 0;
}

/// #un_802FF9DC

int un_802FFB58(int arg0)
{
    if (arg0 == 1) {
        lbAudioAx_80023694();
        lbAudioAx_80023B24(un_804D6DA8[un_804D6DB4]);
    } else if (arg0 == 0) {
        lbAudioAx_80023694();
    }
    return 0;
}

int un_802FFBAC(int arg0)
{
    if (arg0 == 1) {
        if (un_804D585C == un_804D6DB8) {
            int x = (un_804D6DC0 + 1) & 1;
            un_804D6DC0 = x;
            lbAudioAx_80024E50(x);
        } else {
            lbAudioAx_80023F28(un_804D6DB8);
            un_804D6DC0 = 0;
            un_804D585C = un_804D6DB8;
        }
    } else if (arg0 == 0) {
        lbAudioAx_800236DC();
        un_804D585C = -1;
        un_804D6DC0 = 0;
    }
    return 0;
}

bool un_802FFC30(void)
{
    lbAudioAx_800236DC();
    lbAudioAx_800245D4(0x7F);
    lbAudioAx_800245F4(0x7F);
    lbAudioAx_80024614(0x7F);
    return true;
}

bool un_802FFC6C(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80023694();
        lbAudioAx_80024030(0);
        lbAudioAx_800236DC();
        lbAudioAx_800245D4(0x7F);
        lbAudioAx_800245F4(0x7F);
        lbAudioAx_80024614(0x7F);
        gm_801A42F8(MJ_TITLE);
        gm_801A4B60();
    }
    return true;
}

bool fn_802FFCC8(void)
{
    return false;
}

/// #un_802FFCD0

void un_802FFD94(int arg0, void* arg1, void* arg2)
{
    struct un_80304138_objalloc_t* d;
    if (arg0 == 1) {
        d = un_80302DF0();
        lbAudioAx_80024030(1);
        un_80304210(d, arg1, 0, -60, 0);
        un_80302DF8(un_80302DF0(), arg2);
    }
}

int fn_802FFE0C(int arg0)
{
    switch (arg0) {
    case 0:
        lbAudioAx_80024030(0);
        un_80304334(un_80302DF0());
        break;
    case 6:
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(4);
        gm_801A4B60();
        break;
    }
    return 0;
}

bool fn_802FFE6C(bool update_scene)
{
    bool res = update_scene;
    if (update_scene == false) {
        lbAudioAx_80024030(0);
        un_80304334(un_80302DF0());
        res = false;
    }

    return res;
}

bool un_802FFEA4(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x4);
        gm_801A4B60();
    }

    return false;
}

/// #un_802FFEE0

/// #un_802FFF2C

bool un_803001DC(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x1);
        gm_801A4B60();
    }

    return false;
}

int un_80300218(void)
{
    lbLang_SetSavedLanguage(un_803FA258.x0);
    return 0;
}

int un_80300248(int arg0)
{
    if (un_803FA258.x4 && arg0 == 1) {
        lbAudioAx_80024030(1);
        gmMainLib_8015FB68();
    }
    return 0;
}

int un_80300290(int arg0)
{
    if (arg0 == 1) {
        struct un_80304138_objalloc_t* x = un_80302DF0();
        lbAudioAx_80024030(1);
        un_80304210(x, &un_803FA658, 0, -60, 0);
        un_80302DF8(un_80302DF0(), fn_802FFE6C);
    }
    return 0;
}

bool un_803002FC(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x2);
        gm_801A4B60();
    }

    return false;
}

/// #un_80300338

/// #un_80300378

/// #un_803003C4

/// #un_80300410

// these will try to inline un_802FFD94 otherwise
#pragma push
#pragma dont_inline on
int un_80300480(int arg0)
{
    un_802FFD94(arg0, &un_803FB168, fn_802FFE0C);
    return 0;
}

int un_803004B4(int arg0)
{
    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);
    return 0;
}
#pragma pop

#pragma dont_inline on
int un_803004E8(int arg0)
{
    un_802FFD94(arg0, &un_803FAA44, fn_802FFE6C);
    return 0;
}

int un_8030051C(int arg0)
{
    un_802FFD94(arg0, &un_803FB60C, fn_802FFE6C);
    return 0;
}

int un_80300550(int arg0)
{
    un_802FFD94(arg0, &un_803FB728, fn_802FFE6C);
    return 0;
}

int un_80300584(int arg0)
{
    un_802FFD94(arg0, &un_803FB870, fn_802FFE6C);
    return 0;
}

int un_803005B8(int arg0)
{
    un_802FFD94(arg0, &un_803FB98C, fn_802FFE6C);
    return 0;
}

int un_803005EC(int arg0)
{
    un_802FFD94(arg0, &un_803FBA9C, fn_802FFE6C);
    return 0;
}

int un_80300620(int arg0)
{
    un_802FFD94(arg0, &un_803FBB98, fn_802FFE6C);
    return 0;
}

int un_80300654(int arg0)
{
    un_802FFD94(arg0, &un_803FBCAC, fn_802FFE6C);
    return 0;
}

int un_80300688(int arg0)
{
    un_802FFD94(arg0, &un_803FBDC0, fn_802FFE6C);
    return 0;
}

int un_803006BC(int arg0)
{
    un_802FFD94(arg0, &un_803FBFFC, fn_802FFE6C);
    return 0;
}

int un_803006F0(int arg0)
{
    un_802FFD94(arg0, &un_803FC0FC, fn_802FFE6C);
    return 0;
}

int un_80300724(int arg0)
{
    un_802FFD94(arg0, &un_803FC22C, fn_802FFE6C);
    return 0;
}
#pragma dont_inline reset

void un_80300758(int arg0)
{
    if (arg0 == 1) {
        un_802FFCD0(4, (u8*)&un_803FA258 + 0x10);
    }
}

void un_80300790(int arg0)
{
    if (arg0 == 1) {
        un_802FFCD0(4, (u8*)&un_803FA258 + 0x24);
    }
}

#pragma dont_inline on
int un_803007C8(int arg0)
{
    un_802FFD94(arg0, &un_803FC63C, fn_802FFE6C);
    return 0;
}

int un_803007FC(int arg0)
{
    un_802FFD94(arg0, &un_803FCA40, fn_802FFE6C);
    return 0;
}

int un_80300830(int arg0)
{
    un_802FFD94(arg0, &un_803FCC38, fn_802FFE6C);
    return 0;
}

int un_80300864(int arg0)
{
    un_802FFD94(arg0, &un_803FCE4C, fn_802FFE6C);
    return 0;
}

int un_80300898(int arg0)
{
    un_802FFD94(arg0, &un_803FD064, fn_802FFE6C);
    return 0;
}

int un_803008CC(int arg0)
{
    un_802FFD94(arg0, &un_803FDAF8, fn_802FFE6C);
    return 0;
}

int un_80300900(int arg0)
{
    un_802FFD94(arg0, &un_803FDB9C, fn_802FFE6C);
    return 0;
}

int un_80300934(int arg0)
{
    un_802FFD94(arg0, &un_803FD310, fn_802FFE6C);
    return 0;
}
#pragma dont_inline reset

bool un_80300968(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801A42F8(MJ_HANYU_CSS);
        gm_801A4B60();
    }

    return false;
}

bool un_803009A4(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801A42F8(MJ_HANYU_SSS);
        gm_801A4B60();
    }

    return false;
}

/// #un_803009E0

/// #un_80300A88

bool un_80300AB8(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x4);
        gm_801A4B60();
    }

    return false;
}

bool un_80300AF4(int arg0)
{
    if (arg0 == 1) {
        lbAudioAx_80024030(1);
        un_803FA258.x8 = 0x3F;
        un_803FA258.x10 = 0xE;
        un_803FA258.x28 = 3;
        un_803FA258.x2C = 3;
        un_803FA258.x30 = 3;
        gm_SetScenePendingMinor(4);
        gm_801A4B60();
    }
    return false;
}

bool un_80300B58(int arg0)
{
    if (arg0 == 1) {
        lbAudioAx_80024030(1);
        un_803FA258.x8 = 0x3B;
        un_803FA258.x10 = 0x2;
        un_803FA258.x28 = 3;
        un_803FA258.x2C = 3;
        un_803FA258.x30 = 3;
        gm_SetScenePendingMinor(4);
        gm_801A4B60();
    }
    return false;
}

bool un_80300BBC(bool update_scene)
{
    if (update_scene == true) {
        un_803124BC();
        un_80311680();
        gm_801A42F8(MJ_TOY_GALLERY);
        gm_801A4B60();
    }

    return false;
}

bool un_80300BF8(bool update_scene)
{
    if (update_scene == true) {
        un_803124BC();
        Trophy_SetUnlockState(0xE6, true);
        gm_801A42F8(MJ_MENU);
        gm_801A4B60();
    }

    return false;
}

bool un_80300C3C(bool update_scene)
{
    if (update_scene == true) {
        un_803124BC();
        Trophy_SetUnlockState(0xC9, true);
        gm_801A42F8(MJ_MENU);
        gm_801A4B60();
    }

    return false;
}

bool un_80300C80(int arg0)
{
    if (arg0 == 1) {
        int* ptr = gmMainLib_8015CCF0();
        *ptr = un_804D6DDC * 10;
        un_803124BC();
        gm_801A42F8(1);
        gm_801A4B60();
    }
    return false;
}

void fn_80300CC8(int arg0)
{
    int* r29;
    int* r30;
    int* r31;

    switch (arg0) {
    case 0:
        lbAudioAx_80024030(0);
        un_80304334(un_80302DF0());
        break;
    case 6:
        lbAudioAx_80024030(1);
        r29 = gmMainLib_8015CD2C();
        r30 = gmMainLib_8015CD38();
        r31 = gmMainLib_8015CD44();
        {
            int* ptr = gmMainLib_8015CD50();
            *r29 = un_804D6DE0;
            *r30 = un_804D6DE4;
            *r31 = un_804D6DE8;
            *ptr = un_804D6DEC;
        }
        gm_801A42F8(1);
        gm_801A4B60();
        break;
    }
}

#pragma dont_inline on
int un_80300D78(int arg0)
{
    if (arg0 == 1) {
        lbAudioAx_80024030(1);
        un_804D6DE0 = un_804D6DF0;
        un_804D6DE4 = un_804D6DF0;
        un_804D6DE8 = un_804D6DF0;
        un_804D6DEC = un_804D6DF0;
        un_802FFD94(arg0, &un_803FC70C, fn_80300CC8);
    }
    return 0;
}
#pragma dont_inline reset

void fn_80300DE0(int arg0)
{
    s32* ptr;

    ptr = gmMainLib_8015D06C(un_804D6DC8);
    switch (arg0) {
    case 0:
        lbAudioAx_80024030(0);
        un_80304334(un_80302DF0());
        break;
    case 6:
        lbAudioAx_80024030(1);
        *ptr = (u32) (un_804DDC48 * un_804D6DD0);
        gm_801A42F8(1);
        gm_801A4B60();
        break;
    }
}

#pragma dont_inline on
int un_80300E74(int arg0)
{
    if (arg0 == 1) {
        lbAudioAx_80024030(1);
        un_804D6DD8 = 2;
        un_802FFD94(arg0, &un_803FC8C8, fn_80300DE0);
    }
    return 0;
}
#pragma dont_inline reset

void fn_80300ED0(int arg0)
{
    switch (arg0) {
    case 0:
        lbAudioAx_80024030(0);
        un_80304334(un_80302DF0());
        break;
    case 6:
        lbAudioAx_80024030(1);
        gmMainLib_8015D4E8(un_804D6DC8, un_804D6DCC);
        gm_801A42F8(1);
        gm_801A4B60();
        break;
    }
}

/// #un_80300F3C

s32 un_80300F98(s32 arg0)
{
    s32* temp_r31;

    if (arg0 == 1) {
        temp_r31 = gmMainLib_8015CDB0();
        lbAudioAx_80024030(1);
        *temp_r31 = un_804D6DF4;
        gm_801A42F8(1);
        gm_801A4B60();
    }
    return 0;
}

bool un_80300FEC(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x4);
        gm_801A4B60();
    }

    return false;
}

/// #un_80301028

/// #un_80301074

/// #un_803010C0

/// #fn_8030110C

/// #fn_803011EC

/// #un_80301280

/// #un_803012D4

bool un_80301328(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801BF708(0x0);
        gm_801A42F8(MJ_OPENING_MV);
        gm_801A4B60();
    }

    return false;
}

bool un_8030136C(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801BF708(0x5);
        gm_801A42F8(MJ_OPENING_MV);
        gm_801A4B60();
    }

    return false;
}

bool un_803013B0(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801A42F8(MJ_DEBUG_CUTSCENE);
        gm_801A4B60();
    }

    return false;
}

/// #un_803013EC

/// #un_80301420

bool un_80301454(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801A42F8(MJ_BOOT);
        gm_801A4B60();
    }

    return false;
}

bool un_80301490(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0xD);
        gm_801A4B60();
    }

    return false;
}

bool un_803014CC(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x7);
        gm_801A4B60();
    }

    return false;
}

bool un_80301508(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x3);
        gm_801A4B60();
    }

    return false;
}

bool un_80301544(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x9);
        gm_801A4B60();
    }

    return false;
}

bool un_80301580(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0xC);
        gm_801A4B60();
    }

    return false;
}

bool un_803015BC(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801A42F8(MJ_PROGRESSIVE_SCAN);
        gm_801A4B60();
    }

    return false;
}

bool un_803015F8(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0xA);
        gm_801A4B60();
    }

    return false;
}

/// #un_80301634

/// #un_803016D8

/// #un_80301734

/// #un_8030178C

/// #un_80301800

/// #un_80301840

/// #un_803018BC

/// #un_8030191C

/// #un_80301964

/// #un_80301A64

/// #un_80301AD4

/// #un_80301B48

/// #un_80301BA8

void un_80301C64(un_80301C64_t* arg0)
{
    arg0->x0 = un_803FA258.x138;
    arg0->x4 = 0;
}

/// #un_80301C80

/// #un_80301CE0

bool un_80301D40(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_801A42F8(MJ_FIXED_CAMERA_VS);
        gm_801A4B60();
    }

    return false;
}

/// #un_80301D7C

bool un_80301DCC(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0x4);
        gm_801A4B60();
    }

    return false;
}

bool un_80301E08(bool update_scene)
{
    if (update_scene == true) {
        lbAudioAx_80024030(1);
        gm_SetScenePendingMinor(0xE);
        gm_801A4B60();
    }

    return false;
}
