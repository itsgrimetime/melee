#ifndef GALE01_1CAFBC
#define GALE01_1CAFBC

#include <platform.h>
#include <baselib/forward.h>
#include <dolphin/mtx.h>

/* File-local data structures */

typedef struct grFZeroCar_CarData {
    s16 x0;
    s16 x2;
    s16 x4; /* car index 0 */
    s16 x6; /* car index 1 */
    s16 x8; /* car index 2 */
    s16 xA; /* car index 3 */
} grFZeroCar_CarData;

typedef struct grFZeroCar_TransformData {
    Vec3 scale;        /* 0x00 */
    Vec3 translate;    /* 0x0C */
    Quaternion rotate; /* 0x18 */
} grFZeroCar_TransformData;

/* 803B7E50 */ extern grFZeroCar_TransformData grFZeroCar_803B7E50;
/* 803E0BD8 */ extern grFZeroCar_CarData grFZeroCar_803E0BD8[30];
/* 804DADB8 */ extern f32 grFZeroCar_804DADB8;
/* 804DADC0 */ extern f64 grFZeroCar_804DADC0;
/* 804DADC8 */ extern f32 grFZeroCar_804DADC8;
/* 804DADCC */ extern f32 grFZeroCar_804DADCC;
/* 804DADD0 */ extern f32 grFZeroCar_804DADD0;

/* 1CAFBC */ void grFZeroCar_801CAFBC(HSD_GObj* gobj, s16* car_ids,
                                      s16 stage_id, s32 free_old);

#endif
