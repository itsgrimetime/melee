#include "itharisen.h"

#include <placeholder.h>
#include <platform.h>

#include "it/inlines.h"
#include "it/it_266F.h"
#include "it/it_26B1.h"
#include "it/it_2725.h"
#include "it/item.h"

void it_802927E8(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    HSD_JObj* jobj = gobj->hsd_obj;
    f32* spec_attrs = ip->xC4_article_data->x4_specialAttributes;
    ItemAttr* attrs = ip->xCC_item_attr;
    f32 scale = spec_attrs[0] * attrs->x60_scale;
    ip->scl = scale;
    it_80272F7C(jobj, scale);
}
void it_8029282C(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    ip->scl = ip->xCC_item_attr->x60_scale;
    Item_8026849C(gobj);
}

void it_3F14_Logic24_Spawned(Item_GObj* gobj)
{
    it_8029290C(gobj);
}

void it_8029287C(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    f32 zero;

    it_8026B390(gobj);
    zero = it_804DCAF8;
    ip->x40_vel.z = zero;
    ip->x40_vel.y = zero;
    ip->x40_vel.x = zero;
    Item_80268E5C(gobj, 0, ITEM_ANIM_UPDATE);
}
bool itHarisen_UnkMotion0_Anim(Item_GObj* gobj)
{
    return false;
}

void itHarisen_UnkMotion0_Phys(Item_GObj* gobj) {}

bool itHarisen_UnkMotion0_Coll(Item_GObj* gobj)
{
    it_8026D62C(gobj, it_8029290C);
    return false;
}

void it_8029290C(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 1, ITEM_ANIM_UPDATE);
}

bool itHarisen_UnkMotion8_Anim(Item_GObj* gobj)
{
    return false;
}

void itHarisen_UnkMotion1_Phys(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    ItemAttr* attrs = ip->xCC_item_attr;
    it_80272860(gobj, attrs->x10_fall_speed, attrs->x14_fall_speed_max);
}

bool itHarisen_UnkMotion1_Coll(Item_GObj* gobj)
{
    it_8026E15C(gobj, it_8029287C);
    return false;
}

void it_80292998(Item_GObj* gobj, f32 frameSpeed)
{
    Item* ip = GET_ITEM(gobj);
    ip->x5D0_animFrameSpeed = frameSpeed;
    Item_80268E5C(gobj, 3, ITEM_ANIM_UPDATE);
}

void it_802929C8(Item_GObj* gobj, f32 frameSpeed)
{
    Item* ip = GET_ITEM(gobj);
    ip->x5D0_animFrameSpeed = frameSpeed;
    Item_80268E5C(gobj, 4, ITEM_ANIM_UPDATE);
}

void it_802929F8(Item_GObj* gobj, f32 frameSpeed)
{
    Item* ip = GET_ITEM(gobj);
    ip->x5D0_animFrameSpeed = frameSpeed;
    Item_80268E5C(gobj, 5, ITEM_ANIM_UPDATE);
}

void it_80292A28(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    ip->x5D0_animFrameSpeed = 1.0f;
    Item_80268E5C(gobj, 6, ITEM_ANIM_UPDATE);
}

void it_3F14_Logic24_PickedUp(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 2, ITEM_ANIM_UPDATE);
}

bool itHarisen_UnkMotion6_Anim(Item_GObj* gobj)
{
    return false;
}

void itHarisen_UnkMotion6_Phys(Item_GObj* gobj) {}

void it_3F14_Logic24_Dropped(Item_GObj* gobj)
{
    s32 unused[2];
    Item* ip = gobj->user_data;
    ip->x5D0_animFrameSpeed = it_804DCAFC;
    ip = gobj->user_data;
    ip->scl = ip->xCC_item_attr->x60_scale;
    Item_8026849C(gobj);
    Item_80268E5C(gobj, 8, 6);
}
bool itHarisen_UnkMotion8_Coll(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;

    if (M2C_FIELD(ip, s32*, 0xD4C) != 0) {
        it_8026E15C(gobj, it_8029287C);
        return false;
    }
    return it_8026DF34(gobj);
}
void it_3F14_Logic24_Thrown(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 7, 6);
}

void itHarisen_UnkMotion8_Phys(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    ItemAttr* attrs = ip->xCC_item_attr;
    it_80272860(gobj, attrs->x10_fall_speed, attrs->x14_fall_speed_max);
    it_80274658(gobj, M2C_FIELD(it_804D6D28, f32*, 0x68));
}
bool itHarisen_UnkMotion7_Coll(Item_GObj* gobj)
{
    it_8026E15C(gobj, it_8029287C);
    return false;
}

bool it_3F14_Logic24_DmgDealt(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    s32 state = M2C_FIELD(ip, s32*, 0x24);
    if (state != 7) {
        if (state != 8) {
            goto skip;
        }
    }
    itColl_BounceOffVictim(gobj);
skip:
    return false;
}
void it_3F14_Logic24_EnteredAir(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 9, ITEM_ANIM_UPDATE);
}

bool itHarisen_UnkMotion9_Anim(Item_GObj* gobj)
{
    return false;
}

void itHarisen_UnkMotion9_Phys(Item_GObj* gobj) {}

bool itHarisen_UnkMotion9_Coll(Item_GObj* gobj)
{
    it_8026E8C4(gobj, it_8029287C, it_8029290C);
    return false;
}

bool it_3F14_Logic24_Clanked(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    s32 state = M2C_FIELD(ip, s32*, 0x24);
    if (state != 7) {
        if (state != 8) {
            goto skip;
        }
    }
    itColl_BounceOffVictim(gobj);
skip:
    return false;
}
bool it_3F14_Logic24_Reflected(Item_GObj* gobj)
{
    return it_80273030(gobj);
}

bool it_3F14_Logic24_HitShield(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    s32 state = M2C_FIELD(ip, s32*, 0x24);
    if (state != 7) {
        if (state != 8) {
            goto skip;
        }
    }
    itColl_BounceOffVictim(gobj);
skip:
    return false;
}
bool it_3F14_Logic24_ShieldBounced(Item_GObj* gobj)
{
    return itColl_BounceOffShield(gobj);
}

void it_3F14_Logic24_EvtUnk(Item_GObj* gobj, Item_GObj* ref_gobj)
{
    it_8026B894(gobj, ref_gobj);
}
