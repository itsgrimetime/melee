#ifndef GALE01_23EA2C
#define GALE01_23EA2C

#include <placeholder.h>

#include <baselib/forward.h>

/* 23EA2C */ u8 mnDiagram_GetFighterByIndex(int idx);
/* 23EA40 */ u8 mnDiagram_GetNameByIndex(int idx);
/* 23EA54 */ int mnDiagram_8023EA54(u32 arg0);
/* 23EAC4 */ u32 mnDiagram_8023EAC4(void);
/* 23EB84 */ int GetHitPercentage(void);
/* 23ECC4 */ int GetPlayPercentage(void);
/* 23EE38 */ int GetAveragePlayerCount(void);
/* 23EF70 */ int GetNameTotalKOs(u8 field_index);
/* 23EFE4 */ int GetNameTotalFalls(u8 field_index);
/* 23F068 */ int GetFighterTotalKOs(u8 field_index);
/* 23F0DC */ int GetFighterTotalFalls(u8 field_index);
/* 23F14C */ void mnDiagram_8023F14C(char* buf, u32 val, int mode);
/* 23F238 */ void mnDiagram_8023F238(char* buf, u32 val);
/* 23F334 */ void mnDiagram_8023F334(char* buf, u32 val);
/* 23F3A8 */ u8 mnDiagram_8023F3A8(u8 arg0);
/* 23F400 */ u8 mnDiagram_GetNextNameIndex(u8 idx);
/* 23F45C */ u8 mnDiagram_8023F45C(u8 arg0);
/* 23F4CC */ u8 mnDiagram_GetNextFighterIndex(u8 idx);
/* 23F540 */ void mnDiagram_8023F540(void);
/* 23F578 */ int mnDiagram_GetRankedFighterForName(int rank, int name_idx,
                                                   void* func);
/* 23F8CC */ u8 mnDiagram_GetLeastPlayedFighter(u8 name_idx);
/* 23FA6C */ UNK_RET mnDiagram_8023FA6C(UNK_PARAMS);
/* 23FC28 */ UNK_RET mnDiagram_8023FC28(UNK_PARAMS);
/* 23FDD8 */ int mnDiagram_8023FDD8(void);
/* 23FE30 */ UNK_RET fn_8023FE30(UNK_PARAMS);
/* 23FED4 */ UNK_RET fn_8023FED4(UNK_PARAMS);
/* 240B18 */ void fn_80240B18(void* arg0);
/* 240B98 */ UNK_RET fn_80240B98(UNK_PARAMS);
/* 240D94 */ UNK_RET mnDiagram_80240D94(UNK_PARAMS);
/* 241310 */ UNK_RET mnDiagram_80241310(UNK_PARAMS);
/* 241668 */ UNK_RET mnDiagram_80241668(UNK_PARAMS);
/* 241730 */ UNK_RET mnDiagram_80241730(UNK_PARAMS);
/* 2417D0 */ void mnDiagram_802417D0(HSD_GObj* gobj);
/* 241AE8 */ void fn_80241AE8(HSD_GObj* gobj);
/* 241B4C */ UNK_RET mnDiagram_80241B4C(UNK_PARAMS);
/* 241BF8 */ UNK_RET fn_80241BF8(UNK_PARAMS);
/* 241E78 */ UNK_RET mnDiagram_80241E78(UNK_PARAMS);
/* 24227C */ UNK_RET mnDiagram_8024227C(UNK_PARAMS);
/* 2427B4 */ UNK_RET mnDiagram_802427B4(UNK_PARAMS);
/* 242B38 */ HSD_JObj* mnDiagram_80242B38(u8 idx, int arg1);
/* 242C0C */ UNK_RET mnDiagram_80242C0C(UNK_PARAMS);
/* 243038 */ void fn_80243038(HSD_GObj* gobj);
/* 2433AC */ void mnDiagram_802433AC(void);
/* 243434 */ UNK_RET mnDiagram_80243434(UNK_PARAMS);
/* 2437E8 */ void mnDiagram_802437E8(int arg0, int arg1);

#endif
