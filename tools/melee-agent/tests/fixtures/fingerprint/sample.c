/* Self-contained test fixture: no #include so tools (clang, tree-sitter)
   don't need a system header search path. Tree-sitter-c parses this
   structurally; the typedefs make the body realistic. */
typedef unsigned int u32;
typedef unsigned char u8;

#pragma auto_inline off

void fn_alpha(u32 arg0) {
    u32 buttons;
    u8 sel;
    int i;

    buttons = arg0;
    for (i = 0; i < 10; i++) {
        sel = (u8) i;
        buttons |= sel;
    }
}

/* fn_beta has the same body shape as fn_alpha but a different name */
void fn_beta(u32 arg0) {
    u32 buttons;
    u8 sel;
    int i;

    buttons = arg0;
    for (i = 0; i < 10; i++) {
        sel = (u8) i;
        buttons |= sel;
    }
}

/* fn_gamma uses a function-pointer return type to exercise tree-sitter
   on a tricky declarator. */
int (*fn_gamma(void))(int) {
    return 0;
}

#pragma auto_inline reset
