#include "itfreeze.h"

#include "it/inlines.h"
#include "it/it_266F.h"
#include "it/it_26B1.h"
#include "it/it_2725.h"
#include "it/item.h"
#include "it/items/itwhitebea.h"

typedef struct {
    u8 b567 : 3;
    u8 b4 : 1;
    u8 b0123 : 4;
} ByteBits;

/// #it_8028EB88

/// #it_8028EC98

void it_8028ECE0(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.freeze.unk_1C = NULL;
}

Item* it_8028ECF0(Item_GObj* gobj, Vec3* v)
{
    Item* ip = GET_ITEM(gobj);
    v->x = ip->pos.x;
    v->y = ip->pos.y;
    v->z = ip->pos.z;
    return ip;
}

void it_3F14_Logic17_Destroyed(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    if (ip->xDD4_itemVar.freeze.unk_1C != NULL) {
        it_802E37A4((Item_GObj*) ip->xDD4_itemVar.freeze.unk_1C);
        ip->xDD4_itemVar.freeze.unk_1C = NULL;
    }
}
void it_3F14_Logic17_Spawned(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    f32 zero = it_804DCA70;
    f32 posx = ip->pos.x;

    if (posx > zero) {
        ip->facing_dir = it_804DCA80;
    } else {
        ip->facing_dir = it_804DCA84;
    }

    M2C_FIELD(ip, s32*, 0xD5C) = 0;
    zero = it_804DCA70;
    M2C_FIELD(ip, f32*, 0xDD4) = zero;
    M2C_FIELD(ip, f32*, 0xDD8) = zero;
    M2C_FIELD(ip, f32*, 0xDDC) = it_804DCA84;
    M2C_FIELD(ip, f32*, 0xDE0) = zero;
    ip->xDD4_itemVar.freeze.unk_1C = NULL;

    it_8028F1D8(gobj);
}
/// #it_8028EDBC

void it_8028EF34(Item_GObj* gobj)
{
    f32 zero;
    s32 unused[2];
    Item* ip = gobj->user_data;
    ip->x40_vel.x = M2C_FIELD(ip, f32*, 0xDD4);
    zero = it_804DCA70;
    ip->x40_vel.z = zero;
    ip->x40_vel.y = zero;
    it_8026B390(gobj);
    Item_80268E5C(gobj, 0, ITEM_ANIM_UPDATE);
}
bool itFreeze_UnkMotion0_Anim(Item_GObj* gobj)
{
    return false;
}

void itFreeze_UnkMotion0_Phys(Item_GObj* gobj)
{
    it_8028EDBC(gobj);
}

/// #itFreeze_UnkMotion0_Coll

void it_8028F1D8(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 1, ITEM_ANIM_UPDATE);
}

bool itFreeze_UnkMotion3_Anim(Item_GObj* gobj)
{
    return false;
}

void itFreeze_UnkMotion1_Phys(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    ItemAttr* attrs = ip->xCC_item_attr;
    it_80272860(gobj, attrs->x10_fall_speed, attrs->x14_fall_speed_max);
}

bool itFreeze_UnkMotion1_Coll(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    CollData* coll = &ip->x378_itemColl;

    it_8026E414(gobj, it_8028EF34);

    if (M2C_FIELD(ip, s32*, 0xC0) != 1 && (coll->env_flags & 0x18000)) {
        it_80276408(gobj, coll, &M2C_FIELD(ip, void*, 0xDD8));
    }

    return false;
}
void it_3F14_Logic17_PickedUp(Item_GObj* gobj)
{
    Item* item = gobj->user_data;
    Item_GObj* linked;

    if ((linked = (Item_GObj*) item->xDD4_itemVar.freeze.unk_1C) != NULL) {
        it_802E37A4(linked);
        item->xDD4_itemVar.freeze.unk_1C = NULL;
    }

    Item_80268E5C(gobj, 2, ITEM_ANIM_UPDATE);
}

bool itFreeze_UnkMotion2_Anim(Item_GObj* gobj)
{
    return false;
}

void it_3F14_Logic17_Dropped(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 1, 6);
}

void it_3F14_Logic17_Thrown(Item_GObj* gobj)
{
    Item_80268E5C(gobj, 3, 6);
}

void itFreeze_UnkMotion3_Phys(Item_GObj* gobj)
{
    Item* ip;
    ItemAttr* it_attr;

    ip = gobj->user_data;
    it_attr = ip->xCC_item_attr;
    it_80272860(gobj, it_attr->x10_fall_speed, it_attr->x14_fall_speed_max);
}

bool itFreeze_UnkMotion3_Coll(Item_GObj* gobj)
{
    if (it_8026DAA8(gobj) != 0) {
        return 1;
    }
    return 0;
}

bool it_3F14_Logic17_DmgDealt(Item_GObj* arg0)
{
    return true;
}

bool it_3F14_Logic17_Clanked(Item_GObj* arg0)
{
    return true;
}

bool it_3F14_Logic17_HitShield(Item_GObj* arg0)
{
    return true;
}

bool it_3F14_Logic17_Absorbed(Item_GObj* arg0)
{
    return true;
}

bool it_3F14_Logic17_Reflected(Item_GObj* gobj)
{
    return it_80273030(gobj);
}

bool it_3F14_Logic17_ShieldBounced(Item_GObj* gobj)
{
    return itColl_BounceOffShield(gobj);
}

bool it_3F14_Logic17_DmgReceived(Item_GObj* arg0)
{
    return true;
}

void it_8028F434(Item_GObj* gobj, f32 val, s32 arg)
{
    s32 unused[2];
    Item* ip = gobj->user_data;
    f32 zero = it_804DCA70;

    ip->x40_vel.z = zero;
    ip->x40_vel.y = zero;
    ip->x40_vel.x = zero;

    if (val < zero) {
        val = -val;
    }

    M2C_FIELD(ip, f32*, 0xDE8) = val;
    M2C_FIELD(ip, s32*, 0xDF0) = arg;

    it_8026B390(gobj);
    it_802762B0(ip);
    Item_80268E5C(gobj, 4, ITEM_ANIM_UPDATE);
}
bool itFreeze_UnkMotion4_Anim(Item_GObj* gobj)
{
    return false;
}

/// #itFreeze_UnkMotion4_Phys

/// #itFreeze_UnkMotion4_Coll

void it_8028F7C8(Item_GObj* gobj)
{
    s32 unused[3];
    Item* ip = gobj->user_data;
    f32 zero = it_804DCA70;
    ip->x40_vel.z = zero;
    ip->x40_vel.y = zero;
    ip->x40_vel.x = zero;
    it_8026B390(gobj);
    M2C_FIELD(ip, s32*, 0xDEC) = 0x5A;
    Item_80268E5C(gobj, 5, ITEM_ANIM_UPDATE);
}
bool itFreeze_UnkMotion5_Anim(Item_GObj* gobj)
{
    return false;
}

void itFreeze_UnkMotion5_Phys(Item_GObj* gobj) {}

bool itFreeze_UnkMotion5_Coll(Item_GObj* gobj)
{
    s32 unused[4];
    s32 timer;
    Item* ip = gobj->user_data;
    f32 zero;

    it_8026D62C(gobj, it_8028F1D8);

    timer = M2C_FIELD(ip, s32*, 0xDEC);
    if (timer <= 0) {
        ip = gobj->user_data;
        ip->x40_vel.x = M2C_FIELD(ip, f32*, 0xDD4);
        zero = it_804DCA70;
        ip->x40_vel.z = zero;
        ip->x40_vel.y = zero;
        it_8026B390(gobj);
        Item_80268E5C(gobj, 0, ITEM_ANIM_UPDATE);
    } else {
        M2C_FIELD(ip, s32*, 0xDEC) = timer - 1;
    }

    return false;
}
void it_3F14_Logic17_EvtUnk(Item_GObj* gobj, Item_GObj* ref_gobj)
{
    it_8026B894(gobj, ref_gobj);
}

void it_8028F8E4(Item_GObj* gobj)
{
    s32 y, x;
    Vec3 temp;
    Item* ip = gobj->user_data;
    ByteBits* bits = (ByteBits*) &M2C_FIELD(ip, u8*, 0xDCC);

    bits->b4 = 1;
    it_8026B390(gobj);

    x = *(s32*) &ip->pos.x;
    y = *(s32*) &ip->pos.y;
    *(s32*) &M2C_FIELD(ip, f32*, 0x37C) = x;
    *(s32*) &M2C_FIELD(ip, f32*, 0x380) = y;
    *(s32*) &M2C_FIELD(ip, f32*, 0x384) = *(s32*) &ip->pos.z;

    x = *(s32*) &ip->pos.x;
    y = *(s32*) &ip->pos.y;
    *(s32*) &temp.x = x;
    *(s32*) &temp.y = y;
    *(s32*) &temp.z = *(s32*) &ip->pos.z;

    it_80276100(gobj, &temp);
}
void it_8028F968(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    ByteBits* bits;

    it_80273454(gobj);
    bits = (ByteBits*) &M2C_FIELD(ip, u8*, 0xDCC);
    bits->b4 = 0;
    it_8026B3A8(gobj);
}
void it_8028F9B8(Item_GObj* gobj)
{
    Item_8026A8EC(gobj);
}
