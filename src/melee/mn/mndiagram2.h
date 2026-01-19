#ifndef MNDIAGRAM2_H
#define MNDIAGRAM2_H

#include <placeholder.h>
#include <baselib/gobj.h>

typedef struct mnDiagram2_UserData {
    /* 0x00 */ char x0[0x18];
    /* 0x18 */ HSD_JObj* x18;
    /* 0x1C */ s32 x1C;
    /* 0x20 */ char x20[0x4];
    /* 0x24 */ s32 x24;
    /* 0x28 */ void* x28;        // pointer to something with x10 (JObj*)
    /* 0x2C */ char x2C[0x20];   // padding to 0x4C
    /* 0x4C */ HSD_Text* x4C[10];    // array of 10 pointers
    /* 0x74 */ HSD_Text* x74[10];    // array of 10 pointers
    /* 0x9C */ HSD_Text* x9C[10];    // array of 10 pointers
    /* 0xC4 */ HSD_Text* xC4;
} mnDiagram2_UserData;

/* 243A3C */ bool mnDiagram2_80243A3C(u8 arg0);
/* 243A5C */ bool mnDiagram2_80243A5C(u8 arg0);
/* 243A84 */ bool mnDiagram2_80243A84(u8 arg0);
/* 243AB4 */ bool mnDiagram2_80243AB4(u8 arg0);
/* 243ADC */ void mnDiagram2_80243ADC(HSD_GObj* gobj);
/* 243BBC */ void mnDiagram2_80243BBC(HSD_GObj*, u8, u8);
/* 244330 */ s32 mnDiagram2_80244330(s32 arg0, HSD_GObj* type, u8 idx);
/* 24469C */ void mnDiagram2_8024469C(HSD_GObj*, u8, u8, u8, u8);
/* 244C74 */ void mnDiagram2_80244C74(HSD_GObj* gobj, u8 start, u8 flag, u8 arg3);
/* 244D80 */ void mnDiagram2_80244D80(HSD_GObj*);
/* 245068 */ void mnDiagram2_80245068(void*);
/* 245178 */ void mnDiagram2_80245178(void);
/* 2453B0 */ void mnDiagram2_802453B0(void);
/* 24541C */ u8 mnDiagram2_8024541C(HSD_GObj* gobj, u8 idx);
/* 245684 */ u8 mnDiagram2_80245684(HSD_GObj*, u8);
/* 24589C */ u8 mnDiagram2_8024589C(HSD_GObj* gobj, u8 type, u8 idx);
/* 245AE4 */ void mnDiagram2_80245AE4(HSD_GObj* gobj);

#endif
