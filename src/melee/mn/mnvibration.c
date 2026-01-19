#include "mnvibration.h"

#include "mnmain.h"
#include "mnname.h"

#include <sysdolphin/baselib/gobjplink.h>
#include <sysdolphin/baselib/jobj.h>
#include <sysdolphin/baselib/sislib.h>

extern void* mnVibration_804D6C28;
extern f32 mnVibration_803EECEC[2];

void* mnVibration_802474C4(s32 arg0) {
    void* node = *(void**)((u8*)*(void**)((u8*)mnVibration_804D6C28 + 0x2C) + 0x50);
    if (node == NULL) {
        node = NULL;
    } else {
        node = *(void**)((u8*)node + 0x10);
    }
    for (; arg0 > 0; arg0--) {
        if (node == NULL) {
            node = NULL;
        } else {
            node = *(void**)((u8*)node + 0x8);
        }
    }
    return node;
}
/// #fn_80247510

void fn_80248084(void* gobj) {
    if (mn_804A04F0.cur_menu != 0x13) {
        HSD_GObjPLink_80390228(gobj);
    }
}

/// #mnVibration_802480B4

/// #mnVibration_8024829C

/// #mnVibration_80248444

void mnVibration_80248644(HSD_GObj* gobj)
{
    s32 i;
    u8* data;
    u8* ptr1;
    u8* ptr2;

    for (i = 0, data = gobj->user_data, ptr1 = data, ptr2 = data + (i << 2);
         i < 8; i++, ptr1 += 4, ptr2 += 4)
    {
        if (*(HSD_Text**) (ptr1 + 0x70) != NULL) {
            HSD_SisLib_803A5CC4(*(HSD_Text**) (ptr2 + 0x70));
            *(void**) (ptr1 + 0x70) = NULL;
        }
    }

    {
        HSD_JObj* jobj = *(HSD_JObj**) (data + 0x50);
        HSD_JObj* child;
        if (jobj == NULL) {
            child = NULL;
        } else {
            child = jobj->child;
        }

        if (child != NULL) {
            if (jobj == NULL) {
                jobj = NULL;
            } else {
                jobj = jobj->child;
            }
            HSD_JObjRemoveAll(jobj);
        }
    }

    for (i = 0; i < 8; i++) {
        u8 scroll_offset = *(data + 0x0A);
        s32 name_count = GetNameCount();
        u8 name_idx;

        if (name_count < 8 && i >= name_count) {
            name_idx = 0xFF;
        } else {
            s32 sum = scroll_offset + i;
            if (name_count <= sum) {
                name_idx = 0xFF;
            } else {
                name_idx = (u8) sum;
            }
        }

        if ((s32) name_idx != 0xFF) {
            mnVibration_80248444(gobj, name_idx, (u8) i);
        }
    }
}
void fn_80248748(HSD_GObj* gobj) {
    f32* table = mnVibration_803EECEC;
    void* data = *(void**)((u8*)gobj + 0x2C);
    void* jobj = *(void**)((u8*)data + 0x10);
    f32 result = mn_8022ED6C(jobj, (AnimLoopSettings*) table);
    if (result >= table[1]) {
        HSD_GObjPLink_80390228(gobj);
    }
}
/// #fn_802487A8

/// #fn_80248A78

/// #mnVibration_80248ED4

/// #mnVibration_80249174
