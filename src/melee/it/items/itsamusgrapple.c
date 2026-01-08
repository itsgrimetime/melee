#include "itsamusgrapple.h"

#include "itlinkhookshot.h"

#include "ft/ftcoll.h"
#include "ft/inlines.h"
#include "it/inlines.h"
#include "it/item.h"

#include <baselib/gobjplink.h>

void it_2725_Logic53_Spawned(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = NULL;
}

/// #it_802B7160

/// #it_802B743C

/// #it_802B75FC

typedef struct itSamusGrapple_Node {
    /* +0x00 */ void* pad0;
    /* +0x04 */ struct itSamusGrapple_Node* next;
    /* +0x08 */ char pad8[0x1C8];
    /* +0x1D0 */ HSD_GObj* gobj;
} itSamusGrapple_Node;

typedef struct itSamusGrapple_Segment {
    /* +0x00 */ struct itSamusGrapple_Segment* next;
    /* +0x04 */ char pad4[0x10];
    /* +0x14 */ Vec3 pos;
    /* +0x20 */ char pad20[0xC];
    /* +0x2C */ u8 flags;
} itSamusGrapple_Segment;

typedef struct itSamusGrapple_Attr {
    /* +0x00 */ char pad0[0x38];
    /* +0x38 */ f32 max_length;
} itSamusGrapple_Attr;

void it_802B7B84(Item_GObj* gobj)
{
    itSamusGrapple_Node* node;
    Fighter* fp;
    Item* ip;
    HSD_GObj* fighter_gobj;
    PAD_STACK(8);

    if (gobj == NULL) {
        return;
    }

    ip = gobj->user_data;
    if (ip == NULL) {
        return;
    }

    fighter_gobj = M2C_FIELD(ip, HSD_GObj**, 0xDDC);
    if (fighter_gobj == NULL) {
        return;
    }

    fp = fighter_gobj->user_data;
    if (fp == NULL) {
        return;
    }

    M2C_FIELD(ip, void**, 0xDE4) = NULL;
    fp->fv.ss.x223C = NULL;
    fp->accessory2_cb = NULL;
    fp->death1_cb = NULL;
    fp->accessory3_cb = NULL;

    for (node = M2C_FIELD(ip, itSamusGrapple_Node**, 0xDD4); node != NULL;) {
        HSD_GObj* to_plink = node->gobj;
        node = node->next;
        HSD_GObjPLink_80390228(to_plink);
    }

    Item_8026A8EC(gobj);
}

/// #it_802B7C18

/// #fn_802B7E34

void itSamusgrapple_UnkMotion0_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B7E34;
}

/// #fn_802B805C

void itSamusgrapple_UnkMotion1_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B805C;
}

/// #fn_802B8384

void itSamusgrapple_UnkMotion2_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B8384;
}

/// #fn_802B8524

void itSamusgrapple_UnkMotion3_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B8524;
}

/// #fn_802B8684

void itSamusgrapple_UnkMotion4_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B8684;
}

/// #fn_802B8814

void itSamusgrapple_UnkMotion5_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B8814;
}

/// #fn_802B895C

void itSamusgrapple_UnkMotion6_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B895C;
}

/// #fn_802B8B54

void itSamusgrapple_UnkMotion7_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B8B54;
}

/// #fn_802B8D38

void itSamusgrapple_UnkMotion8_Phys(Item_GObj* gobj)
{
    GET_ITEM(gobj)->xDD4_itemVar.samusgrapple.unk_10 = fn_802B8D38;
}

/// #it_802B900C

/// #it_802B91C4

/// #it_802B9328

/// #it_802B99A0

/// #it_802B9CE8

/// #it_802B9FD4

/// #it_802BA194

bool it_802BA2D8(void* list_ptr, Vec3* pos, void* attr_ptr, float length)
{
    itSamusGrapple_Segment* current;
    itSamusGrapple_Segment* next;
    Vec3 sp18;
    s32 flag;
    itSamusGrapple_Attr* attr = attr_ptr;
    f32 dist;

    current = list_ptr;
    next = *(itSamusGrapple_Segment**) list_ptr;

    while (next != NULL && !((current->flags >> 7) & 1)) {
        current = next;
        next = next->next;
    }

    dist = it_802A3C98(&current->pos, pos, &sp18);

    flag = 0;
    while (next != NULL && length > dist) {
        current->flags = (u8) ((current->flags & ~0x80) | (flag << 7));
        dist = it_802A3C98(&next->pos, pos, &sp18);
        current = next;
        next = next->next;
    }

    dist = dist - length;
    if (dist > attr->max_length) {
        dist = attr->max_length;
    }

    it_802B900C(current, pos, attr, dist);

    return next == NULL;
}

/// #it_802BA3BC

/// #it_802BA5DC

/// #it_802BA760

void it_2725_Logic53_PickedUp(Item_GObj* gobj)
{
    PAD_STACK(16);
    Item_80268E5C((HSD_GObj*) gobj, 0, ITEM_ANIM_UPDATE);
    it_802A2428(gobj);
}

void it_802BA9B8(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    PAD_STACK(8);
    Item_80268E5C((HSD_GObj*) gobj, 3, ITEM_ANIM_UPDATE);
    ftColl_8007AFF8(ip->xDD4_itemVar.samusgrapple.x8);
    it_802A2428(gobj);
}

void it_802BAA08(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    PAD_STACK(8);
    Item_80268E5C((HSD_GObj*) gobj, 2, ITEM_ANIM_UPDATE);
    ftColl_8007AFF8(ip->xDD4_itemVar.samusgrapple.x8);
    it_802A2428(gobj);
}

void it_802BAA58(Item_GObj* gobj)
{
    PAD_STACK(16);
    Item_80268E5C((HSD_GObj*) gobj, 4, ITEM_ANIM_UPDATE);
    it_802A2428(gobj);
}

void it_802BAA94(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    PAD_STACK(8);
    Item_80268E5C((HSD_GObj*) gobj, 5, ITEM_ANIM_UPDATE);
    ftColl_8007AFF8(ip->xDD4_itemVar.samusgrapple.x8);
    it_802A2428(gobj);
}

void it_802BAAE4(HSD_GObj* gobj, Vec3* pos, float facing_dir)
{
    Item* ip = GET_ITEM(gobj);
    ip->xDD4_itemVar.samusgrapple.x0->pos = *pos;
    Item_80268E5C(gobj, 1, ITEM_ANIM_UPDATE);
    it_802A2428((Item_GObj*) gobj);
}

void it_802BAB40(Item_GObj* gobj)
{
    PAD_STACK(16);
    Item_80268E5C((HSD_GObj*) gobj, 6, ITEM_ANIM_UPDATE);
    it_802A2428(gobj);
}
void it_802BAB7C(Item_GObj* gobj)
{
    PAD_STACK(16);
    Item_80268E5C((HSD_GObj*) gobj, 7, ITEM_ANIM_UPDATE);
    it_802A2428(gobj);
}
void it_802BABB8(Item_GObj* gobj)
{
    Item* ip = GET_ITEM(gobj);
    Fighter* fp = ip->owner->user_data;
    ftData* ft_data = fp->ft_data;
    void* ext_attr = ft_data->ext_attr;
    PAD_STACK(16);

    Item_80268E5C((HSD_GObj*) gobj, 8, ITEM_ANIM_UPDATE);
    it_802A2428(gobj);

    M2C_FIELD(fp, float*, 0x2344) = (f32) M2C_FIELD(ext_attr, s32*, 0xD0);
}

void it_802BAC3C(Fighter_GObj* gobj)
{
    Fighter* fp = gobj->user_data;
    if (fp->fv.ss.x223C != NULL) {
        it_802B7B84(fp->fv.ss.x223C);
    } else {
        fp->accessory2_cb = NULL;
        fp->death1_cb = NULL;
        fp->accessory3_cb = NULL;
    }
}

void it_802BAC80(Fighter_GObj* gobj)
{
    Fighter* fp = gobj->user_data;
    Item_GObj* item;

    if ((item = fp->fv.ss.x223C) != NULL) {
        Item* ip = item->user_data;
        if (ip->xDD4_itemVar.samusgrapple.unk_10 != NULL) {
            ip->xDD4_itemVar.samusgrapple.unk_10(item);
        }
    }
}

/// #it_802BACC4

void it_2725_Logic53_EvtUnk(Item_GObj* gobj, Item_GObj* other)
{
    Item* ip = GET_ITEM(gobj);
    it_8026B894(gobj, other);
    if (ip->xDD4_itemVar.samusgrapple.x8 == (HSD_GObj*) other) {
        ip->xDD4_itemVar.samusgrapple.x8 = NULL;
    }
}
