#include "itbox.h"

#include <placeholder.h>
#include <platform.h>

#include "cm/camera.h"
#include "gr/grkongo.h"
#include "it/inlines.h"
#include "it/it_266F.h"
#include "it/it_26B1.h"
#include "it/it_2725.h"
#include "it/item.h"
#include "lb/lb_00F9.h"
#include "lb/lbvector.h"
#include "mp/mpcoll.h"

#include <baselib/random.h>

/// #it_80286088

void it_3F14_Logic1_Spawned(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    ip->xDCE_flag.b7 = 0;
    ip->xDD4_itemVar.box.xDD4 = 0;
    ip->xDD4_itemVar.box.xDDC = NULL;
    it_8028655C(gobj);
}

void it_3F14_Logic1_Destroyed(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    if (ip->xDD4_itemVar.box.xDDC != NULL) {
        grKongo_801D8058(ip->xDD4_itemVar.box.xDDC);
        ip->xDD4_itemVar.box.xDDC = NULL;
    }
}

void it_80286248(Item_GObj* gobj, s32 a, s32 b, s32 c, s32 d)
{
    Vec3 sp24;
    s32 ab;
    Item* ip;
    s32 flag;
    s32 rand;
    f32 zero;
    PAD_STACK(28);

    ip = gobj->user_data;
    zero = it_804DC904;
    sp24.z = zero;
    sp24.y = zero;
    sp24.x = zero;

    if (it_8026F8B4(gobj, &ip->pos, &sp24, 0)) {
        return;
    }
    if (it_8026F6BC(gobj, &ip->pos, &sp24, 0) != 0) {
        return;
    }
    flag = 0;
    if (HSD_Randi(d) == 0) {
        flag |= 1;
    }
    ab = a + b;
    rand = HSD_Randi(c + ab);
    if (rand < a) {
        it_8026F3D4(gobj, 0, 1, flag);
        return;
    }
    if (rand < ab) {
        it_8026F3D4(gobj, 0, 2, flag);
        return;
    }
    it_8026F3D4(gobj, 0, 3, flag);
}
bool it_80286340(Item_GObj* gobj, s32 a, s32 b, s32 c, s32 d)
{
    s32 ab = a + b;
    s32 abc = c + ab;
    s32 rand = HSD_Randi(d + abc);

    if (rand < a) {
        return true;
    }
    if (rand < ab) {
        return true;
    }
    if (rand < abc) {
        return true;
    }
    return false;
}

bool it_802863BC(Item_GObj* gobj)
{
    Vec3 sp1C;
    Vec3 sp10;
    Item* ip = gobj->user_data;
    CollData* coll = (CollData*) &M2C_FIELD(ip, u8*, 0x378);
    void* sa = ip->xC4_article_data->x4_specialAttributes;

    if (M2C_FIELD(ip, u32*, 0x4AC) & 0x18000) {
        it_80276408(gobj, coll, &sp1C);
        sp10.x = it_804DC904;
        sp10.y = it_804DC900;
        sp10.z = it_804DC904;

        if (lbVector_AngleXY(&sp1C, &sp10) < M2C_FIELD(sa, f32*, 0x18)) {
            f32 zero = it_804DC904;
            M2C_FIELD(ip, f32*, 0x84) = zero;
            M2C_FIELD(ip, f32*, 0x80) = zero;
            M2C_FIELD(ip, f32*, 0x7C) = zero;
            M2C_FIELD(ip, f32*, 0x90) = zero;
            M2C_FIELD(ip, f32*, 0x8C) = zero;
            M2C_FIELD(ip, f32*, 0x88) = zero;
            M2C_FIELD(ip, f32*, 0x9C) = zero;
            M2C_FIELD(ip, f32*, 0x98) = zero;
            M2C_FIELD(ip, f32*, 0x94) = zero;
            M2C_FIELD(ip, f32*, 0xA8) = zero;
            M2C_FIELD(ip, f32*, 0xA4) = zero;
            M2C_FIELD(ip, f32*, 0xA0) = zero;
            M2C_FIELD(ip, s32*, 0xD5C) = 1;
            return true;
        }
    }
    return false;
}

void fn_80286480(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    f32 zero;
    it_8026B390(gobj);
    zero = 0.0f;
    ip->x40_vel.z = zero;
    ip->x40_vel.y = zero;
    ip->x40_vel.x = zero;
    Item_80268E5C(gobj, 0, ITEM_ANIM_UPDATE);
}

bool itBox_UnkMotion0_Anim(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    if (ip->xD44_lifeTimer <= 0.0f) {
        it_802787B4(gobj, 0x421);
    }
    return false;
}

void itBox_UnkMotion0_Phys(Item_GObj* gobj) {}

bool itBox_UnkMotion0_Coll(Item_GObj* gobj)
{
    it_8026D62C(gobj, it_8028655C);
    it_80276CB8(gobj);
    return false;
}

void it_8028655C(Item_GObj* gobj)
{
    it_8026B3A8(gobj);
    Item_80268E5C(gobj, 1, ITEM_ANIM_UPDATE);
}

bool itBox_UnkMotion4_Anim(Item_GObj* gobj)
{
    return false;
}

/// #itBox_UnkMotion1_Phys

bool itBox_UnkMotion1_Coll(Item_GObj* gobj)
{
    it_8026E15C(gobj, fn_80286480);
    return false;
}

void it_3F14_Logic1_PickedUp(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 2, ITEM_ANIM_UPDATE);
}

bool itBox_UnkMotion2_Anim(Item_GObj* gobj)
{
    return false;
}

void itBox_UnkMotion2_Phys(Item_GObj* gobj) {}

void it_3F14_Logic1_Thrown(Item_GObj* gobj)
{
    it_8026B3A8(gobj);
    Item_80268E5C(gobj, 3, ITEM_ANIM_UPDATE | ITEM_DROP_UPDATE);
}

void itBox_UnkMotion4_Phys(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    ItemAttr* attrs = ip->xCC_item_attr;
    it_80272860(gobj, attrs->x10_fall_speed, attrs->x14_fall_speed_max);
    it_80274658(gobj, it_804D6D28->x68_float);
}

/// #itBox_UnkMotion3_Coll

void it_3F14_Logic1_Dropped(Item_GObj* gobj)
{
    it_8026B3A8(gobj);
    Item_80268E5C(gobj, 4, ITEM_ANIM_UPDATE | ITEM_DROP_UPDATE);
}

/// #itBox_UnkMotion4_Coll

void it_80286AA4(Item_GObj* gobj)
{
    Vec3 pos;
    Item* ip = gobj->user_data;
    f32 vel;
    PAD_STACK(8);

    it_8026BB44(gobj);
    it_80272C08(gobj);
    it_802756D0(gobj);
    it_8026B3A8(gobj);
    it_8026BD24(gobj);
    it_8027518C(gobj);
    vel = it_804DC904;
    ip->x40_vel.x = vel;
    ip->x40_vel.y = vel;
    ip->xDCF_flag.b2 = 1;
    ip->xDD4_itemVar.box.xDD4 = 1;
    ip->xDD4_itemVar.box.xDD8 = 40;
    it_80275444(gobj);
    pos = ip->pos;
    lb_800119DC(&pos, 0x78, it_804DC900, it_804DC928, it_804DC92C);
    Item_80268E5C(gobj, 6, ITEM_ANIM_UPDATE);
}

bool itBox_UnkMotion6_Anim(Item_GObj* gobj)
{
    return it_802751D8(gobj);
}

void itBox_UnkMotion6_Phys(Item_GObj* gobj) {}

bool itBox_UnkMotion6_Coll(Item_GObj* gobj)
{
    return false;
}

void it_80286BA0(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    s32* attrs;
    HSD_JObj* jobj = gobj->hsd_obj;
    f32 vel;
    PAD_STACK(8);

    attrs = ip->xC4_article_data->x4_specialAttributes;
    Item_8026AE84(ip, 0xF6, 0x7F, 0x40);
    Camera_80030E44(2, &ip->pos);
    it_80286248(gobj, attrs[0], attrs[1], attrs[2], attrs[4]);
    HSD_JObjSetFlagsAll(jobj, 0x10);
    it_802756D0(gobj);
    vel = it_804DC904;
    ip->x40_vel.x = vel;
    ip->x40_vel.y = vel;
    ip->xDCF_flag.b2 = 1;
    ip->xDD4_itemVar.box.xDD4 = 1;
    ip->xDD4_itemVar.box.xDD8 = 40;
    it_8026B3A8(gobj);
    Item_80268E5C(gobj, 7, ITEM_ANIM_UPDATE);
}
bool itBox_UnkMotion7_Anim(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    ip->xDD4_itemVar.box.xDD8 -= 1;
    if (ip->xDD4_itemVar.box.xDD8 > 0) {
        return false;
    }
    return true;
}

void itBox_UnkMotion7_Phys(Item_GObj* gobj) {}

bool itBox_UnkMotion7_Coll(Item_GObj* gobj)
{
    return false;
}

/// #it_3F14_Logic1_DmgDealt

/// #it_3F14_Logic1_Clanked

/// #it_3F14_Logic1_HitShield

/// #it_3F14_Logic1_Reflected

/// #it_3F14_Logic1_DmgReceived

void it_3F14_Logic1_EnteredAir(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 4, ITEM_ANIM_UPDATE);
}

bool itBox_UnkMotion5_Anim(Item_GObj* gobj)
{
    return false;
}

void itBox_UnkMotion5_Phys(Item_GObj* gobj) {}

bool itBox_UnkMotion5_Coll(Item_GObj* gobj)
{
    it_8026E8C4(gobj, fn_80286480, it_8028655C);
    return false;
}

void it_3F14_Logic1_EvtUnk(Item_GObj* gobj, Item_GObj* ref_gobj)
{
    it_8026B894(gobj, ref_gobj);
}

void it_802870A4(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    it_802762B0(ip);
    it_8026B3A8(gobj);
    Item_80268E5C(gobj, 8, ITEM_ANIM_UPDATE);
    ip->on_accessory = it_8028733C;
}
bool itBox_UnkMotion8_Anim(Item_GObj* gobj)
{
    return false;
}

/// #itBox_UnkMotion8_Phys

bool itBox_UnkMotion8_Coll(Item_GObj* gobj)
{
    return false;
}

void it_8028733C(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    HSD_GObj* xDDC;
    HSD_JObj* jobj;
    Vec3 sp24;
    Vec3 sp18;
    PAD_STACK(8);

    xDDC = ip->xDD4_itemVar.box.xDDC;
    if (xDDC != NULL) {
        jobj = xDDC->hsd_obj;
        if (jobj == NULL) {
            __assert("jobj.h", 987, "jobj != NULL");
        }
        sp24 = jobj->translate;
        lbVector_Diff(&sp24, &ip->pos, &sp18);
        ip->pos = sp24;
        if (sp24.z >= it_804DC904) {
            ip->x40_vel = sp18;
            mpColl_80043680(&ip->x378_itemColl, &ip->pos);
            it_8026B3A8(gobj);
            Item_80268E5C(gobj, 1, ITEM_ANIM_UPDATE);
        }
    } else {
        mpColl_80043680(&ip->x378_itemColl, &ip->pos);
        it_8026B3A8(gobj);
        Item_80268E5C(gobj, 1, ITEM_ANIM_UPDATE);
    }
}
