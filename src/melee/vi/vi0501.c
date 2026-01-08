#include "vi0501.h"

#include "cm/camera.h"
#include "ef/efasync.h"
#include "ef/eflib.h"
#include "ft/ftdemo.h"
#include "gm/gm_1601.h"
#include "gm/gm_1A36.h"
#include "gm/gm_1A45.h"
#include "gr/grlib.h"
#include "gr/ground.h"
#include "gr/stage.h"
#include "it/item.h"
#include "lb/lb_00B0.h"
#include "lb/lb_00F9.h"
#include "lb/lbarchive.h"
#include "lb/lbaudio_ax.h"
#include "lb/lbshadow.h"
#include "mp/mpcoll.h"
#include "pl/player.h"
#include "vi/vi.h"

#include <dolphin/gx.h>
#include <baselib/aobj.h>
#include <baselib/cobj.h>
#include <baselib/displayfunc.h>
#include <baselib/fog.h>
#include <baselib/gobjgxlink.h>
#include <baselib/gobjobject.h>
#include <baselib/gobjproc.h>
#include <baselib/jobj.h>
#include <baselib/wobj.h>

static SceneDesc* un_804D6F70;
static HSD_Archive* un_804D6F74;
static HSD_Archive* un_804D6F78;
static GXColor erase_colors_vi0501;
static float un_804D6F80;
static ViCharaDesc un_804D6F84;

static Vec3 initial_pos = { 0.0f, 0.0f, 0.0f };

void un_8031D9E4(int arg0, int arg1, int arg2)
{
    ViCharaDesc* desc;
    un_804D6F84.p1_char_index = arg0;
    desc = &un_804D6F84;
    desc->p1_costume_index = arg1;
    desc->p2_costume_index = arg2;
}

// .data section 0x804000B4 - 0x804000D0
char un_804000B4[] = "ViIntro.dat";
char un_804000C0[] = "ScVi";

void mn_8022EAE0(HSD_GObj*);

void un_8031D9F8(CharacterKind char_kind, int costume, int spawn_mode,
                 int spawn_indices)
{
    u8* indices = (u8*)spawn_indices;
    void* gr_result;
    HSD_GObj* entity;
    HSD_JObj* jobj;
    s32 i;
    f32 scale;
    Vec3 pos;
    char pad[24];

    Camera_80028B9C(6);
    lb_8000FCDC();
    mpColl_80041C78();
    Ground_801C0378(0x40);
    Stage_802251E8(0x11, 0);
    Item_80266FA8();
    Item_80266FCC();
    un_804D6F80 = Ground_801C0498();
    Ground_801C04BC(un_804DE064);
    Stage_8022524C();
    Stage_8022532C(0x11, 0);

    ftDemo_ObjAllocInit();
    Player_InitAllPlayers();

    Player_80036E20(char_kind, un_804D6F78, 3);
    Player_SetPlayerCharacter(0, char_kind);
    Player_SetCostumeId(0, costume);
    Player_SetPlayerId(0, 0);
    Player_SetSlottype(0, 2);
    Player_SetFacingDirection(0, un_804DE068);
    Player_80032768(0, &un_804000A8);
    Player_80036F34(0, 8);

    gr_result = grLib_801C9A10();
    scale = un_804DE060;

    for (i = 1; i < 4; i++) {
        Player_80036E20(4, un_804D6F74, 6);
        Player_80031DA8(indices[i - 1], spawn_mode);
        Player_SetFlagsBit1(i);
        Player_SetPlayerCharacter(i, 4);
        Player_SetCostumeId(i, spawn_mode);
        Player_SetPlayerId(i, 0);
        Player_SetSlottype(i, 2);
        Player_SetFacingDirection(i, un_804DE068);
        Player_80032768(i, &un_804000A8);
        Player_SetUnk4D(i, indices[i - 1]);
        Player_80036F34(i, i + 10);

        entity = Player_GetEntity(i);
        un_804A2E98[i - 1] = entity;

        jobj = GET_JOBJ(un_804A2E98[i - 1]);
        HSD_JObjReqAnimAll(jobj, un_804DE06C);
        HSD_JObjAnimAll(jobj);

        jobj = GET_JOBJ(un_804A2E98[i - 1]);
        HSD_ASSERT(0x69, jobj != NULL);

        pos.x = jobj->translate.x;
        pos.y = jobj->translate.y;
        pos.z = jobj->translate.z;
        pos.x = pos.x * (scale * un_804D6F80);
        pos.y = pos.y * (scale * un_804D6F80);
        pos.z = pos.z * (scale * un_804D6F80);
        ((Vec3*)((u8*)gr_result + 0xC))[i - 1].x = pos.x;
        ((Vec3*)((u8*)gr_result + 0xC))[i - 1].y = pos.y;
        ((Vec3*)((u8*)gr_result + 0xC))[i - 1].z = pos.z;

        HSD_JObjReqAnimAll(jobj, un_804DE070);
    }

    lbAudioAx_80026F2C(0x1C);
    lbAudioAx_8002702C(0xC, 0x80004000ULL);
    lbAudioAx_80027168();
    lbAudioAx_80027648();
}
void vi_8031DC80(HSD_GObj* gobj, int unused)
{
    PAD_STACK(8);
    lbShadow_8000F38C(0);
    vi_RunCamera(gobj, (u8*) &erase_colors_vi0501, 0x281);
}

void fn_8031DD14(HSD_GObj* gobj)
{
    HSD_CObj* cobj = GET_COBJ(gobj);
    f32 frame;

    HSD_CObjAnim(cobj);
    frame = cobj->aobj->curr_frame;

    if (60.0f == frame || 70.0f == frame || 85.0f == frame) {
        vi_8031C9B4(0xC, 0);
        lbAudioAx_800237A8(0x222F9, 0x7F, 0x40);

        if (60.0f == cobj->aobj->curr_frame) {
            lbAudioAx_800237A8(0x73, 0x7F, 0x40);
        }
        if (70.0f == cobj->aobj->curr_frame) {
            lbAudioAx_800237A8(0x74, 0x7F, 0x40);
        }
        if (85.0f == cobj->aobj->curr_frame) {
            lbAudioAx_800237A8(0x73, 0x7F, 0x40);
        }
    }

    frame = cobj->aobj->curr_frame;
    if (98.0f == frame || 108.0f == frame || 123.0f == frame) {
        lbAudioAx_800237A8(0x22308, 0x7F, 0x40);
    }

    if (cobj->aobj->curr_frame == cobj->aobj->end_frame) {
        lb_800145F4();
        gm_801A4B60();
    }
}
void un_8031DE58_OnEnter(void* arg)
{
    u8* input = arg;
    u8 char_index;
    HSD_Fog* fog;
    HSD_GObj* fog_gobj;
    HSD_LObj* lobj;
    HSD_GObj* light_gobj;
    HSD_CObj* cobj;
    HSD_GObj* camera_gobj;
    HSD_JObj* jobj;
    HSD_GObj* model_gobj;
    s32 i;

    lbAudioAx_800236DC();
    efLib_8005B4B8();
    efAsync_8006737C(0);

    char_index = input[0];

    un_804D6F74 =
        lbArchive_LoadSymbols(un_804000B4, &un_804D6F70, un_804000C0, NULL);
    un_804D6F78 = lbArchive_LoadSymbols(viGetCharAnimByIndex(char_index), NULL);

    fog_gobj = GObj_Create(0xb, 3, 0);
    fog = HSD_FogLoadDesc(un_804D6F70->fogs->desc);
    HSD_GObjObject_80390A70(fog_gobj, HSD_GObj_804D7848, fog);
    GObj_SetupGXLink(fog_gobj, HSD_GObj_FogCallback, 0, 0);
    erase_colors_vi0501 = fog->color;

    light_gobj = GObj_Create(0xb, 3, 0);
    lobj = lb_80011AC4(un_804D6F70->lights);
    HSD_GObjObject_80390A70(light_gobj, HSD_GObj_804D784A, lobj);
    GObj_SetupGXLink(light_gobj, HSD_GObj_LObjCallback, 0, 0);

    camera_gobj = GObj_Create(0x13, 0x14, 0);
    cobj = lb_80013B14((HSD_CameraDescPerspective*) un_804D6F70->cameras->desc);
    HSD_GObjObject_80390A70(camera_gobj, HSD_GObj_804D784B, cobj);
    GObj_SetupGXLinkMax(camera_gobj, vi_8031DC80, 5);
    HSD_CObjAddAnim(cobj, un_804D6F70->cameras->anims[0]);
    HSD_CObjReqAnim(cobj, un_804DE070);
    HSD_CObjAnim(cobj);
    HSD_GObjProc_8038FD54(camera_gobj, fn_8031DD14, 0);

    for (i = 0; un_804D6F70->models[i] != NULL; i++) {
        model_gobj = GObj_Create(0xe, 0xf, 0);
        jobj = HSD_JObjLoadJoint(un_804D6F70->models[i]->joint);
        HSD_GObjObject_80390A70(model_gobj, HSD_GObj_804D7849, jobj);
        GObj_SetupGXLink(model_gobj, HSD_GObj_JObjCallback, 9, 0);
        gm_8016895C(jobj, un_804D6F70->models[i], 0);
        HSD_JObjReqAnimAll(jobj, un_804DE070);
        HSD_JObjAnimAll(jobj);
        HSD_GObjProc_8038FD54(model_gobj, mn_8022EAE0, 0x17);
    }

    un_8031D9F8(input[0], input[1], input[3], (int)&input[4]);
    lbAudioAx_800237A8(0x20b, 0x7f, 0x40);
    lbAudioAx_800237A8(0x20c, 0x7f, 0x40);
}

void vi_8031E0F0_OnFrame(void)
{
    vi_8031CAAC();
}
