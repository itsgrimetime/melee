#include "vi/vi1202.h"

#include <baselib/gobj.h>
#include <baselib/jobj.h>

#include "vi.h"

void un_8032110C(HSD_GObj* gobj)
{
    HSD_JObjAnimAll(GET_JOBJ(gobj));
}

void un_80321130(HSD_GObj* gobj)
{
    HSD_JObjAnimAll(GET_JOBJ(gobj));
}

void un_80321154(HSD_GObj* gobj)
{
    HSD_JObjAnimAll(GET_JOBJ(gobj));
}

void un_803218E0_OnFrame(void)
{
    vi_8031CAAC();
}
<<<<<<< HEAD
=======

extern char un_804A2F08[];
extern vi1202_UnkStruct* un_804D7050;

void un_80321900(void)
{
    HSD_GObj* gobj = GObj_Create(0x16, 0x17, 0);
    HSD_GObjProc_8038FD54(gobj, fn_803219AC, 0x13);
    un_804D7050 = (vi1202_UnkStruct*)un_804A2F08;
    un_80321950(un_804D7050);
}

void un_80321950(void* s)
{
    ((vi1202_UnkStruct*)s)->x0 = 0;
    ((vi1202_UnkStruct*)s)->x4 = 0x10000;
    ((vi1202_UnkStruct*)s)->x8 = 1.0F;
    ((vi1202_UnkStruct*)s)->xC = 0;
    ((vi1202_UnkStruct*)s)->x10 = *(void**)((char*)Fighter_804D6500 + 0x20);
    ((vi1202_UnkStruct*)s)->x14 = 0x83D60;
    ((vi1202_UnkStruct*)s)->x18 = *(s32*)((char*)Fighter_804D6500 + 0x28);
    ((vi1202_UnkStruct*)s)->x1C = 0;
    ((vi1202_UnkStruct*)s)->x20 = 0;
    ((vi1202_UnkStruct*)s)->x24 = 0;
    ((vi1202_UnkStruct*)s)->x2C = -1;
    ((vi1202_UnkStruct*)s)->x28 = -1;
}

void fn_803219AC(HSD_GObj* gobj)
{
    vi1202_UnkStruct* data = un_804D7050;
    if (data->x4 < 0x10000) {
        data->x4 = data->x4 + 1;
    }
    un_80321A00(gobj);
    un_80321AF4(gobj);
}

void un_80321C28(void)
{
    vi1202_UnkStruct* data = un_804D7050;
    if (lbAudioAx_80023710(data->x2C) != 0) {
        lbAudioAx_800236B8(data->x2C);
    }
    data->x2C = -1;
}

void un_80321C70(void)
{
    vi1202_UnkStruct* data = un_804D7050;
    void* fighter = Fighter_804D6500;
    s32 x18 = data->x18;
    if (x18 >= *(s32*)((char*)fighter + 0x28)) {
        return;
    }
    if (x18 >= *(s32*)((char*)fighter + 0x24)) {
        data->x1C = 1;
    }
}

void un_80321CA4(s32 arg)
{
    vi1202_UnkStruct* data = un_804D7050;
    un_80321CE8();
    data->x28 = lbAudioAx_8002411C(arg);
}

void un_80321CE8(void)
{
    vi1202_UnkStruct* data = un_804D7050;
    if (lbAudioAx_80023710(data->x28) != 0) {
        lbAudioAx_800236B8(data->x28);
    }
    data->x28 = -1;
}
>>>>>>> 26d502ade (Match un_80321CE8 (vi1202.c))
