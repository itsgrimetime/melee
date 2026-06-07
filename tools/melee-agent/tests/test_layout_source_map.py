from src.layout.source_map import map_decls

SRC = '''\
#include "x.h"
static AnimLoopSettings mnEvent_803EF758 = { 0, 199.0f, 0 };
static Vec3 mnEvent_803EF764 = { -3.8f, -0.6f, 0 };
static char mnEvent_803EF788[0xC] = "translate";
void fn_8024D15C(void) { mnEvent_803EF764.x = 1.0f; }
'''


def test_maps_symbol_names_to_decl_lines(tmp_path):
    p = tmp_path / "mnevent.c"
    p.write_text(SRC)
    decls = map_decls(p)
    assert decls["mnEvent_803EF758"].line == 2
    assert decls["mnEvent_803EF788"].line == 4
    assert decls["mnEvent_803EF788"].is_static is True
    assert "fn_8024D15C" not in decls  # used, not file-scope declared
