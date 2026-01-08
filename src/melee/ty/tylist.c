#include "tylist.h"

#include "if/textlib.h"
#include "lb/lb_00B0.h"
#include "ty/toy.h"

#include <m2c_macros.h>

#include <baselib/cobj.h>
#include <baselib/displayfunc.h>
#include <baselib/fog.h>
#include <baselib/gobj.h>
#include <baselib/gobjgxlink.h>
#include <baselib/sislib.h>
#include <baselib/video.h>

typedef struct {
    u8 pad[0x28];
    HSD_CObj* cobj;
} TyListData;

typedef struct TyListArg {
    /* 0x00 */ void* x0;
    /* 0x04 */ void* x4;
    /* 0x08 */ void* x8;
    /* 0x0C */ void* xC;
    /* 0x10 */ HSD_JObj* x10;
    /* 0x14 */ void* x14;
    /* 0x18 */ u8 pad_18[0x26 - 0x18];
    /* 0x26 */ s16 idx;
    /* 0x28 */ u8 pad_28[0x30 - 0x28];
    /* 0x30 */ float x30;
} TyListArg;

extern u8 un_804A2AA8[];
extern void* un_804D6ED0;
extern void* un_804D6EC4;
extern void* un_804D6EC0;
extern void* un_804D6EBC;
extern void* un_804D6EB8;
extern void* un_804D6EB4;
extern void* un_804D6EB0;
extern void* un_804D6EAC;
extern void* un_804D6ECC;
extern void* un_804D6EA8;
extern void* un_804D6EA4;
extern void* un_804D6EC8;

/// #un_803124BC

/// #un_8031263C

void un_803127D4(void)
{
    un_804D6ED0 = NULL;
    un_804D6EC4 = NULL;
    un_804D6EC0 = NULL;
    un_804D6EBC = NULL;
    un_804D6EB8 = NULL;
    un_804D6EB4 = NULL;
    un_804D6EB0 = NULL;
    un_804D6EAC = NULL;
    un_804D6ECC = NULL;
    un_804D6EA8 = NULL;
    un_804D6EA4 = NULL;
    un_804D6EC8 = NULL;
    memzero(un_804A2AA8, 0x14);
}

void un_80312834(char* buf, u32 num)
{
    u8* lookup = M2C_FIELD(HSD_SisLib_804D1124[0], u8**, 0x4E8);
    u32 idx;
    u32 original = num;

    if (num >= 100) {
        idx = (num / 100) * 2;
        *buf++ = lookup[idx];
        *buf++ = lookup[idx + 1];
        num = num % 100;
    }

    if (num >= 10) {
        idx = (num / 10) * 2;
        *buf++ = lookup[idx];
        *buf++ = lookup[idx + 1];
        num = num % 10;
    } else if (original >= 100) {
        *buf++ = lookup[0];
        *buf++ = lookup[1];
    }

    idx = num * 2;
    *buf = lookup[idx];
    *(buf + 1) = lookup[idx + 1];
    *(buf + 2) = 0;
}

/// #un_80312904

/// #un_80312BAC

/// #un_80312E88

/// #un_8031305C

/// #un_80313358

void un_80313464(TyListArg* arg)
{
    char* data = un_804A2AC0;
    s32 val;
    PAD_STACK(24);

    val = un_804D6EDC[arg->idx];

    un_803083D8(arg->x14, val);

    if (arg->x10 != NULL) {
        HSD_JObjUnref(arg->x10);
        arg->x10 = NULL;
    }

    if (un_80304924(val) != 0) {
        arg->x10 = un_80313508(*(void**) (data + 0x27C), un_803FE8D0,
                               un_804DDE60, arg->x30, un_804DDE48);
    }
}
/// #un_80313508

/// #un_80313774

/// #fn_80313BD8

/// #fn_8031438C

void fn_80314504(HSD_GObj* gobj)
{
    TyListData* data = (TyListData*) gobj;

    if ((s32) HSD_CObjSetCurrent(data->cobj) != 0) {
        HSD_SetEraseColor(0, 0, 0, 0xFF);
        HSD_CObjEraseScreen(data->cobj, 1, 0, 0);
        HSD_GObj_80390ED0(gobj, 7);
        HSD_FogSet(0);
        HSD_CObjEndCurrent();
    }
}

/// #un_8031457C

/// #un_803147C4

/// #un_803148E4
