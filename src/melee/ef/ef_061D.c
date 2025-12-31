#include "ef_061D.h"

#include "eflib.h"
#include "types.h"

#include <placeholder.h>
#include <baselib/gobj.h>
#include <baselib/jobj.h>
#include <baselib/particle.h>

extern s32 efLib_804D64E8;

static char ef_803BF9D0[] = "!(jobj->flags & JOBJ_USE_QUATERNION)";
static char ef_804D39D8[] = "jobj.h";
static char ef_804D39E0[] = "jobj";

static f32 ef_804D81D0 = 0.0f;
static f64 ef_804D81D8 = -1.0;
static f64 ef_804D81E0 = 1.0;
static f32 ef_804D81E8 = 1.0f;
static f32 ef_804D81EC = 3.0f;
static f32 ef_804D81F0 = -1.0f;

void* ef_80061D70(s32 gfx_id, HSD_GObj* parent_gobj, va_list vlist)
{
    void* result = NULL;
    HSD_JObj* jobj;
    HSD_JObj* jobj2;
    Vec3* vec3_ptr;
    f32* f32_ptr;
    f32 scale;
    s32 switch_idx;

    efLib_804D64E8 = 1;
    switch_idx = gfx_id - 0x479;

    if (switch_idx > 0x40) {
        return NULL;
    }

    switch (gfx_id) {
    case 0x479:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C9FC(0x3F2, vec3_ptr);
        break;

    case 0x47A:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0x3E8, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        hsd_8039EFAC(0, 1, 0x3E9, jobj);
        break;

    case 0x47B:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C9FC(0x3EB, vec3_ptr);
        break;

    case 0x47C:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0x3E9, parent_gobj, jobj);
        if (result != NULL) {
            ((Effect*)result)->x10 = efLib_8005F08C;
        }
        break;

    case 0x47D:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 1, 0x3F0, jobj);
        break;

    case 0x47E:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 1, 0x3F1, jobj);
        break;

    case 0x47F:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 2, 0x7D4, jobj);
        break;

    case 0x480:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 2, 0x7D2, jobj);
        break;

    case 0x481:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 2, 0x7D3, jobj);
        break;

    case 0x482:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0x7D0, parent_gobj, jobj);
        if (result != NULL) {
            ((Effect*)result)->x10 = efLib_8005EBC8;
        }
        break;

    case 0x483:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C9FC(0x7D7, vec3_ptr);
        break;

    case 0x484:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 2, 0x7DB, jobj);
        break;

    case 0x485:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 2, 0x7DE, jobj);
        break;

    case 0x486:
        jobj = va_arg(vlist, HSD_JObj*);
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C814(0x7D1, parent_gobj, vec3_ptr);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->scale.x = vec3_ptr->x;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        hsd_8039EFAC(0, 1, 0x7D2, jobj);
        break;

    case 0x487:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C5C4(0x7D2, parent_gobj, jobj);
        break;

    case 0x488:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0xBB8, parent_gobj, jobj);
        break;

    case 0x489:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0xBB9, parent_gobj, jobj);
        break;

    case 0x48A:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0xBBA, parent_gobj, jobj);
        break;

    case 0x48B:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0xBBB, parent_gobj, jobj);
        break;

    case 0x48C:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0xBBC, parent_gobj, jobj);
        if (result != NULL) {
            ((Effect*)result)->x10 = efLib_8005E3A0;
        }
        break;

    case 0x48D:
        result = efLib_8005CF40(0xBC0, &vlist);
        break;

    case 0x48E:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C814(0xBBD, parent_gobj, vec3_ptr);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->scale.x = ef_804D81E8;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
            f32_ptr = va_arg(vlist, f32*);
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x2A9, "jobj");
            __assert("jobj.h", 0x2AA, ef_803BF9D0);
            jobj2->scale.y = *f32_ptr;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        break;

    case 0x48F:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C6F4(0xFA0, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            jobj = va_arg(vlist, HSD_JObj*);
            eff->x0 = (ef_UnkStruct2*)efLib_8005C6F4(0xFA1, parent_gobj, jobj);
        }
        break;

    case 0x490:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0xFA2, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            eff->translate.z = *f32_ptr;
            eff->x10 = efLib_8005EDDC;
        }
        break;

    case 0x491:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0xFA4, parent_gobj, jobj);
        break;

    case 0x492:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0xFA3, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        break;

    case 0x493:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0xFA5, parent_gobj, jobj);
        if (result != NULL) {
            ((Effect*)result)->x10 = efLib_8005F270;
        }
        break;

    case 0x494:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0xFA6, parent_gobj, jobj);
        break;

    case 0x495:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0xFA7, parent_gobj, jobj);
        break;

    case 0x496:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C2BC(0xFA8, parent_gobj, jobj);
        break;

    case 0x497:
        result = efLib_8005CF40(0x138B, &vlist);
        break;

    case 0x498:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 5, 0x138F, jobj);
        break;

    case 0x499:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 5, 0x1395, jobj);
        break;

    case 0x49A:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0x9858, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
            jobj2 = GET_JOBJ(eff->gobj);
            HSD_JObjAnimAll(jobj2);
        }
        break;

    case 0x49B:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0x9859, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
            jobj2 = GET_JOBJ(eff->gobj);
            HSD_JObjAnimAll(jobj2);
        }
        break;

    case 0x49C: {
        HSD_JObj* saved_jobj;
        jobj = va_arg(vlist, HSD_JObj*);
        saved_jobj = jobj;
        result = efLib_8005C6F4(0x9471, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            jobj = va_arg(vlist, HSD_JObj*);
            eff->x0 = (ef_UnkStruct2*)efLib_8005C6F4(0x9470, parent_gobj, jobj);
        }
        break;
    }

    case 0x49D:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C814(0x80E8, parent_gobj, vec3_ptr);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->scale.x = ef_804D81E8;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
            f32_ptr = va_arg(vlist, f32*);
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x2A9, "jobj");
            __assert("jobj.h", 0x2AA, ef_803BF9D0);
            jobj2->scale.y = *f32_ptr;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        break;

    case 0x49E:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x24, 0x8CA0, jobj);
        break;

    case 0x49F:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x2E, 0xB3B0, jobj);
        break;

    case 0x4A0:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x2E, 0xB3B1, jobj);
        break;

    case 0x4A1:
        result = efLib_8005CF40(0xB3B6, &vlist);
        break;

    case 0x4A2: {
        HSD_JObj* saved_jobj;
        jobj = va_arg(vlist, HSD_JObj*);
        saved_jobj = jobj;
        result = efLib_8005C1B4(0x9088, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        hsd_8039EFAC(0, 0x25, 0x9088, saved_jobj);
        break;
    }

    case 0x4A3:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C9FC(0x908A, vec3_ptr);
        break;

    case 0x4A4: {
        HSD_JObj* saved_jobj;
        jobj = va_arg(vlist, HSD_JObj*);
        saved_jobj = jobj;
        result = efLib_8005C6F4(0xB799, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            jobj = va_arg(vlist, HSD_JObj*);
            eff->x0 = (ef_UnkStruct2*)efLib_8005C6F4(0xB798, parent_gobj, jobj);
        }
        break;
    }

    case 0x4A5:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C6F4(0x4E20, parent_gobj, jobj);
        break;

    case 0x4A6:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C6F4(0x4E21, parent_gobj, jobj);
        break;

    case 0x4A7:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C2BC(0x5208, parent_gobj, jobj);
        goto shared_scale_copy;

    case 0x4A8:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C2BC(0x5209, parent_gobj, jobj);
    shared_scale_copy:
        if (result != NULL) {
            Vec3 saved_scale;
            HSD_JObj* parent_jobj = GET_JOBJ(parent_gobj);
            __assert("jobj.h", 0x337, "jobj");
            saved_scale.x = parent_jobj->scale.x;
            saved_scale.y = parent_jobj->scale.y;
            saved_scale.z = parent_jobj->scale.z;
            jobj2 = GET_JOBJ(((Effect*)result)->gobj);
            __assert("jobj.h", 0x337, "jobj");
            jobj2 = GET_JOBJ(((Effect*)result)->gobj);
            __assert("jobj.h", 0x2F8, "jobj");
            jobj2->scale.x = saved_scale.x;
            jobj2->scale.y = saved_scale.y;
            jobj2->scale.z = saved_scale.z;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        break;

    case 0x4A9:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x2E, 0xB3B0, jobj);
        break;

    case 0x4AA:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x2E, 0xB3B1, jobj);
        break;

    case 0x4AB:
        result = efLib_8005CF40(0xB3B6, &vlist);
        break;

    case 0x4AC:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C9FC(0x206, vec3_ptr);
        break;

    case 0x4AD: {
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C1B4(0x7D00, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        hsd_8039EFAC(0, 0x20, 0x7D00, jobj);
        break;
    }

    case 0x4AE:
        vec3_ptr = va_arg(vlist, Vec3*);
        result = efLib_8005C9FC(0x7D02, vec3_ptr);
        break;

    case 0x4AF:
        result = efLib_8005CD2C(0xA028, &vlist, parent_gobj);
        break;

    case 0x4B0:
        result = efLib_8005CD2C(0xA029, &vlist, parent_gobj);
        break;

    case 0x4B1:
        result = efLib_8005CD2C(0xA02A, &vlist, parent_gobj);
        break;

    case 0x4B2:
        result = efLib_8005CD2C(0xA02B, &vlist, parent_gobj);
        break;

    case 0x4B3:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x22, 0x84D4, jobj);
        break;

    case 0x4B4:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x22, 0x84D2, jobj);
        break;

    case 0x4B5:
        jobj = va_arg(vlist, HSD_JObj*);
        result = hsd_8039EFAC(0, 0x22, 0x84D3, jobj);
        break;

    case 0x4B6: {
        Vec3* vec3 = va_arg(vlist, Vec3*);
        result = efLib_8005C814(0x84D0, parent_gobj, vec3);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        break;
    }

    case 0x4B7: {
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C3DC(0x9858, parent_gobj, jobj);
        if (result != NULL) {
            Effect* eff = (Effect*)result;
            f32_ptr = va_arg(vlist, f32*);
            if (*f32_ptr < 0.0f) {
                scale = -1.0f;
            } else {
                scale = 1.0f;
            }
            jobj2 = GET_JOBJ(eff->gobj);
            __assert("jobj.h", 0x294, "jobj");
            __assert("jobj.h", 0x295, ef_803BF9D0);
            jobj2->rotate.x = scale;
            if (!(jobj2->flags & JOBJ_MTX_INDEP_SRT)) {
                if (jobj2 != NULL) {
                    HSD_JObjMtxIsDirty(jobj2);
                }
            }
        }
        break;
    }

    case 0x4B8:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C6F4(0xBB80, parent_gobj, jobj);
        break;

    case 0x4B9:
        jobj = va_arg(vlist, HSD_JObj*);
        result = efLib_8005C6F4(0xBB81, parent_gobj, jobj);
        break;

    default:
        break;
    }

    return result;
}
