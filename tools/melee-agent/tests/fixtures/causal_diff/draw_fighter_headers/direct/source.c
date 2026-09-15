static inline HSD_JObj* mnDiagram_CreateFighterHeader(
    int fighter_id, mnDiagram_Assets* assets)
{
    HSD_JObj* child;
    void** joint_data = assets->FaceB;
    HSD_JObj* jobj;

    jobj = HSD_JObjLoadJoint(joint_data[0]);
    HSD_JObjAddAnimAll(jobj, joint_data[1], joint_data[2], joint_data[3]);
    HSD_JObjReqAnimAll(jobj, mnDiagram_804DBF84);
    HSD_JObjAnimAll(jobj);
    lb_80011E24(jobj, &child, 2, -1);
    HSD_JObjReqAnimAll(child, (f32) (fighter_id & 0xFF));
    HSD_JObjAnimAll(child);
    return jobj;
}

void mnDiagram_DrawFighterHeaders(void* arg0, int arg1, int arg2)
{
    int fighter_id;
    HSD_JObj* header;
    Diagram* data = GET_DIAGRAM(arg0);
    Diagram* data_alias = data;
    mnDiagram_Assets* assets = (mnDiagram_Assets*) &mnDiagram_804A0750;
    u8* sorted;
    f32 spacing;
    int i;
    HSD_JObj* parent;

    // Column headers (fighter icons)
    for (i = 0; i < 7; i++) {
        sorted = (u8*) assets;
        if (mnDiagram_CountUnlockedFightersInline() > i) {
            header = mnDiagram_CreateFighterHeader(
                (fighter_id = mnDiagram_GetVisibleFighterCursorFrom(
                     sorted, arg2, i),
                 fighter_id),
                assets);
            spacing = HSD_JObjGetTranslationX(data->jobjs[8]) -
                      HSD_JObjGetTranslationX(data->jobjs[7]);
            HSD_JObjSetTranslateX(header, spacing * i);
            parent = data->jobjs[7];
            HSD_JObjAddChild(parent, header);
        }
    }

    // Row headers (fighter icons)
    for (i = 0; i < 0xA; i++) {
        sorted = (u8*) assets;
        if (mnDiagram_CountUnlockedFightersInline() > i) {
            header = mnDiagram_CreateFighterHeader(
                mnDiagram_GetVisibleFighterCursorFrom2(sorted, arg1, i),
                assets);
            parent = data_alias->jobjs[9];
            spacing = HSD_JObjGetTranslationY(data_alias->jobjs[10]) -
                      HSD_JObjGetTranslationY(parent);
            HSD_JObjSetTranslateY(header, spacing * i);
            HSD_JObjAddChild(data_alias->jobjs[9], header);
        }
    }
}
