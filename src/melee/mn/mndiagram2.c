#include "mndiagram2.h"

#include <baselib/gobj.h>
#include <baselib/gobjproc.h>
#include <baselib/jobj.h>
#include <baselib/sislib.h>

/* Forward declarations for mnDiagram functions */
u8 mnDiagram_8023EA2C(s32);
s32 mnDiagram_8023EA40_s(s32);
s32 mnDiagram_8023EA2C_s(s32);
#define mnDiagram_8023EA40(x) mnDiagram_8023EA40_s(x)
s32 GetNameCount(void);
extern void mnDiagram_8023F540(void);
s32 mnDiagram_8023F578(s32, s32, void*);
u8 mnDiagram_8023F8CC(u8);

/* Forward declarations for persistent data functions */
s32 GetNameTotalKOs(u8);
s32 GetFighterTotalKOs(u8);
s32 GetNameTotalFalls(u8);
s32 GetFighterTotalFalls(u8);
void* GetPersistentNameData(u8);
void* GetPersistentFighterData(u8);
s32 GetHitPercentage(void);
s32 GetPlayPercentage(void);
s32 GetAveragePlayerCount(void);

/* Forward declaration for mn function */
bool mn_8022E950(s32);

/* mnDiagram2 local data and callbacks */
extern u8 mn_804A04F0[];
void fn_80243D40(HSD_GObj*);

/* Union for 64-bit sorting operations */
typedef union {
    struct {
        u8 name;
        char pad1[7];
        s32 x8;
        s32 xC;
    };
    struct {
        f64 d0;
        f64 d8;
    };
    struct {
        char pad2[8];
        u64 value;
    };
} mnDiagram2_SortEntry;

/* Local struct for mnDiagram2_80245AE4 */
typedef struct {
    /* 0x00 */ char x0[0x20];
    /* 0x20 */ void* x20;
    /* 0x24 */ char x24[0x34];
    /* 0x58 */ HSD_Text* x58;
    /* 0x5C */ HSD_Text* x5C;
    /* 0x60 */ HSD_Text* x60[5];
} mnDiagram2_AE4_UserData;

bool mnDiagram2_80243A3C(u8 arg0)
{
    switch (arg0) {
    case 0xB:
        return TRUE;
    default:
        return FALSE;
    }
}

bool mnDiagram2_80243A5C(u8 arg0)
{
    switch (arg0) {
    case 14:
    case 15:
    case 16:
    case 17:
        return TRUE;
    default:
        return FALSE;
    }
}

bool mnDiagram2_80243A84(u8 arg0)
{
    switch (arg0) {
    case 3:
    case 12:
    case 13:
        return TRUE;
    default:
        return FALSE;
    }
}

bool mnDiagram2_80243AB4(u8 arg0)
{
    switch (arg0) {
    case 21:
    case 22:
    case 23:
        return TRUE;
    default:
        return FALSE;
    }
}

/// #mnDiagram2_80243ADC

/// #mnDiagram2_80243BBC

s32 mnDiagram2_80244330(s32 arg0, HSD_GObj* type, u8 idx)
{
    u8 typeVal;
    u8 idxVal;

    typeVal = (u8) (u32) type;
    idxVal = idx;

    switch (typeVal) {
    case 0x00:
        if ((u8) arg0) {
            return GetNameTotalKOs(idxVal);
        }
        return GetFighterTotalKOs(idxVal);

    case 0x01:
        if ((u8) arg0) {
            return GetNameTotalFalls(idxVal);
        }
        return GetFighterTotalFalls(idxVal);

    case 0x02:
        if ((u8) arg0) {
            return (u16) * (u16*) ((u8*) GetPersistentNameData(idxVal) + 0xF0);
        }
        return (u16) * (u16*) ((u8*) GetPersistentFighterData(idxVal) + 0x34);

    case 0x03:
        return GetHitPercentage();

    case 0x04:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0xFC);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x40);

    case 0x05:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x100);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x44);

    case 0x06:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x104);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x48);

    case 0x07:
        if ((u8) arg0) {
            return (u16) *
                   (u16*) ((u8*) GetPersistentNameData(idxVal) + 0x108);
        }
        return (u16) * (u16*) ((u8*) GetPersistentFighterData(idxVal) + 0x4C);

    case 0x08:
        if ((u8) arg0) {
            return (u16) *
                   (u16*) ((u8*) GetPersistentNameData(idxVal) + 0x10A);
        }
        return (u16) * (u16*) ((u8*) GetPersistentFighterData(idxVal) + 0x4E);

    case 0x09:
        if ((u8) arg0) {
            return (u16) *
                   (u16*) ((u8*) GetPersistentNameData(idxVal) + 0x10C);
        }
        return (u16) * (u16*) ((u8*) GetPersistentFighterData(idxVal) + 0x50);

    case 0x0A:
        if ((u8) arg0) {
            return (u16) *
                   (u16*) ((u8*) GetPersistentNameData(idxVal) + 0x10E);
        }
        return (u16) * (u16*) ((u8*) GetPersistentFighterData(idxVal) + 0x52);

    case 0x0B:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x110);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x54);

    case 0x0C:
        return GetPlayPercentage();

    case 0x0D:
        return GetAveragePlayerCount();

    case 0x0E:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x118);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x5C);

    case 0x0F:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x11C);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x60);

    case 0x10:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x120);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x64);

    case 0x11:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x124);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x68);

    case 0x12:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x128);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x6C);

    case 0x13:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x12C);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x70);

    case 0x14:
        if ((u8) arg0) {
            return *(s32*) ((u8*) GetPersistentNameData(idxVal) + 0x130);
        }
        return *(s32*) ((u8*) GetPersistentFighterData(idxVal) + 0x74);

    case 0x15:
        return mnDiagram_8023F578(0, idxVal, (void*) mnDiagram_8023F540);

    case 0x16:
        return mnDiagram_8023F578(1, idxVal, (void*) mnDiagram_8023F540);

    case 0x17:
        return mnDiagram_8023F8CC(idxVal);

    default:
        break;
    }
    return 0;
}

/// #mnDiagram2_8024469C

void mnDiagram2_80244C74(HSD_GObj* gobj, u8 start, u8 flag, u8 arg3)
{
    s32 limit;
    s32 idx;
    s32 i;
    u8 var_r28;

    if (flag != 0) {
        var_r28 = mnDiagram_8023EA40(arg3);
    } else {
        var_r28 = mnDiagram_8023EA2C(arg3);
    }

    if (flag != 0) {
        limit = 0x18;
    } else {
        limit = 0x15;
    }

    i = 0;
    idx = (u8) start;
    do {
        s32 val;
        if (idx >= limit) {
            val = idx - limit;
        } else {
            val = idx;
        }
        mnDiagram2_8024469C(gobj, flag, val, i, var_r28);
        i++;
        idx++;
    } while (i < 10);
}
/// #mnDiagram2_80244D80

/// #mnDiagram2_80245068

/// #mnDiagram2_80245178

void mnDiagram2_802453B0(void)
{
    u8* data = mn_804A04F0;
    HSD_GObj* gobj;
    u32 val;
    u8 flags;

    data[0x10] = 1;
    *(s16*) (data + 0x2) = 0;
    mnDiagram2_80245178();
    gobj = (HSD_GObj*) HSD_GObjProc_8038FD54(GObj_Create(0, 1, 0x80),
                                             fn_80243D40, 0);
    val = HSD_GObj_804D783C;
    flags = ((u8*) gobj)[0xD];
    flags = (flags & ~0x30) | ((val & 3) << 4);
    ((u8*) gobj)[0xD] = flags;
}
u8 mnDiagram2_8024541C(HSD_GObj* gobj, u8 idx)
{
    mnDiagram2_SortEntry entries[25];
    f64 temp0;
    f64 temp8;
    mnDiagram2_SortEntry* base;
    mnDiagram2_SortEntry* ptr;
    mnDiagram2_SortEntry* curr;
    s32 i;
    s32 j;
    s32 k;
    s32 maxIdx;
    s32 zero;
    s32 neg1;
    u8 name;

    base = entries;
    ptr = base;
    i = 0;
    zero = 0;
    neg1 = -1;

    do {
        name = mnDiagram_8023EA2C(i);
        ptr->name = name;
        if (mn_8022E950(name) != 0) {
            ptr->xC = mnDiagram2_80244330(0, gobj, name);
            ptr->x8 = zero;
        } else {
            ptr->xC = neg1;
            ptr->x8 = neg1;
        }
        i++;
        ptr++;
    } while (i < 25);

    // Selection sort with -1 handling
    i = 0;
    do {
        k = i + 1;
        maxIdx = i;
        curr = &entries[k];
        while (k < 25) {
            // Skip entries with -1 value
            if (curr->value != (u64) -1) {
                // Update if curr > entries[maxIdx] OR entries[maxIdx] == -1
                u64 maxVal = entries[maxIdx].value;
                if (curr->value > maxVal || maxVal == (u64) -1) {
                    maxIdx = k;
                }
            }
            curr++;
            k++;
        }

        if (maxIdx != i) {
            ptr = &entries[maxIdx];
            j = maxIdx - i;
            temp0 = ptr->d0;
            temp8 = ptr->d8;

            while (j > 0) {
                ptr->d0 = (ptr - 1)->d0;
                ptr->d8 = (ptr - 1)->d8;
                ptr--;
                j--;
            }
            base->d0 = temp0;
            base->d8 = temp8;
        }
        base++;
        i++;
    } while (i < 25);

    // Return
    ptr = &entries[idx];
    if (ptr->value == (u64) -1) {
        return 25;
    }
    return entries[idx].name;
}

/// #mnDiagram2_80245684

u8 mnDiagram2_8024589C(HSD_GObj* gobj, u8 type, u8 idx)
{
    mnDiagram2_SortEntry entries[25];
    f64 temp0;
    f64 temp8;
    mnDiagram2_SortEntry* base;
    mnDiagram2_SortEntry* curr;
    void* funcTable;
    s32 count;
    s32 res;
    mnDiagram2_SortEntry* ptr;
    mnDiagram2_SortEntry* arr;
    s32 i;
    s32 j;
    s32 k;
    s32 zero;

    base = entries;
    ptr = base;
    i = 0;
    zero = 0;

    do {
        ptr->name = mnDiagram_8023EA2C(i);
        i++;
        ptr->xC = zero;
        ptr->x8 = zero;
        ptr++;
    } while (i < 25);

    count = GetNameCount();
    funcTable = (void*) mnDiagram_8023F540;
    type = type;
    arr = entries;

    i = 0;
    while (i < count) {
        switch ((s32) type) {
        case 0x15:
            res = mnDiagram_8023F578(0, i, funcTable);
            break;
        case 0x16:
            res = mnDiagram_8023F578(1, i, funcTable);
            break;
        case 0x17:
            res = mnDiagram_8023F8CC((u8) i);
            break;
        default:
            goto next;
        }

        if (res != 25) {
            ptr = base;
            k = 0;
            for (j = 25; j > 0; j--) {
                if (res == ptr->name) {
                    arr[k].value += 1;
                    break;
                }
                ptr++;
                k++;
            }
        }
    next:
        i++;
    }

    // Bubble sort
    j = 0;
    do {
        k = j + 1;
        curr = &entries[k];
        while (k < 25) {
            u64 a = base->value;
            u64 b = curr->value;
            if (a < b) {
                temp0 = base->d0;
                temp8 = base->d8;
                base->d0 = curr->d0;
                base->d8 = curr->d8;
                curr->d0 = temp0;
                curr->d8 = temp8;
            }
            curr++;
            k++;
        }
        base++;
        j++;
    } while (j < 25);

    // Return
    curr = &entries[idx];
    if (curr->value == 0) {
        curr->name = 25;
    }
    ((mnDiagram2_SortEntry*) gobj)->d0 = curr->d0;
    ((mnDiagram2_SortEntry*) gobj)->d8 = curr->d8;

    return 0;
}

void mnDiagram2_80245AE4(HSD_GObj* gobj)
{
    mnDiagram2_AE4_UserData* data;
    mnDiagram2_AE4_UserData* base;
    mnDiagram2_AE4_UserData* ptr;
    s32 i;
    void* tmp;
    HSD_JObj* jobj;

    data = gobj->user_data;

    if (data->x58 != NULL) {
        HSD_SisLib_803A5CC4(data->x58);
        data->x58 = NULL;
    }

    i = 0;
    base = data;
    ptr = (mnDiagram2_AE4_UserData*) ((u8*) data + (i << 2));

    do {
        if (base->x60[0] != NULL) {
            HSD_SisLib_803A5CC4(ptr->x60[0]);
            base->x60[0] = NULL;
        }
        i++;
        base = (mnDiagram2_AE4_UserData*) ((u8*) base + 4);
        ptr = (mnDiagram2_AE4_UserData*) ((u8*) ptr + 4);
    } while (i < 5);

    if (data->x5C != NULL) {
        HSD_SisLib_803A5CC4(data->x5C);
        data->x5C = NULL;
    }

    tmp = data->x20;
    if (tmp == NULL) {
        tmp = NULL;
    } else {
        tmp = *(void**) ((u8*) tmp + 0x10);
    }
    jobj = tmp;
    if (jobj != NULL) {
        HSD_JObjRemoveAll(jobj);
    }
}