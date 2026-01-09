#include "itklap.h"

#include "it/it_26B1.h"
#include "it/item.h"

typedef struct {
    u8 b567 : 3;
    u8 b4 : 1;
    u8 b0123 : 4;
} ByteBits;

/// #it_802E1820

/// #it_2725_Logic10_Destroyed

/// #it_802E18B4

void it_802E1930(Item_GObj* gobj)
{
    f32 zero = it_804DD6E8;
    Item* ip = M2C_FIELD(gobj, Item**, 0x2C);
    M2C_FIELD(ip, f32*, 0x44) = zero;
    M2C_FIELD(ip, f32*, 0x40) = zero;
    Item_80268E5C(gobj, 0, 2);
}
bool itKlap_UnkMotion1_Anim(Item_GObj* gobj)
{
    return false;
}

/// #itKlap_UnkMotion1_Phys

/// #itKlap_UnkMotion1_Coll

void it_802E1C4C(Item_GObj* gobj)
{
    f32 zero = it_804DD6E8;
    Item* ip = M2C_FIELD(gobj, Item**, 0x2C);
    M2C_FIELD(ip, f32*, 0x44) = zero;
    M2C_FIELD(ip, f32*, 0x40) = zero;
    Item_80268E5C(gobj, 1, ITEM_ANIM_UPDATE);
}
/// #it_802E1C84

bool itKlap_UnkMotion2_Anim(Item_GObj* gobj)
{
    return false;
}

/// #itKlap_UnkMotion2_Phys

bool itKlap_UnkMotion2_Coll(Item_GObj* gobj)
{
    return false;
}

bool it_2725_Logic10_DmgReceived(Item_GObj* gobj)
{
    Item* ip = M2C_FIELD(gobj, Item**, 0x2C);
    ByteBits* bits = (ByteBits*) &M2C_FIELD(ip, u8*, 0xDCC);
    bits->b4 = 1;
    it_802E1E94(gobj);
    return false;
}
/// #it_802E1E94

bool itKlap_UnkMotion4_Anim(Item_GObj* gobj)
{
    return false;
}

/// #itKlap_UnkMotion4_Phys

bool itKlap_UnkMotion4_Coll(Item_GObj* gobj)
{
    return false;
}

/// #it_802E20D8

bool itKlap_UnkMotion3_Anim(Item_GObj* gobj)
{
    return false;
}

void itKlap_UnkMotion3_Phys(Item_GObj* gobj) {}

bool itKlap_UnkMotion3_Coll(Item_GObj* gobj)
{
    return false;
}

/// #it_802E215C

/// #it_802E2330

void it_802E2450(Item_GObj* gobj, Item_GObj* ref_gobj)
{
    it_8026B894(gobj, ref_gobj);
}
