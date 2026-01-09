#include "itkusudama.h"

#include <placeholder.h>
#include <platform.h>

#include "it/it_26B1.h"
#include "it/it_2725.h"
#include "it/it_266F.h"
#include "it/item.h"
#include "it/inlines.h"

extern f32 it_804DC9E4;

/// #it_802896CC

void it_3F14_Logic4_Spawned(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    ip->xDCE_flag.b7 = 0;
    ip->xDAC_itcmd_var0 = 0;
    ip->xDB0_itcmd_var1 = 0;
    ip->xDB4_itcmd_var2 = 0;
    M2C_FIELD(ip, s32*, 0xDD4) = 0;
    it_8028A3CC(gobj);
}
/// #it_802897C8

/// #it_80289910

/// #it_80289A00

/// #it_80289B50

/// #it_80289BE8

/// #it_8028A114

/// #it_8028A190

bool itKusudama_UnkMotion0_Anim(Item_GObj* gobj)
{
    it_802897C8(it_804DC9E4);
    return false;
}

void itKusudama_UnkMotion0_Phys(Item_GObj* gobj) {}

bool itKusudama_UnkMotion0_Coll(Item_GObj* gobj)
{
    it_8026D62C(gobj, it_8028A3CC);
    return false;
}

/// #itKusudama_UnkMotion1_Anim

void itKusudama_UnkMotion1_Phys(Item_GObj* gobj) {}

bool itKusudama_UnkMotion1_Coll(Item_GObj* gobj)
{
    it_8026DA08(gobj);
    return false;
}

/// #it_8028A3CC

bool itKusudama_UnkMotion2_Anim(Item_GObj* gobj)
{
    it_802897C8(it_804DC9E4);
    return false;
}

void itKusudama_UnkMotion2_Phys(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    ItemAttr* attrs = ip->xCC_item_attr;
    it_80272860(gobj, attrs->x10_fall_speed, attrs->x14_fall_speed_max);
}

bool itKusudama_UnkMotion2_Coll(Item_GObj* gobj)
{
    it_8026E15C(gobj, it_8028A190);
    return false;
}

/// #it_8028A544

/// #itKusudama_UnkMotion3_Anim

void itKusudama_UnkMotion3_Phys(Item_GObj* gobj) {}

/// #itKusudama_UnkMotion3_Coll

void it_3F14_Logic4_PickedUp(Item_GObj* gobj)
{
    Item_80268E5C((HSD_GObj*) gobj, 4, ITEM_ANIM_UPDATE);
}

bool itKusudama_UnkMotion4_Anim(Item_GObj* gobj)
{
    return false;
}

void itKusudama_UnkMotion4_Phys(Item_GObj* gobj) {}

void it_3F14_Logic4_Thrown(Item_GObj* gobj)
{
    it_8026B3A8(gobj);
    Item_80268E5C(gobj, 5, 6);
}
bool itKusudama_UnkMotion6_Anim(Item_GObj* gobj)
{
    return false;
}

void itKusudama_UnkMotion6_Phys(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    ItemAttr* attrs = ip->xCC_item_attr;
    it_80272860(gobj, attrs->x10_fall_speed, attrs->x14_fall_speed_max);
    it_80274658(gobj, it_804D6D28->x68_float);
}
/// #itKusudama_UnkMotion5_Coll

void it_3F14_Logic4_Dropped(Item_GObj* gobj)
{
    it_8026B3A8(gobj);
    Item_80268E5C(gobj, 6, 6);
}
/// #itKusudama_UnkMotion6_Coll

/// #it_8028AC74

bool itKusudama_UnkMotion7_Anim(Item_GObj* gobj)
{
    return it_802751D8(gobj);
}

void itKusudama_UnkMotion7_Phys(Item_GObj* gobj) {}

bool itKusudama_UnkMotion7_Coll(Item_GObj* gobj)
{
    return false;
}

/// #it_8028AD44

/// #itKusudama_UnkMotion8_Anim

void itKusudama_UnkMotion8_Phys(Item_GObj* gobj) {}

bool itKusudama_UnkMotion8_Coll(Item_GObj* gobj)
{
    return false;
}

bool it_3F14_Logic4_DmgDealt(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    PAD_STACK(16);
    if (M2C_FIELD(ip, s32*, 0xDD4) == 0) {
        s32* attrs = ip->xC4_article_data->x4_specialAttributes;
        if (it_8028A114(gobj, attrs[1], attrs[0], attrs[2], attrs[3]) != 0) {
            it_8028A544(gobj);
        } else {
            it_8028AC74(gobj);
        }
    }
    return false;
}
bool it_3F14_Logic4_Clanked(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    if (M2C_FIELD(ip, s32*, 0xDD4) == 0) {
        it_80289B50(gobj, 0);
    }
    return false;
}
bool it_3F14_Logic4_HitShield(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    if (M2C_FIELD(ip, s32*, 0xDD4) == 0) {
        it_80289B50(gobj, 0);
    }
    return false;
}
bool it_3F14_Logic4_Reflected(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    if (M2C_FIELD(ip, s32*, 0xDD4) == 0) {
        it_80289B50(gobj, 0);
    }
    return false;
}
bool it_3F14_Logic4_DmgReceived(Item_GObj* gobj)
{
    Item* ip = gobj->user_data;
    s32* attrs = ip->xC4_article_data->x4_specialAttributes;
    PAD_STACK(8);

    if (M2C_FIELD(ip, s32*, 0xDD4) == 0) {
        s32 dmg = ip->xC9C;
        if ((f32) (u32) (dmg ^ 0x80000000) >= ((f32*) attrs)[8]) {
            if (it_8028A114(gobj, attrs[1], attrs[0], attrs[2], attrs[3]) != 0)
            {
                it_8028A544(gobj);
            } else {
                it_8028AC74(gobj);
            }
        }
    }
    return false;
}
void it_3F14_Logic4_EvtUnk(Item_GObj* gobj, Item_GObj* ref_gobj)
{
    it_8026B894(gobj, ref_gobj);
}
