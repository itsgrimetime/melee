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


def test_non_static_decl_is_static_false(tmp_path):
    p = tmp_path / "global.c"
    p.write_text("int global_counter = 0;\nstatic int hidden = 1;\n")
    decls = map_decls(p)
    assert decls["global_counter"].is_static is False
    assert decls["global_counter"].line == 1
    assert decls["hidden"].is_static is True


def test_robustness_never_raises(tmp_path):
    p = tmp_path / "unbalanced.c"
    p.write_text("int x = 0;\n}\n}\n*&^%$ = ;\n")
    result = map_decls(p)
    assert isinstance(result, dict)
    assert result["x"].line == 1

    p2 = tmp_path / "nonascii.c"
    p2.write_bytes(b"static int y = 0; // caf\xe9\n")
    result2 = map_decls(p2)
    assert isinstance(result2, dict)
    assert result2["y"].is_static is True

    p3 = tmp_path / "empty.c"
    p3.write_text("")
    assert map_decls(p3) == {}
