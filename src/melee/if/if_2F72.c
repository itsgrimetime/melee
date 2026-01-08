#include "if_2F72.h"

#include "gm/gm_1601.h"
#include "gm/gm_16AE.h"
#include "if/ifall.h"
#include "if/ifstatus.h"
#include "if/types.h"
#include "lb/lb_00B0.h"
#include "lb/lbarchive.h"
#include "lb/lbaudio_ax.h"
#include "pl/player.h"

#include <baselib/debug.h>
#include <baselib/gobj.h>
#include <baselib/gobjproc.h>
#include <baselib/gobjplink.h>
#include <baselib/gobjproc.h>
#include <baselib/jobj.h>

// Orphaned data strings from original ROM
static char lbl_803F9780[] = "ScInfStc_scene_models";
static char lbl_803F9798[] = "translate";

static void* lbl_804A1340[13];

void if_802F7BB4(s32 player_idx)
{
    void** base;
    u8 idx;
    s32 offset;
    void** entry;

    base = lbl_804A1340;
    idx = (u8)player_idx;
    offset = idx << 1;
    entry = base + offset;
    (base + offset)[1] = fn_802F77F8(*++entry, idx, 1);
    if ((base + offset)[1] != NULL) {
        HSD_GObjProc_8038FD54(*entry, (HSD_GObjEvent)fn_802F75D4, 0x11);
    }
}

void if_802F7E24(void)
{
    memzero(lbl_804A1340, 0x34);
    lbArchive_LoadSections(*ifAll_802F3690(), lbl_804A1340, lbl_803F9780, 0);
}

void if_802F7E7C(void)
{
    HSD_GObj** data = (HSD_GObj**) lbl_804A1340;
    s32 i = 0;
    HSD_GObj** base = (HSD_GObj**) lbl_804A1340;

    do {
        if (data[1] != NULL) {
            HSD_GObjPLink_80390228(data[1]);
        }
        if (data[2] != NULL) {
            HSD_GObjPLink_80390228(data[2]);
        }
        i++;
        data += 2;
    } while (i < 6);
    memzero(base, 0x34);
}
