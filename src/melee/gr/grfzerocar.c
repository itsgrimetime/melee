#include "grfzerocar.h"

#include "gr/granime.h"
#include "gr/grdatfiles.h"
#include "gr/ground.h"
#include "lb/lb_00F9.h"

#include <dolphin/mtx.h>
#include <baselib/jobj.h>

/* Local version of UnkStageDat_x8_t with proper fields */
typedef struct grFZeroCar_StageDatEntry {
    struct HSD_Joint* unk0;
    HSD_AnimJoint** unk4;
    HSD_MatAnimJoint** unk8;
    u8 rest[0x34 - 0xC];
} grFZeroCar_StageDatEntry;

/* Helper macro to get hsd_obj from gobj at offset 0x28 */
#define GOBJ_HSD_OBJ(gobj) (*(HSD_JObj**) ((u8*) (gobj) + 0x28))

void grFZeroCar_801CAFBC(HSD_GObj* gobj, s16* car_ids, s16 stage_id,
                         s32 free_old)
{
    HSD_JObj* root_jobj;
    HSD_JObj* child_jobj;
    HSD_JObj* new_jobj;
    HSD_JObj* car_jobj0;
    HSD_JObj* car_jobj1;
    HSD_JObj* car_jobj2;
    HSD_JObj* car_jobj3;
    HSD_JObj* temp_jobj;
    grFZeroCar_CarData* car_data;
    s16* cur_car_id;
    f32 scale_factor;
    f32 car_scale;
    Vec3 scale;
    Vec3 translate;
    Quaternion rotate;
    s32 i;
    s32 count;
    s16 idx;

    root_jobj = GOBJ_HSD_OBJ(gobj);
    scale_factor = Ground_801C0498();

    /* Set scale on root jobj */
    scale = grFZeroCar_803B7E50.scale;
    HSD_JObjSetScale(root_jobj, &scale);

    /* Get first child */
    child_jobj = root_jobj != NULL ? root_jobj->child : NULL;

    if (free_old != 0) {
        lb_8000F9F8(child_jobj);
    }

    /* Allocate new jobj and add as next sibling */
    new_jobj = HSD_JObjAlloc();
    HSD_ASSERT(0xAC, new_jobj);
    PSMTXIdentity(new_jobj->mtx);
    new_jobj->scl = NULL;
    HSD_JObjAddNext(child_jobj, new_jobj);

    car_data = grFZeroCar_803E0BD8;
    cur_car_id = car_ids;

    for (i = 0; i < 30; i++) {
        if (i != 0) {
            child_jobj = Ground_801C13D0(*cur_car_id, 0);
            if (child_jobj != NULL) {
                new_jobj = HSD_JObjAlloc();
                HSD_ASSERT(0xBA, new_jobj);
                PSMTXIdentity(new_jobj->mtx);
                new_jobj->scl = NULL;
                HSD_JObjAddNext(child_jobj, new_jobj);
                HSD_JObjAddChild(root_jobj, new_jobj);
                if (free_old != 0) {
                    lb_8000F9F8(child_jobj);
                }
            } else {
                HSD_ASSERT(0xC3, 0);
            }
        }

        /* Set translate and rotate */
        translate = grFZeroCar_803B7E50.translate;
        rotate = grFZeroCar_803B7E50.rotate;
        HSD_JObjSetTranslate(child_jobj, &translate);
        HSD_JObjSetRotate(child_jobj, &rotate);

        /* Scale the new jobj */
        HSD_JObjGetScale(new_jobj, &scale);
        scale.x *= scale_factor;
        scale.y *= scale_factor;
        scale.z *= scale_factor;
        HSD_JObjSetScale(new_jobj, &scale);

        /* Count valid car indices */
        count = 0;
        car_scale = grFZeroCar_804DADC8;
        car_jobj0 = NULL;
        car_jobj1 = NULL;
        car_jobj2 = NULL;
        car_jobj3 = NULL;

        if (car_data->x4 != -1) {
            count = 1;
        }
        if (car_data->x6 != -1) {
            count++;
        }
        if (car_data->x8 != -1) {
            count++;
        }
        if (car_data->xA != -1) {
            count++;
        }

        switch (count) {
        case 1:
            car_scale = grFZeroCar_804DADCC;
            break;
        case 2:
            car_scale = grFZeroCar_804DADC8;
            break;
        case 3:
            car_scale = grFZeroCar_804DADC8;
            break;
        case 4:
            car_scale = grFZeroCar_804DADD0;
            break;
        }

        /* Find car jobjs by index */
        idx = car_data->x4;
        if (idx != -1) {
            temp_jobj = child_jobj;
            while (temp_jobj != NULL && idx != 0) {
                idx--;
                temp_jobj = Ground_801C4100(temp_jobj);
            }
            car_jobj0 = temp_jobj;
        }

        idx = car_data->x6;
        if (idx != -1) {
            temp_jobj = child_jobj;
            while (temp_jobj != NULL && idx != 0) {
                idx--;
                temp_jobj = Ground_801C4100(temp_jobj);
            }
            car_jobj1 = temp_jobj;
        }

        idx = car_data->x8;
        if (idx != -1) {
            temp_jobj = child_jobj;
            while (temp_jobj != NULL && idx != 0) {
                idx--;
                temp_jobj = Ground_801C4100(temp_jobj);
            }
            car_jobj2 = temp_jobj;
        }

        idx = car_data->xA;
        if (idx != -1) {
            temp_jobj = child_jobj;
            while (temp_jobj != NULL && idx != 0) {
                idx--;
                temp_jobj = Ground_801C4100(temp_jobj);
            }
            car_jobj3 = temp_jobj;
        }

        /* Setup each car jobj */
        if (car_jobj0 != NULL) {
            UnkArchiveStruct* archive = grDatFiles_801C6330(stage_id);
            grFZeroCar_StageDatEntry* entry;
            HSD_ASSERT(0x5F, archive);
            temp_jobj = Ground_801C13D0(stage_id, 0);
            if (temp_jobj != NULL) {
                entry =
                    (grFZeroCar_StageDatEntry*) &archive->unk4->unk8[stage_id];
                if (entry->unk4 != NULL && entry->unk8 != NULL) {
                    grAnime_801C6C0C(temp_jobj, *entry->unk4, *entry->unk8, 0);
                    HSD_JObjReqAnimAllByFlags(temp_jobj, 0x497,
                                              grFZeroCar_804DADB8);
                    HSD_ForeachAnim(temp_jobj, JOBJ_TYPE, 0x76A4,
                                    HSD_AObjSetRate, AOBJ_ARG_AF,
                                    grFZeroCar_804DADC0);
                }
                HSD_JObjAddChild(car_jobj0, temp_jobj);
            }
            HSD_JObjSetScaleX(car_jobj0, car_scale);
            HSD_JObjSetScaleY(car_jobj0, car_scale);
        }

        if (car_jobj1 != NULL) {
            UnkArchiveStruct* archive = grDatFiles_801C6330(stage_id);
            grFZeroCar_StageDatEntry* entry;
            HSD_ASSERT(0x5F, archive);
            temp_jobj = Ground_801C13D0(stage_id, 0);
            if (temp_jobj != NULL) {
                entry =
                    (grFZeroCar_StageDatEntry*) &archive->unk4->unk8[stage_id];
                if (entry->unk4 != NULL && entry->unk8 != NULL) {
                    grAnime_801C6C0C(temp_jobj, *entry->unk4, *entry->unk8, 0);
                    HSD_JObjReqAnimAllByFlags(temp_jobj, 0x497,
                                              grFZeroCar_804DADB8);
                    HSD_ForeachAnim(temp_jobj, JOBJ_TYPE, 0x76A4,
                                    HSD_AObjSetRate, AOBJ_ARG_AF,
                                    grFZeroCar_804DADC0);
                }
                HSD_JObjAddChild(car_jobj1, temp_jobj);
            }
            HSD_JObjSetScaleX(car_jobj1, car_scale);
            HSD_JObjSetScaleY(car_jobj1, car_scale);
        }

        if (car_jobj2 != NULL) {
            UnkArchiveStruct* archive = grDatFiles_801C6330(stage_id);
            grFZeroCar_StageDatEntry* entry;
            HSD_ASSERT(0x5F, archive);
            temp_jobj = Ground_801C13D0(stage_id, 0);
            if (temp_jobj != NULL) {
                entry =
                    (grFZeroCar_StageDatEntry*) &archive->unk4->unk8[stage_id];
                if (entry->unk4 != NULL && entry->unk8 != NULL) {
                    grAnime_801C6C0C(temp_jobj, *entry->unk4, *entry->unk8, 0);
                    HSD_JObjReqAnimAllByFlags(temp_jobj, 0x497,
                                              grFZeroCar_804DADB8);
                    HSD_ForeachAnim(temp_jobj, JOBJ_TYPE, 0x76A4,
                                    HSD_AObjSetRate, AOBJ_ARG_AF,
                                    grFZeroCar_804DADC0);
                }
                HSD_JObjAddChild(car_jobj2, temp_jobj);
            }
            HSD_JObjSetScaleX(car_jobj2, car_scale);
            HSD_JObjSetScaleY(car_jobj2, car_scale);
        }

        if (car_jobj3 != NULL) {
            UnkArchiveStruct* archive = grDatFiles_801C6330(stage_id);
            grFZeroCar_StageDatEntry* entry;
            HSD_ASSERT(0x5F, archive);
            temp_jobj = Ground_801C13D0(stage_id, 0);
            if (temp_jobj != NULL) {
                entry =
                    (grFZeroCar_StageDatEntry*) &archive->unk4->unk8[stage_id];
                if (entry->unk4 != NULL && entry->unk8 != NULL) {
                    grAnime_801C6C0C(temp_jobj, *entry->unk4, *entry->unk8, 0);
                    HSD_JObjReqAnimAllByFlags(temp_jobj, 0x497,
                                              grFZeroCar_804DADB8);
                    HSD_ForeachAnim(temp_jobj, JOBJ_TYPE, 0x76A4,
                                    HSD_AObjSetRate, AOBJ_ARG_AF,
                                    grFZeroCar_804DADC0);
                }
                HSD_JObjAddChild(car_jobj3, temp_jobj);
            }
            HSD_JObjSetScaleX(car_jobj3, car_scale);
            HSD_JObjSetScaleY(car_jobj3, car_scale);
        }

        cur_car_id += 2;
        car_data++;
    }
}
