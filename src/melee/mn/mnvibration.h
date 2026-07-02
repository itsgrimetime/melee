#ifndef MELEE_MN_VIBRATION_H
#define MELEE_MN_VIBRATION_H

#include <placeholder.h>
#include <platform.h>

#include <baselib/forward.h>

#include <dolphin/mtx.h>

extern f32 mnVibration_804DC020;
extern f32 mnVibration_804DC030; ///< sdata2 pool; 0.0 (also cursor req-anim
                                 ///< frame 0)
/* 804DC034/038/03C/040/044/048/04C are the same sdata2 pool run (0.03, -9.5,
 * 9.1, 17.0, 364.68332, 38.38772, 0.0521), kept as individual anchors rather
 * than one array view - the loads use direct SDA relocs, not indexing. */
extern f32 mnVibration_804DC050; ///< intro-reveal frame, port panel 1 (10.0)
extern f32 mnVibration_804DC054; ///< intro-reveal frame, port panel 2 (11.0)
extern f32 mnVibration_804DC058; ///< intro-reveal frame, port panel 3 (12.0)
extern f32 mnVibration_804DC05C; ///< intro-reveal frame, port panel 4 (13.0)
extern f32 mnVibration_804DC060; ///< intro-reveal frame, name list (14.0)
extern SDATA char mnVibration_804D4FF4[];
extern SDATA char mnVibration_804D4FFC[];

/* 2474C4 */ HSD_JObj* mnVibration_802474C4(s32 count);
/* 247510 */ void fn_80247510(HSD_GObj*);
/* 248084 */ void fn_80248084(HSD_GObj* gobj);
/* 2480B4 */ void mnVibration_802480B4(HSD_JObj* arg0, u8 arg1, u8 arg2);
/* 24829C */ void mnVibration_8024829C(HSD_GObj* arg0);
/* 248444 */ void mnVibration_80248444(HSD_GObj* arg0, u8 arg1, u8 arg2);
/* 248644 */ void mnVibration_80248644(HSD_GObj* arg0);
/* 248748 */ void fn_80248748(HSD_GObj* gobj);
/* 2487A8 */ void fn_802487A8(HSD_GObj* gobj);
/* 248A78 */ void fn_80248A78(HSD_GObj*);
/* 248ED4 */ void mnVibration_80248ED4(s32 arg0);
/* 249174 */ void mnVibration_80249174(int arg0);

#endif
