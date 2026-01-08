#include "vi.h"

#include "vi0801.static.h"

#include "cm/camera.h"
#include "ef/efasync.h"
#include "ef/eflib.h"
#include "gm/gm_unsplit.h"
#include "gr/grbigblueroute.h"
#include "gr/ground.h"
#include "gr/stage.h"
#include "it/item.h"
#include "lb/lb_00B0.h"
#include "lb/lb_00F9.h"
#include "lb/lbarchive.h"
#include "lb/lbaudio_ax.h"
#include "mp/mpcoll.h"
#include "pl/player.h"
#include "sc/types.h"

#include <baselib/aobj.h>
#include <baselib/cobj.h>
#include <baselib/fog.h>
#include <baselib/gobj.h>
#include <baselib/gobjgxlink.h>
#include <baselib/gobjobject.h>
#include <baselib/gobjproc.h>
#include <baselib/lobj.h>

// .data section 0x804001E0 - 0x80400200
char un_804001E0[] = "ViWait0801";
char un_804001EC[] = "ViWait0801_scene";

static void un_8031ED70(HSD_GObj* gobj, int unused)
{
    NOT_IMPLEMENTED;
}

void un_8031EE60(HSD_GObj* gobj)
{
    HSD_JObjAnimAll(GET_JOBJ(gobj));
}

void un_8031EE84(void)
{
    NOT_IMPLEMENTED;
}

void fn_8031EFE4(HSD_GObj* gobj)
{
    HSD_CObj* cobj = gobj->hsd_obj;
    HSD_CObjAnim(cobj);
    if (cobj->aobj->curr_frame == 1.0F || cobj->aobj->curr_frame == 30.0F) {
        vi_8031C9B4(0xC, 0);
    }
    if (cobj->aobj->curr_frame == 60.0F) {
        vi_8031C9B4(0x10, 0);
    }
    if (cobj->aobj->curr_frame == cobj->aobj->end_frame) {
        lb_800145F4();
        gm_801A4B60();
    }
}

void un_8031F07C_OnEnter(void* unused)
{
    HSD_CObj* cobj;
    HSD_GObj* gobj;
    struct HSD_Fog* fog;
    HSD_LObj* lobj;

    lbAudioAx_800236DC();
    efLib_8005B4B8();
    efAsync_8006737C(0);
    lbAudioAx_80023F28(0x5B);
    lbAudioAx_80024E50(1);

    lbArchive_LoadSymbols(un_804001E0, &un_804D6FB8, un_804001EC, NULL);

    gobj = GObj_Create(0x13, 0x14, 0);
    cobj =
        lb_80013B14((HSD_CameraDescPerspective*) un_804D6FB8->cameras->desc);
    HSD_GObjObject_80390A70(gobj, HSD_GObj_804D784B, cobj);
    GObj_SetupGXLinkMax(gobj, (void (*)(HSD_GObj*, int)) un_8031ED70, 8);
    HSD_CObjAddAnim(cobj, un_804D6FB8->cameras->anims[0]);
    HSD_CObjReqAnim(cobj, un_804DE0C0);
    HSD_CObjAnim(cobj);
    HSD_GObjProc_8038FD54(gobj, fn_8031EFE4, 0);

    un_8031EE84();

    Camera_80028B9C(6);
    lb_8000FCDC();
    mpColl_80041C78();
    Ground_801C0378(0x40);
    Stage_802251E8(0x49, 0);
    Item_80266FA8();
    Item_80266FCC();
    Stage_8022524C();
    Stage_8022532C(0x49, 0);

    gobj = GObj_Create(0xB, 3, 0);
    fog = (struct HSD_Fog*) HSD_FogLoadDesc(un_804D6FB8->fogs->desc);
    HSD_GObjObject_80390A70(gobj, (u8) HSD_GObj_804D7848, fog);
    GObj_SetupGXLink(gobj, HSD_GObj_FogCallback, 0, 0);
    un_804D6FBC = fog->color;

    gobj = GObj_Create(0xB, 3, 0);
    lobj = lb_80011AC4(un_804D6FB8->lights);
    HSD_GObjObject_80390A70(gobj, (u8) HSD_GObj_804D784A, lobj);
    GObj_SetupGXLink(gobj, HSD_GObj_LObjCallback, 0, 0);

    grBigBlueRoute_8020DAB4(un_804A2EA8, un_804DE0D0, 0x17);

    Player_InitAllPlayers();
    lbAudioAx_80024E50(0);
}

void un_8031F274_OnFrame(void)
{
    vi_8031CAAC();
}
