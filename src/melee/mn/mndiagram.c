#include "mndiagram.static.h"

#include "gm/types.h"

/// @brief Gets the fighter ID at the given sorted index.
/// @param idx Index into the sorted fighter list
/// @return Fighter ID
u8 mnDiagram_GetFighterByIndex(int idx)
{
    return mnDiagram_804A0750.pad_0[idx];
}

/// @brief Gets the name ID at the given sorted index.
/// @param idx Index into the sorted name list
/// @return Name ID
u8 mnDiagram_GetNameByIndex(int idx)
{
    return mnDiagram_804A076C.pad_0[idx];
}

int mnDiagram_8023EA54(u32 arg0)
{
    if (lbLang_IsSavedLanguageUS() != 0) {
        if (arg0 >= 0x274A6) {
            return 1;
        }
        return 0;
    } else {
        if (arg0 >= 0x186A0) {
            return 1;
        }
        return 0;
    }
}

/// #mnDiagram_8023EAC4

/// #GetHitPercentage

/// #GetPlayPercentage

/// #GetAveragePlayerCount

int GetNameTotalKOs(u8 field_index)
{
    int total = 0;
    int i;
    for (i = 0; i < 0x78; i++) {
        if (GetNameText(i) != 0) {
            struct gmm_x2FF8_inner* data = GetPersistentNameData(field_index);
            total += M2C_FIELD(data, u16*, (u8) i * 2);
        }
    }
    return total;
}

int GetNameTotalFalls(u8 field_index)
{
    int i;
    int total = 0;
    int offset = (u8) (field_index & 0xFF) * 2;
    PAD_STACK(16);
    for (i = 0; i < 0x78; i++) {
        if (GetNameText(i) != 0) {
            void* data = GetPersistentNameData(i);
            total += M2C_FIELD(data, u16*, offset);
        }
    }
    if (total > 999999) {
        total = 999999;
    }
    return total;
}

int GetFighterTotalKOs(u8 field_index)
{
    u8 idx = (u8) (field_index & 0xFF);
    int total = 0;
    int i = 0;
    void* data;
    for (; i < 0x19; i++) {
        if (mn_IsFighterUnlocked(i) != 0) {
            data = GetPersistentFighterData(idx);
            total += M2C_FIELD(data, u16*, (u8) i * 2);
        }
    }
    return total;
}

int GetFighterTotalFalls(u8 field_index)
{
    int i;
    int total = 0;
    int offset = field_index * 2;
    void* data;
    PAD_STACK(16);
    for (i = 0; i < 0x19; i++) {
        if (mn_IsFighterUnlocked(i) != 0) {
            data = GetPersistentFighterData(i);
            total += M2C_FIELD(data, u16*, offset);
        }
    }
    return total;
}

/// #mnDiagram_8023F14C

/// #mnDiagram_8023F238

void mnDiagram_8023F334(char* buf, u32 val)
{
    int digit_count;
    int last;
    char* ptr;
    int i;

    digit_count = mn_8022EB78(val);
    ptr = buf;
    last = digit_count - 1;
    i = 0;
    for (; i < digit_count; i++) {
        *ptr = mn_8022EB24(val, last - i) + 0x30;
        ptr++;
    }
    buf[digit_count] = mnDiagram_804D4FA4;
}

u8 mnDiagram_8023F3A8(u8 arg0)
{
    int i, original;

    original = i = (int) arg0;

    do {
        if (--i < 0) {
            return original;
        }
    } while ((u32) GetNameText(i) == 0);

    return i;
}

/// #mnDiagram_8023F400

u8 mnDiagram_8023F45C(u8 arg0)
{
    int i;
    u8 original;
    u8* ptr;

    ptr = (u8*) &mnDiagram_804A0750 + arg0;
    i = arg0;
    original = arg0;
    do {
        i--;
        ptr--;
        if (i < 0) {
            return original;
        }
    } while (mn_IsFighterUnlocked(*ptr) == 0);
    return (u8) i;
}

u8 mnDiagram_GetNextFighterIndex(u8 idx)
{
    int i;
    u8 original;
    u8* ptr;

    ptr = (u8*) &mnDiagram_804A0750 + idx;
    i = idx;
    original = idx;
    do {
        i++;
        ptr++;
        if (i >= 0x19) {
            return original;
        }
    } while (mn_IsFighterUnlocked(*ptr) == 0);
    return (u8) i;
}

/// #mnDiagram_8023F540

/// #mnDiagram_8023F578

/// #mnDiagram_8023F8CC

/// #mnDiagram_8023FA6C

/// #mnDiagram_8023FC28

int mnDiagram_8023FDD8(void)
{
    int i;
    int count;
    i = 0;
    count = 0;
    for (; i < 0x19; i++) {
        if (mn_IsFighterUnlocked(i) != 0) {
            count++;
        }
    }
    return count;
}

/// #fn_8023FE30

/// #fn_8023FED4

void fn_80240B18(void* arg0)
{
    mnDiagram_CleanupData* data = arg0;

    if (data->text[0] != NULL) {
        HSD_SisLib_803A5CC4(data->text[0]);
    }
    if (data->text[1] != NULL) {
        HSD_SisLib_803A5CC4(data->text[1]);
    }
    if (data->text[2] != NULL) {
        HSD_SisLib_803A5CC4(data->text[2]);
    }
    if (data->text[3] != NULL) {
        HSD_SisLib_803A5CC4(data->text[3]);
    }
    if (data->text[4] != NULL) {
        HSD_SisLib_803A5CC4(data->text[4]);
    }
    HSD_Free(arg0);
}

/// #fn_80240B98

/// #mnDiagram_80240D94

/// #mnDiagram_80241310

/// #mnDiagram_80241668

/// #mnDiagram_80241730

/// #mnDiagram_802417D0

void fn_80241AE8(HSD_GObj* gobj)
{
    void* data;
    void* jobj;
    f32* table;

    data = M2C_FIELD(gobj, void**, 0x2C);
    mnDiagram_802417D0(gobj);
    jobj = M2C_FIELD(data, void**, 0x0C);
    table = mnDiagram_803EE774;
    if (mn_8022ED6C(jobj, table) >= table[1]) {
        HSD_GObjPLink_80390228(gobj);
    }
}

/// #mnDiagram_80241B4C

/// #fn_80241BF8

/// #mnDiagram_80241E78

/// #mnDiagram_8024227C

/// #mnDiagram_802427B4

/// #mnDiagram_80242B38

/// #mnDiagram_80242C0C

/// #fn_80243038

void mnDiagram_802433AC(void)
{
    void** joint_data;
    HSD_GObj* gobj;
    HSD_JObj* jobj;
    PAD_STACK(32);

    joint_data = &mnDiagram_804A0814;
    gobj = GObj_Create(6, 7, 0x80);
    jobj = HSD_JObjLoadJoint(*joint_data);
    HSD_GObjObject_80390A70(gobj, HSD_GObj_804D7849, jobj);
    GObj_SetupGXLink(gobj, HSD_GObj_JObjCallback, 4, 0x80);
    HSD_GObjProc_8038FD54(gobj, fn_80243038, 0);
}

/// #mnDiagram_80243434

/// #mnDiagram_802437E8
