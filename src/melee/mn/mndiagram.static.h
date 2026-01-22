#ifndef __GALE01_23EA2C
#define __GALE01_23EA2C

#include "mndiagram.h" // IWYU pragma: export

#include <placeholder.h>

#include <m2c_macros.h>

/* Forward declarations */
bool mn_IsFighterUnlocked(s32);
s32 lbLang_IsSavedLanguageUS(void);
void HSD_Free(void*);
char* GetNameText(s32);
void* GetPersistentNameData(s32);
void* GetPersistentFighterData(s32);
s32 mn_8022EB78(s32);
s32 mn_8022EB24(s32, s32);
f32 mn_8022ED6C(void*, f32*);
void HSD_GObjPLink_80390228(HSD_GObj*);
HSD_JObj* HSD_JObjLoadJoint(void*);
void HSD_GObjObject_80390A70(HSD_GObj*, u8, HSD_JObj*);
void GObj_SetupGXLink(HSD_GObj*, void*, s32, s32);
HSD_GObj* GObj_Create(u16, u8, u8);
void* HSD_GObjProc_8038FD54(HSD_GObj*, void*, s32);
void HSD_GObj_JObjCallback(HSD_GObj*, s32);

/* Data externs */
extern char mnDiagram_804D4FA4;
extern f32 mnDiagram_803EE774[];
extern void* mnDiagram_804A0814;
extern u8 HSD_GObj_804D7849;

struct mnDiagram_804A0750_t {
    char pad_0[0x1C];
};
STATIC_ASSERT(sizeof(struct mnDiagram_804A0750_t) == 0x1C);

struct mnDiagram_804A076C_t {
    char pad_0[0x78];
};
STATIC_ASSERT(sizeof(struct mnDiagram_804A076C_t) == 0x78);

/* 4A0750 */ struct mnDiagram_804A0750_t mnDiagram_804A0750;
/* 4A076C */ struct mnDiagram_804A076C_t mnDiagram_804A076C;

/// User data structure for fn_80240B18 (cleanup function)
typedef struct mnDiagram_CleanupData {
    /* 0x00 */ char x0[0x38];
    /* 0x38 */ HSD_Text*
        text[5]; ///< text objects at 0x38, 0x3C, 0x40, 0x44, 0x48
} mnDiagram_CleanupData;

#endif
