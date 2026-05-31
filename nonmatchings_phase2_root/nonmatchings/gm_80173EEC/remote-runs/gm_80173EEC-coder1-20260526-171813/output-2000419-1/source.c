
typedef int bool;
typedef signed char s8;
typedef unsigned char u8;
typedef signed short int s16;
typedef unsigned short int u16;
typedef signed long s32;
typedef unsigned long u32;
typedef signed long long int s64;
typedef unsigned long long int u64;
typedef float f32;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wtypedef-redefinition"
#pragma clang diagnostic pop
typedef u32 MotionFlags;
typedef enum CharacterKind
{
  CKIND_CAPTAIN,
  CKIND_DONKEY,
  CKIND_FOX,
  CKIND_GAMEWATCH,
  CKIND_KIRBY,
  CKIND_KOOPA,
  CKIND_LINK,
  CKIND_LUIGI,
  CKIND_MARIO,
  CKIND_MARS,
  CKIND_MEWTWO,
  CKIND_NESS,
  CKIND_PEACH,
  CKIND_PIKACHU,
  CKIND_POPONANA,
  CKIND_PURIN,
  CKIND_SAMUS,
  CKIND_YOSHI,
  CKIND_ZELDA,
  CKIND_SEAK,
  CKIND_FALCO,
  CKIND_CLINK,
  CKIND_DRMARIO,
  CKIND_EMBLEM,
  CKIND_PICHU,
  CKIND_GANON,
  CKIND_PLAYABLE_COUNT,
  CKIND_MASTERH = CKIND_PLAYABLE_COUNT,
  CKIND_BOY,
  CKIND_GIRL,
  CKIND_GKOOPS,
  CKIND_CREZYH,
  CHKIND_SANDBAG,
  CHKIND_POPO,
  CHKIND_NONE,
  CHKIND_MAX = CHKIND_NONE
} CharacterKind;
static const MotionFlags Ft_MF_None = 0;
static const MotionFlags Ft_MF_KeepFastFall = 1 << 0;
static const MotionFlags Ft_MF_KeepGfx = 1 << 1;
static const MotionFlags Ft_MF_KeepColAnimHitStatus = 1 << 2;
static const MotionFlags Ft_MF_SkipHit = 1 << 3;
static const MotionFlags Ft_MF_SkipModel = 1 << 4;
static const MotionFlags Ft_MF_SkipAnimVel = 1 << 5;
static const MotionFlags Ft_MF_Unk06 = 1 << 6;
static const MotionFlags Ft_MF_SkipMatAnim = 1 << 7;
static const MotionFlags Ft_MF_SkipThrowException = 1 << 8;
static const MotionFlags Ft_MF_KeepSfx = 1 << 9;
static const MotionFlags Ft_MF_SkipParasol = 1 << 10;
static const MotionFlags Ft_MF_SkipRumble = 1 << 11;
static const MotionFlags Ft_MF_SkipColAnim = 1 << 12;
static const MotionFlags Ft_MF_KeepAccessory = 1 << 13;
static const MotionFlags Ft_MF_UpdateCmd = 1 << 14;
static const MotionFlags Ft_MF_SkipNametagVis = 1 << 15;
static const MotionFlags Ft_MF_KeepColAnimPartHitStatus = 1 << 16;
static const MotionFlags Ft_MF_KeepSwordTrail = 1 << 17;
static const MotionFlags Ft_MF_SkipItemVis = 1 << 18;
static const MotionFlags Ft_MF_Unk19 = 1 << 19;
static const MotionFlags Ft_MF_UnkUpdatePhys = 1 << 20;
static const MotionFlags Ft_MF_FreezeState = 1 << 21;
static const MotionFlags Ft_MF_SkipModelPartVis = 1 << 22;
static const MotionFlags Ft_MF_SkipMetalB = 1 << 23;
static const MotionFlags Ft_MF_Unk24 = 1 << 24;
static const MotionFlags Ft_MF_SkipAttackCount = 1 << 25;
static const MotionFlags Ft_MF_SkipModelFlags = 1 << 26;
static const MotionFlags Ft_MF_Unk27 = 1 << 27;
static const MotionFlags Ft_MF_SkipHitStun = 1 << 28;
static const MotionFlags Ft_MF_SkipAnim = 1 << 29;
static const MotionFlags Ft_MF_Unk30 = 1 << 30;
static const MotionFlags Ft_MF_Unk31 = 1 << 31;
typedef enum MajorSceneKind
{
  MJ_TITLE,
  MJ_MENU,
  MJ_VS,
  MJ_CLASSIC,
  MJ_ADVENTURE,
  MJ_ALLSTAR,
  MJ_DEBUG,
  MJ_DEBUG_SOUND_TEST,
  MJ_HANYU_CSS,
  MJ_HANYU_SSS,
  MJ_CAMERA_MODE,
  MJ_TOY_GALLERY,
  MJ_TOY_LOTTERY,
  MJ_TOY_COLLECTION,
  MJ_DEBUG_VS,
  MJ_TARGET_TEST,
  MJ_SUPER_SUDDEN_DEATH_VS,
  MJ_INVISIBLE_VS,
  MJ_SLOMO_VS,
  MJ_LIGHTNING_VS,
  MJ_CHALLENGER_APPROACH,
  MJ_CLASSIC_GOVER,
  MJ_ADVENTURE_GOVER,
  MJ_ALLSTAR_GOVER,
  MJ_OPENING_MV,
  MJ_DEBUG_CUTSCENE,
  MJ_DEBUG_GOVER,
  MJ_TOURNAMENT,
  MJ_TRAINING,
  MJ_TINY_VS,
  MJ_GIANT_VS,
  MJ_STAMINA_VS,
  MJ_HOME_RUN_CONTEST,
  MJ_10MAN_VS,
  MJ_100MAN_VS,
  MJ_3MIN_VS,
  MJ_15MIN_VS,
  MJ_ENDLESS_VS,
  MJ_CRUEL_VS,
  MJ_PROGRESSIVE_SCAN,
  MJ_BOOT,
  MJ_MEMCARD,
  MJ_FIXED_CAMERA_VS,
  MJ_EVENT,
  MJ_SINGLE_BUTTON_VS,
  MJ_COUNT
} MajorSceneKind;
bool fn_801722BC(void);
bool fn_801722F4(void);
bool fn_8017232C(void);
bool fn_80172380(void);
bool fn_801723D4(void);
bool fn_80172428(void);
bool fn_80172478(void);
bool fn_801724C8(void);
bool fn_801724D0(void);
bool fn_80172504(void);
bool fn_80172538(void);
bool fn_8017256C(void);
bool fn_801725A8(void);
bool fn_801725E4(void);
bool fn_80172624(void);
bool fn_80172664(void);
bool fn_80172698(void);
bool fn_801726CC(void);
bool fn_80172700(void);
bool fn_80172734(void);
bool fn_80172768(void);
bool fn_80172C78(int);
bool fn_80173510(void);
bool fn_801735F0(void);
bool fn_80173644(void);
bool fn_8017367C(void);
void gm_80173EEC(void);
typedef union UnkFlagStruct
{
  u8 u8;
  struct 
  {
    u8 b0 : 1;
    u8 b1 : 1;
    u8 b2 : 1;
    u8 b3 : 1;
    u8 b4 : 1;
    u8 b5 : 1;
    u8 b6 : 1;
    u8 b7 : 1;
  };
} UnkFlagStruct;
struct gmm_x1CB0
{
  u8 item_freq;
  u8 pad_x1[0x8 - 0x1];
  u64 item_mask;
  u8 rumble[4];
  u8 sound_balance;
  u8 deflicker;
  u8 saved_language;
  u32 stage_mask;
  u8 padding_x16[0x1];
};
struct FighterData
{
  u16 fighter_kos[25];
  u8 padding_0x32[2];
  u16 sd_count;
  u8 padding_0x36[2];
  u32 attacks_hit;
  u32 attacks_total;
  s32 damage_dealt;
  s32 damage_taken;
  s32 damage_recovered;
  u16 peak_damage;
  u16 match_count;
  u16 victories;
  u16 losses;
  u32 play_time;
  u32 total_player_count;
  s32 walk_distance;
  s32 run_distance;
  s32 fall_distance;
  s32 peak_height;
  s32 coins_collected;
  s32 coins_swiped;
  s32 coins_lost;
  s8 x78;
  s8 x79;
  UnkFlagStruct x7A;
  s8 x7B;
  struct 
  {
    u16 b0 : 1;
    u16 b1 : 1;
    u16 b2 : 1;
    u16 b3 : 1;
    u16 b4 : 1;
    u16 b5 : 1;
    u16 b6 : 1;
    u16 b789 : 3;
    u16 b10_to_12 : 3;
    u16 b13_to_15 : 3;
    u16 x7E;
    u8 x80;
    u8 x81;
    u8 x82;
    s8 x83;
    s32 x84;
    s32 x88;
    s32 x8C;
    s32 x90;
    u32 x94;
    s32 x98;
    s32 x9C;
    u16 xA0;
    u16 xA2;
    s32 xA4;
    s32 xA8;
  } x7C;
};
struct NameTagData
{
  u16 vs_kos[120];
  u16 sd_count;
  u8 padding_0xF2[2];
  u32 attacks_hit;
  u32 attacks_total;
  s32 damage_dealt;
  s32 damage_taken;
  s32 damage_recovered;
  u16 peak_damage;
  u16 match_count;
  u16 victories;
  u16 losses;
  u32 play_time;
  u32 total_player_count;
  s32 walk_distance;
  s32 run_distance;
  s32 fall_distance;
  s32 peak_height;
  s32 coins_collected;
  s32 coins_swiped;
  s32 coins_lost;
  u32 play_time_by_fighter[25];
  char namedata[8];
  s8 x1A0;
  u8 x1A1;
  s8 x1A2;
  u8 padding_x1A2;
};
struct NameTagDataBank
{
  struct NameTagData inner[19];
};
struct gmm_retval_ED98
{
  u32 x0;
  u32 x4;
  u8 padding[0x4];
  s32 xC;
  s32 x10;
  s32 x14;
  s32 x18;
  s32 x1C;
};
struct gmm_retval_EDB0
{
  s32 x0;
  s32 x4;
};
struct gmm_retval_EDBC
{
  s32 x0;
  u32 x4;
  s32 x8;
  u32 xC;
  int x10;
  u32 x14;
  u16 x18[2];
  u8 pad_x1C[0x4C - 0x1C];
  s32 x4C[4];
  u8 padding_x4C[(0xB0 - 0x4C) - (4 * 4)];
  s32 xB0[0x19];
  int x114[0x19];
};
struct gmm_x1868
{
  u16 x1868;
  u16 x186A;
  u8 x186C;
  char pad_5[3];
  struct gmm_retval_ED98 unk_8;
  struct gmm_retval_EDB0 unk_28;
  struct gmm_retval_EDBC unk_30;
  struct gmm_x1868_1A8_t
  {
    u32 x0;
    u8 x4;
    u8 x5;
    u8 x6;
  } unk_1A8;
  s32 x1A18;
  s32 x1A1C;
  s32 x1A20;
  s32 x1A24;
  s32 x1A28;
  s32 x1A2C;
  s32 x1A30;
  s32 x1A34;
  s32 x1A38;
  s32 x1A3C;
  s32 x1A40;
  s32 x1A44;
  u32 x1A48;
  s32 x1A4C;
  s32 x1A50;
  int x1A54;
  s32 x1A58;
  s32 x1A5C;
  s32 x1A60;
  s32 x1A64;
  s64 x1A68;
  s32 x1A70[4];
  u8 padding_x1A70[0xBC];
  u8 x1B3C;
  char pad_2D5[3];
  u32 x1B40[3];
  u32 x1B4C[3];
  u32 x1B58[3];
  u8 padding_x1B58[0x1C];
  u32 x1B80[4];
  u8 padding_x1B80[0xF8];
  u32 x1C88[3];
  u8 padding_x1C88[0x1C];
  struct gmm_x1CB0 x1CB0;
  s16 x1CD0;
  s16 x1CD2;
  s32 x1CD4;
  u8 padding_x1CD4[0x254];
  struct FighterData x1F2C[0x19];
  struct NameTagDataBank x2FF8[2];
};
static int lbl_803D5648[] = {0x000003E8, 0xFFFFFC18, 0x000007D0, 0xFFFFFA24, 0x00000BB8, 0x000005DC, 0x000007D0, 0x000003E8, 0xFFFFFC18, 0xFFFFFE0C, 0xFFFFF830, 0xFFFFFC18, 0x000001F4, 0xFFFFFE0C, 0xFFFFFE0C, 0x00000FA0, 0x000009C4, 0x000005DC, 0x000007D0, 0x000009C4, 0x00001388, 0x00000320, 0x00000BB8, 0x00001F40, 0xFFFFFE0C, 0x000007D0, 0x00000FA0, 0x00000FA0, 0x00002710, 0x00001770, 0x00000FA0, 0x00002710, 0x00004E20, 0x00001B58, 0x00000DAC, 0x00000BB8, 0x00000DAC, 0x000005DC, 0x00000898, 0x00000C1C, 0x00000708, 0x000001F4, 0x000003E8, 0x00000BB8, 0x00001B58, 0x00002710, 0x00003A98, 0x00004E20, 0x000007D0, 0x000007D0, 0x00002710, 0x00001770, 0xFFFFFE0C, 0xFFFFFA24, 0x000007D0, 0x00000DAC, 0x0000012C, 0x000009C4, 0x000005DC, 0x000009C4, 0x000007D0, 0xFFFFFC18, 0xFFFFF63C, 0x000001F4, 0x00001388, 0x0000012C, 0x00001964, 0x000009C4, 0x000003E8, 0x000007D0, 0x000005DC, 0x000009C4, 0x00000BB8, 0x00000FA0, 0x00000320, 0x000007D0, 0x00001388, 0x000009C4, 0xFFFFFC18, 0xFFFFF830, 0x000001F4, 0x000003E8, 0x00000320, 0x000003E8, 0x00000320, 0x000009C4, 0x000007D0, 0x00000320, 0x000007D0, 0x000001F4, 0x000002BC, 0x00000320, 0x00000064, 0x000003E8, 0x000002BC, 0x00000FA0, 0x00000BB8, 0x000005DC, 0x000005DC, 0x000009C4, 0x000005DC, 0x0000012C, 0x000004B0, 0x0000012C, 0x00000064, 0xFFFFF830, 0x00000BB8, 0x000009C4, 0x000009C4, 0x000007D0, 0x00000BB8, 0x000009C4, 0x00000BB8, 0x00001388, 0x00000BB8, 0x00001B58, 0x00001388, 0x00002EE0, 0xFFFFFA24, 0x000007D0, 0x00000320, 0xFFFFFC18, 0xFFFFF830, 0xFFFFFE0C, 0x000007D0, 0x00000BB8, 0x000007D0, 0x00000BB8, 0x0000012C, 0x00001388, 0x00000FA0, 0x00000320, 0x00001388, 0x000001F4, 0x00000BB8, 0x00000DAC, 0x00000320, 0x000007D0, 0x00000280, 0x000004B0, 0x000005DC, 0x000009C4, 0x000007D0, 0x00000FA0, 0x00001F40, 0x00003A98, 0x00000FA0, 0x000003E8, 0x000005DC, 0x000001F4, 0xFFFFFC18, 0x000001F4, 0xFFFFFC18, 0xFFFFFA24, 0x000007D0, 0x000001F4, 0x000003E8, 0x000007D0, 0x000003E8, 0x000001F4, 0x000007D0, 0x000005DC, 0x00000BB8, 0x00001388, 0x00000D02, 0x00000456, 0x000007D0, 0x00000708, 0x000007D0, 0x00000BB8, 0x00000BB8, 0x00000320, 0x00000320, 0x000005DC, 0x000003E8, 0x000007D0, 0xFFFFFC18, 0x00000BB8, 0x00000064, 0x000005DC, 0x00000FA0, 0x00000FA0, 0x00000BB8, 0x000007D0, 0x000005DC, 0x000005DC, 0x000005DC, 0x000005DC, 0x000005DC, 0x00000640, 0x000007D0, 0x000006A4, 0x000007D0, 0x000007D0, 0x000009C4, 0x000003E8, 0x000009C4, 0x00001F40, 0x00000320, 0x000007D0, 0x000007D0, 0x00000BB8, 0x000005DC, 0x00000FA0, 0x00000FA0, 0x00000258, 0x000009C4, 0x0000012C, 0x00000320, 0x000004B0, 0x00000708, 0x00000AF0, 0x000004B0, 0x00000320, 0x00000320, 0x00000258, 0x00000FA0, 0x00000640, 0x000005DC, 0x000009C4, 0x00000320, 0xFFFFFE0C, 0x000009C4, 0x00000190, 0x00000320, 0x000003E8, 0x00002710, 0x00001F40, 0x000493E0, 0x00002710, 0xFFFFB1E0, 0x00002710, 0x00004E20, 0x000186A0, 0x0000C350, 0x0000C350, 0x0000C350, 0x00030D40, 0x00000064, 0x000000C8, 0x0000012C, 0x0000012C, 0x000001F4, 0x00000096, 0x000000C8, 0x00000320, 0x00000014, 0x00013880, 0x00000014, 0x00007530, 0x00002710, 0x00001F40, 0x000186A0, 0x00007530, 0x000003E8, 0x00007530, 0x00000320};
struct lbl_803D5A4C_t
{
  short kind;
  u16 x2;
  u8 x4;
  u8 x5;
  u8 x6;
};
static struct lbl_803D5A4C_t lbl_803D5A4C[0x80C / (sizeof(struct lbl_803D5A4C_t))] = {{0, 0x011, 0xFF, 0, 2}, {1, 0x012, 0xFF, 0, 0}, {2, 0x013, 0x7F, 1, 0}, {3, 0x014, 0xFF, 0, 0}, {4, 0x015, 0xFF, 0, 0}, {5, 0x016, 0xFF, 0, 2}, {6, 0x017, 0xFF, 1, 0}, {7, 0x018, 0xFD, 1, 0}, {8, 0x019, 0xFF, 0, 0}, {9, 0x01A, 0xFF, 0, 0}, {0xA, 0x01B, 0xFF, 1, 0}, {0xB, 0x01C, 0xFF, 1, 0}, {0xC, 0x01D, 0xFF, 0, 0}, {0xD, 0x01E, 0xFF, 0, 0}, {0xE, 0x01F, 0xFF, 0, 0}, {0xF, 0x020, 0xFF, 0, 0}, {0x10, 0x021, 0xFF, 0, 0}, {0x11, 0x022, 0xFF, 0, 0}, {0x12, 0x023, 0xFF, 0, 0}, {0x13, 0x024, 0xFF, 1, 0}, {0x14, 0x025, 0xFF, 0, 0}, {0x15, 0x026, 0xFF, 0, 2}, {0x16, 0x027, 0x9F, 0, 0}, {0x17, 0x028, 0xFF, 0, 2}, {0x18, 0x029, 0xFF, 0, 2}, {0x19, 0x02A, 0xFF, 0, 0}, {0x1A, 0x02B, 0xFF, 1, 0}, {0x1B, 0x02C, 0xFF, 0, 0}, {0x1C, 0x02D, 0xFF, 0, 0}, {0x1D, 0x02E, 0xFF, 0, 0}, {0x1E, 0x02F, 0xFF, 0, 0}, {0x1F, 0x030, 0xFF, 0, 0}, {0x20, 0x031, 0xFF, 0, 0}, {0x21, 0x033, 0xFF, 0, 2}, {0x22, 0x032, 0xFF, 0, 2}, {0x23, 0x034, 0xFF, 0, 0}, {0x24, 0x035, 0xFF, 0, 2}, {0x25, 0x036, 0xFF, 0, 0}, {0x26, 0x037, 0xFF, 0, 0}, {0x27, 0x038, 0xFF, 0, 0}, {0x28, 0x039, 0xFF, 0, 0}, {0x29, 0x03A, 0xFF, 1, 0}, {0x2A, 0x03B, 0xFD, 1, 0}, {0x2B, 0x03C, 0xFF, 0, 0}, {0x2C, 0x03D, 0xFF, 0, 0}, {0x2D, 0x03E, 0xFF, 1, 0}, {0x2E, 0x03F, 0x87, 0, 0}, {0x2F, 0x040, 0x87, 0, 0}, {0x30, 0x041, 0xFF, 0, 0}, {0x31, 0x042, 0xFF, 0, 0}, {0x32, 0x043, 0xFF, 0, 0}, {0x33, 0x044, 0xFF, 0, 0}, {0x34, 0x045, 0xFF, 0, 0}, {0x35, 0x046, 0xFF, 0, 0}, {0x36, 0x047, 0xFF, 0, 0}, {0x37, 0x048, 0xFF, 0, 0}, {0x38, 0x049, 0xFF, 0, 0}, {0x39, 0x04A, 0xFF, 0, 0}, {0x3A, 0x04B, 0xFF, 0, 0}, {0x3B, 0x04C, 0xFF, 1, 0}, {0x3C, 0x04D, 0xFF, 0, 0}, {0x3D, 0x04E, 0xFF, 1, 0}, {0x3E, 0x04F, 0xFF, 1, 0}, {0x3F, 0x050, 0xFF, 1, 0}, {0x40, 0x051, 0xFF, 1, 0}, {0x41, 0x052, 0xFF, 1, 0}, {0x42, 0x053, 0xFF, 0, 0}, {0x43, 0x054, 0xFF, 1, 0}, {0x44, 0x055, 0xFF, 1, 0}, {0x45, 0x056, 0xFF, 1, 0}, {0x46, 0x057, 0xFF, 1, 0}, {0x47, 0x058, 0xFF, 0, 0}, {0x48, 0x059, 0xFF, 1, 0}, {0x49, 0x05A, 0xFF, 1, 0}, {0x4A, 0x05B, 0xFF, 1, 0}, {0x4B, 0x05C, 0xFF, 1, 0}, {0x4C, 0x05D, 0xFF, 1, 0}, {0x4D, 0x05E, 0xFF, 1, 0}, {0x4E, 0x060, 0x02, 0, 0}, {0x4F, 0x061, 0xFF, 0, 0}, {0x50, 0x062, 0xDF, 0, 0}, {0x51, 0x063, 0xFF, 0, 0}, {0x52, 0x064, 0xFF, 0, 0}, {0x53, 0x065, 0xFF, 0, 0}, {0x54, 0x066, 0xFF, 1, 0}, {0x55, 0x067, 0xDF, 0, 0}, {0x56, 0x068, 0xFF, 1, 0}, {0x57, 0x069, 0xFF, 0, 0}, {0x58, 0x06A, 0xFF, 1, 0}, {0x59, 0x06B, 0x1F, 0, 0}, {0x5A, 0x06C, 0xFF, 0, 0}, {0x5B, 0x06D, 0xFF, 1, 0}, {0x5C, 0x06E, 0xFF, 1, 0}, {0x5D, 0x06F, 0xFF, 0, 0}, {0x5E, 0x070, 0xFF, 0, 0}, {0x5F, 0x071, 0xFD, 1, 0}, {0x60, 0x072, 0xFD, 0, 0}, {0x61, 0x074, 0x02, 0, 0}, {0x62, 0x075, 0xDF, 0, 0}, {0x63, 0x076, 0xDF, 0, 0}, {0x64, 0x077, 0xDF, 0, 0}, {0x65, 0x078, 0x02, 0, 0}, {0x66, 0x07A, 0xFF, 0, 0}, {0x67, 0x07B, 0x02, 0, 0}, {0x68, 0x07C, 0x02, 0, 0}, {0x69, 0x07D, 0x87, 0, 0}, {0x6A, 0x07E, 0x87, 0, 0}, {0x6B, 0x07F, 0x1F, 0, 0}, {0x6C, 0x080, 0x87, 0, 0}, {0x6D, 0x082, 0xFF, 1, 1}, {0x6E, 0x084, 0xFF, 1, 1}, {0x6F, 0x085, 0xFF, 1, 1}, {0x70, 0x086, 0xFF, 1, 1}, {0x71, 0x087, 0xFF, 1, 1}, {0x72, 0x088, 0xFF, 1, 1}, {0x73, 0x089, 0x02, 1, 1}, {0x74, 0x08A, 0xFF, 1, 1}, {0x75, 0x08B, 0xFF, 1, 1}, {0x76, 0x08C, 0xFF, 1, 1}, {0x77, 0x08D, 0xFF, 1, 1}, {0x78, 0x08E, 0xFF, 1, 1}, {0x79, 0x08F, 0xFF, 1, 1}, {0x7A, 0x090, 0xFF, 1, 1}, {0x7B, 0x091, 0xFF, 1, 1}, {0x7C, 0x092, 0xFF, 1, 1}, {0x7D, 0x093, 0xFF, 1, 1}, {0x7E, 0x094, 0xFF, 1, 1}, {0x7F, 0x095, 0xFF, 1, 1}, {0x80, 0x096, 0xFF, 1, 1}, {0x81, 0x097, 0xFF, 1, 0}, {0x82, 0x098, 0x02, 1, 0}, {0x83, 0x099, 0x02, 1, 0}, {0x84, 0x09A, 0x02, 1, 0}, {0x85, 0x09B, 0x02, 1, 0}, {0x86, 0x09C, 0x02, 0, 0}, {0x87, 0x09D, 0x02, 1, 0}, {0x88, 0x09E, 0x02, 1, 0}, {0x89, 0x09F, 0xFF, 0, 0}, {0x8A, 0x0A0, 0xFF, 0, 0}, {0x8B, 0x0A1, 0xFF, 0, 0}, {0x8C, 0x0A2, 0xFF, 0, 0}, {0x8D, 0x0A3, 0xFF, 0, 0}, {0x8E, 0x0A4, 0xFD, 0, 0}, {0x8F, 0x0A5, 0xFD, 0, 0}, {0x90, 0x0A6, 0xFD, 0, 0}, {0x91, 0x0A7, 0xFF, 0, 0}, {0x92, 0x0A8, 0xDF, 0, 0}, {0x93, 0x0A9, 0x1F, 0, 0}, {0x94, 0x0AA, 0xFF, 0, 2}, {0x95, 0x0AB, 0xFF, 0, 2}, {0x96, 0x0AC, 0xFF, 0, 2}, {0x97, 0x0AD, 0xFF, 1, 1}, {0x98, 0x0AE, 0xFF, 1, 1}, {0x99, 0x0AF, 0x02, 1, 0}, {0x9A, 0x0B0, 0xFF, 1, 0}, {0x9B, 0x0B1, 0xFF, 1, 0}, {0x9C, 0x0B2, 0xFF, 1, 0}, {0x9D, 0x0B3, 0xFF, 1, 0}, {0x9E, 0x0B6, 0x02, 0, 0}, {0x9F, 0x0B7, 0xFF, 0, 0}, {0xA0, 0x0B8, 0xFF, 0, 0}, {0xA1, 0x0B9, 0xFF, 0, 0}, {0xA2, 0x0BA, 0xFF, 0, 0}, {0xA3, 0x0BB, 0xFF, 0, 0}, {0xA4, 0x0BC, 0xFF, 0, 0}, {0xA5, 0x0BD, 0xFF, 0, 0}, {0xA6, 0x0BE, 0xFF, 0, 0}, {0xA7, 0x0BF, 0xFF, 0, 0}, {0xA8, 0x0C0, 0xFF, 0, 0}, {0xA9, 0x0C1, 0xFF, 0, 0}, {0xAA, 0x0C2, 0xFF, 0, 0}, {0xAB, 0x0C3, 0xFF, 0, 0}, {0xAC, 0x0C4, 0xFF, 1, 1}, {0xAD, 0x0C5, 0xFF, 1, 1}, {0xAE, 0x0C6, 0xFF, 0, 0}, {0xAF, 0x0C7, 0xFF, 0, 0}, {0xB0, 0x0C8, 0xFF, 1, 1}, {0xB1, 0x0C9, 0xFF, 1, 1}, {0xB2, 0x0CA, 0xFF, 1, 1}, {0xB3, 0x0CB, 0xFF, 0, 0}, {0xB4, 0x0CC, 0xFF, 0, 0}, {0xB5, 0x0CD, 0xFF, 0, 0}, {0xB6, 0x0CE, 0xFF, 1, 0}, {0xB7, 0x0CF, 0xFF, 1, 1}, {0xB8, 0x0D0, 0xFF, 1, 1}, {0xB9, 0x0D1, 0xFF, 1, 1}, {0xBA, 0x0D2, 0xFF, 1, 1}, {0xBB, 0x0D3, 0xFF, 1, 1}, {0xBC, 0x0D4, 0xFF, 0, 0}, {0xBD, 0x0D5, 0xFF, 0, 0}, {0xBE, 0x0D6, 0xFF, 0, 0}, {0xBF, 0x0D7, 0xFF, 1, 1}, {0xC0, 0x0D8, 0xFF, 1, 1}, {0xC1, 0x0D9, 0xFF, 1, 1}, {0xC2, 0x0DA, 0xFF, 1, 0}, {0xC3, 0x0DB, 0xFF, 1, 0}, {0xC4, 0x0DC, 0xFF, 1, 0}, {0xC5, 0x0DD, 0xFF, 1, 0}, {0xC6, 0x0DE, 0xFF, 1, 1}, {0xC7, 0x0DF, 0xFF, 1, 0}, {0xC8, 0x0E0, 0xFF, 1, 0}, {0xC9, 0x0E1, 0xFF, 1, 0}, {0xCA, 0x0E2, 0xFF, 1, 0}, {0xCB, 0x0E3, 0xFF, 1, 1}, {0xCC, 0x0E4, 0xFF, 0, 0}, {0xCD, 0x0E5, 0xFF, 0, 0}, {0xCE, 0x0F0, 0xFF, 1, 0}, {0xCF, 0x0F1, 0xFF, 1, 0}, {0xD0, 0x0F2, 0xFF, 1, 0}, {0xD1, 0x0F3, 0xFF, 1, 0}, {0xD2, 0x0F4, 0xFF, 1, 0}, {0xD3, 0x0F5, 0xFF, 1, 0}, {0xD4, 0x0F6, 0xFF, 1, 0}, {0xD5, 0x0F7, 0xFF, 1, 0}, {0xD6, 0x0F8, 0xFF, 1, 0}, {0xD7, 0x002, 0x02, 0, 0}, {0xD8, 0x003, 0x02, 0, 0}, {0xD9, 0x004, 0x02, 0, 0}, {0xDA, 0x005, 0x02, 0, 0}, {0xDB, 0x006, 0x02, 0, 0}, {0xDC, 0x007, 0x02, 0, 0}, {0xDD, 0x008, 0x02, 0, 0}, {0xDE, 0x009, 0x02, 0, 0}, {0xDF, 0x00A, 0x02, 0, 0}, {0xE0, 0x00B, 0x02, 0, 0}, {0xE1, 0x00C, 0x02, 0, 0}, {0xE2, 0x00D, 0x02, 0, 0}, {0xE3, 0x00E, 0x02, 1, 0}, {0xE4, 0x00F, 0x02, 1, 0}, {0xE5, 0x010, 0x02, 1, 0}, {0xE6, 0x0E6, 0xFD, 0, 0}, {0xE7, 0x0E7, 0xFD, 0, 0}, {0xE8, 0x0E8, 0xFD, 0, 0}, {0xE9, 0x0E9, 0xFD, 0, 0}, {0xEA, 0x0EA, 0xFD, 0, 0}, {0xEB, 0x0EB, 0xFD, 0, 0}, {0xEC, 0x0EC, 0xFD, 0, 0}, {0xED, 0x0ED, 0xFD, 0, 0}, {0xEE, 0x0EE, 0xFD, 0, 0}, {0xEF, 0x0EF, 0xFD, 0, 0}, {0xF0, 0x0F9, 0xFD, 0, 0}, {0xF1, 0x0FA, 0xFD, 0, 0}, {0xF2, 0x0FB, 0xFD, 0, 0}, {0xF3, 0x0FC, 0xFD, 0, 0}, {0xF4, 0x0FD, 0xFD, 0, 0}, {0xF5, 0x0FE, 0xFD, 0, 0}, {0xF6, 0x0FF, 0xFD, 0, 0}, {0xF7, 0x100, 0xFD, 0, 0}, {0xF8, 0x101, 0xFD, 0, 0}, {0xF9, 0x05F, 0x02, 0, 0}, {0xFA, 0x073, 0x02, 0, 0}, {0xFB, 0x079, 0x02, 0, 0}, {0xFC, 0x081, 0x87, 0, 0}, {0xFD, 0x083, 0x14, 0, 0}, {0xFE, 0x0B4, 0x87, 0, 0}, {0xFF, 0x0B5, 0x87, 0, 0}, {0x29A}};
struct lbl_803B7A60_t
{
  s32 x0[4];
  s32 x10[4];
  s32 x20[4];
  s32 x30[4];
  f32 x40[4];
  u32 x50[4];
  u32 x60[4];
};
static struct lbl_803B7A60_t lbl_803B7A60 = {{0, 0, 0, 0}, {0, 0, 0, 0}, {0, 0, 0, 0}, {0, 0, 0, 0}, {0.0f, 0.0f, 0.0f, 0.0f}, {0x0FFFFFFF, 0x0FFFFFFF, 0x0FFFFFFF, 0x0FFFFFFF}, {0, 0, 0, 0}};
bool gm_80160474(CharacterKind, MajorSceneKind);
bool fn_80162CCC(void);
bool gm_80162D1C(void);
bool gm_80162EC8(void);
bool gm_80162F18(void);
bool fn_801630C4(void);
bool gm_80163114(void);
bool fn_80163D24(void);
bool fn_80163D74(void);
u8 gm_8016400C(u8 ckind);
bool gm_80164600(void);
bool gm_80164ABC(void);
bool fn_80164B48(void);
bool un_80304470(void);
bool un_80304510(void);
int un_803045A0(void);
int un_80304690(void);
bool un_80304780(void);
bool gmMainLib_8015CF94(void);
bool gmMainLib_8015D508(void);
int gmMainLib_8015D94C(u32);
bool gmMainLib_8015DADC(u32);
struct gmm_retval_EDBC *gmMainLib_8015EDBC(void);
s32 gmMainLib_8015EE90(void);
static const MotionFlags ftCo_MF_5_6 = Ft_MF_SkipAnimVel | Ft_MF_Unk06;
static const MotionFlags ftCo_MF_2_5_6 = ftCo_MF_5_6 | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_Squat = ftCo_MF_2_5_6 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_Dash = ftCo_MF_Squat | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_Run = ftCo_MF_5_6 | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_Appeal = (ftCo_MF_5_6 | Ft_MF_KeepFastFall) | Ft_MF_SkipModel;
static const MotionFlags ftCo_MF_9_10 = Ft_MF_KeepSfx | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_LandingAirN = (ftCo_MF_9_10 | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_LandingAirF = ftCo_MF_LandingAirN | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_LandingAirB = ftCo_MF_LandingAirN | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_LandingAirHi = ftCo_MF_LandingAirB | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_LandingAirLw = ftCo_MF_9_10 | Ft_MF_SkipModel;
static const MotionFlags ftCo_MF_Turn = ftCo_MF_2_5_6 | Ft_MF_KeepAccessory;
static const MotionFlags ftCo_MF_Walk = (ftCo_MF_2_5_6 | Ft_MF_KeepGfx) | Ft_MF_UpdateCmd;
static const MotionFlags ftCo_MF_3_5_6 = ftCo_MF_5_6 | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_Jump = (ftCo_MF_3_5_6 | Ft_MF_KeepFastFall) | Ft_MF_SkipNametagVis;
static const MotionFlags ftCo_MF_JumpAir = (ftCo_MF_3_5_6 | Ft_MF_KeepGfx) | Ft_MF_KeepColAnimPartHitStatus;
static const MotionFlags ftCo_MF_GuardReflect = ((((ftCo_MF_5_6 | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx) | Ft_MF_SkipModel) | Ft_MF_SkipColAnim) | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftCo_MF_Guard = Ft_MF_Unk19 | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftCo_MF_AttackBase = Ft_MF_KeepSfx | Ft_MF_SkipItemVis;
static const MotionFlags ftCo_MF_Attack = ftCo_MF_AttackBase | Ft_MF_FreezeState;
static const MotionFlags ftCo_MF_Attack_2 = ftCo_MF_Attack | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_AttackDash = ftCo_MF_Attack_2 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_AttackS3 = ftCo_MF_Attack_2 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_AttackHi3 = ftCo_MF_AttackS3 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_AttackLw3 = ftCo_MF_Attack | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_CliffAttackQuick = ((((ftCo_MF_AttackLw3 | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx) | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipModel) | Ft_MF_SkipAnimVel;
static const MotionFlags ftCo_MF_AttackAir = ftCo_MF_Attack | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_AttackAirN = ((ftCo_MF_AttackAir | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipHit) | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_AttackAirF = ftCo_MF_AttackAirN | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_AttackAirB = ftCo_MF_AttackAirN | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_AttackAirHi = ftCo_MF_AttackAirF | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_AttackAirLw = ftCo_MF_AttackAir | Ft_MF_SkipModel;
static const MotionFlags ftCo_MF_Attack4 = ftCo_MF_AttackLw3 | Ft_MF_SkipRumble;
static const MotionFlags ftCo_MF_AttackS4 = ftCo_MF_Attack4 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_AttackHi4 = ftCo_MF_Attack4 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_AttackLw4 = (ftCo_MF_Attack4 | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_Attack1 = ftCo_MF_Attack | Ft_MF_Unk19;
static const MotionFlags ftCo_MF_Attack11 = ftCo_MF_Attack1 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_Attack12 = ftCo_MF_Attack1 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_Attack13 = ftCo_MF_Attack12 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_Attack100 = ftCo_MF_Attack1 | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_ItemScope = Ft_MF_SkipItemVis | Ft_MF_SkipModelPartVis;
static const MotionFlags ftCo_MF_SwordSwing1 = ftCo_MF_ItemScope | Ft_MF_Unk06;
static const MotionFlags ftCo_MF_SwordSwing3 = ftCo_MF_SwordSwing1 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_SwordSwingDash = ftCo_MF_SwordSwing3 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_BatSwing1 = ftCo_MF_SwordSwing1 | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_BatSwing3 = ftCo_MF_BatSwing1 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_BatSwingDash = ftCo_MF_BatSwing3 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_ParasolSwing1 = ftCo_MF_SwordSwing1 | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_ParasolSwing3 = ftCo_MF_ParasolSwing1 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_ParasolSwingDash = ftCo_MF_ParasolSwing3 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_HarisenSwing1 = ftCo_MF_BatSwing1 | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_HarisenSwing3 = ftCo_MF_HarisenSwing1 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_HarisenSwingDash = ftCo_MF_HarisenSwing3 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_StarRodSwing1 = ftCo_MF_SwordSwing1 | Ft_MF_SkipModel;
static const MotionFlags ftCo_MF_StarRodSwing3 = ftCo_MF_StarRodSwing1 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_StarRodSwingDash = ftCo_MF_StarRodSwing3 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_LipstickSwing1 = ftCo_MF_StarRodSwing1 | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_LipstickSwing3 = ftCo_MF_LipstickSwing1 | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_LipstickSwingDash = ftCo_MF_LipstickSwing3 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_ParasolOpen = ftCo_MF_ParasolSwing1 | Ft_MF_SkipModel;
static const MotionFlags ftCo_MF_HammerBase = ftCo_MF_LipstickSwing1 | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_Hammer = ftCo_MF_HammerBase | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_WarpStarFall = ftCo_MF_Hammer | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_ItemScope_5_6 = ftCo_MF_5_6 | ftCo_MF_ItemScope;
static const MotionFlags ftCo_MF_ItemThrow = ftCo_MF_ItemScope_5_6 | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_LGunShoot = ((((ftCo_MF_ItemScope | Ft_MF_KeepFastFall) | Ft_MF_SkipHit) | Ft_MF_SkipModel) | Ft_MF_Unk06) | Ft_MF_SkipThrowException;
static const MotionFlags ftCo_MF_ItemScopeFire = ftCo_MF_LGunShoot | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_HammerFall = ftCo_MF_Hammer | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_ItemThrowAir = ftCo_MF_ItemThrow | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_LGunShootAir = ftCo_MF_LGunShoot | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_ItemScopeAir = ((ftCo_MF_HammerBase | Ft_MF_KeepFastFall) | Ft_MF_SkipThrowException) | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_Swing4 = Ft_MF_KeepGfx | Ft_MF_SkipRumble;
static const MotionFlags ftCo_MF_SwordSwing4 = ftCo_MF_SwordSwing1 | ftCo_MF_Swing4;
static const MotionFlags ftCo_MF_BatSwing4 = ftCo_MF_BatSwing1 | ftCo_MF_Swing4;
static const MotionFlags ftCo_MF_ParasolSwing4 = ftCo_MF_ParasolSwing1 | ftCo_MF_Swing4;
static const MotionFlags ftCo_MF_HarisenSwing4 = ftCo_MF_HarisenSwing1 | ftCo_MF_Swing4;
static const MotionFlags ftCo_MF_StarRodSwing4 = ftCo_MF_StarRodSwing1 | ftCo_MF_Swing4;
static const MotionFlags ftCo_MF_LipstickSwing4 = ftCo_MF_LipstickSwing1 | ftCo_MF_Swing4;
static const MotionFlags ftCo_MF_ItemThrow4 = ftCo_MF_ItemScope_5_6 | ftCo_MF_Swing4;
static const MotionFlags ftCo_MF_ItemThrowAir4 = ftCo_MF_ItemThrow4 | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_HammerMove = ftCo_MF_HammerBase | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_HammerTurn = ftCo_MF_HammerMove | Ft_MF_KeepAccessory;
static const MotionFlags ftCo_MF_HammerWalk = ftCo_MF_HammerMove | Ft_MF_UpdateCmd;
static const MotionFlags ftCo_MF_ItemFall = ((Ft_MF_SkipHit | Ft_MF_SkipModel) | Ft_MF_Unk06) | Ft_MF_SkipModelPartVis;
static const MotionFlags ftCo_MF_ItemScrewBase = ((ftCo_MF_AttackBase | ftCo_MF_ItemFall) | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_ItemScrew = ftCo_MF_ItemScrewBase | Ft_MF_SkipNametagVis;
static const MotionFlags ftCo_MF_HammerJump = (ftCo_MF_HammerMove | Ft_MF_SkipParasol) | Ft_MF_SkipNametagVis;
static const MotionFlags ftCo_MF_ItemScrewAir = (ftCo_MF_ItemScrewBase | Ft_MF_SkipParasol) | Ft_MF_KeepColAnimPartHitStatus;
static const MotionFlags ftCo_MF_LiftWait = Ft_MF_Unk19 | Ft_MF_SkipModelPartVis;
static const MotionFlags ftCo_MF_LiftMove = ((ftCo_MF_LiftWait | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipAnimVel) | Ft_MF_Unk06;
static const MotionFlags ftCo_MF_LiftTurn = ftCo_MF_LiftMove | Ft_MF_KeepAccessory;
static const MotionFlags ftCo_MF_LiftWalk = (ftCo_MF_LiftMove | Ft_MF_KeepGfx) | Ft_MF_UpdateCmd;
static const MotionFlags ftCo_MF_ParasolFall = (ftCo_MF_ItemFall | Ft_MF_SkipItemVis) | Ft_MF_Unk19;
static const MotionFlags ftCo_MF_FireFlowerShoot = (ftCo_MF_ParasolFall | Ft_MF_KeepGfx) | Ft_MF_SkipThrowException;
static const MotionFlags ftCo_MF_ItemScopeRapid = ((ftCo_MF_ParasolFall | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipThrowException) | Ft_MF_Unk19;
static const MotionFlags ftCo_MF_FireFlowerShootAir = ftCo_MF_FireFlowerShoot | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_ItemScopeAirRapid = ftCo_MF_ItemScopeRapid | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_Dazed = Ft_MF_UnkUpdatePhys | Ft_MF_SkipModelPartVis;
static const MotionFlags ftCo_MF_Damage = ftCo_MF_Dazed | Ft_MF_KeepSwordTrail;
static const MotionFlags ftCo_MF_DamageScrew = ftCo_MF_Damage | Ft_MF_SkipNametagVis;
static const MotionFlags ftCo_MF_DamageScrewAir = ftCo_MF_Damage | Ft_MF_KeepColAnimPartHitStatus;
static const MotionFlags ftCo_MF_Down = (((Ft_MF_SkipHit | Ft_MF_SkipAnimVel) | Ft_MF_Unk06) | Ft_MF_FreezeState) | Ft_MF_SkipModelPartVis;
static const MotionFlags ftCo_MF_DownU = ftCo_MF_Down | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_DownD = ftCo_MF_DownU | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_DownDamageU = ftCo_MF_DownU | Ft_MF_KeepSwordTrail;
static const MotionFlags ftCo_MF_DownDamageD = ftCo_MF_DownD | Ft_MF_KeepSwordTrail;
static const MotionFlags ftCo_MF_DownAttack = ((ftCo_MF_Attack | Ft_MF_SkipModel) | Ft_MF_SkipAnimVel) | Ft_MF_SkipModelPartVis;
static const MotionFlags ftCo_MF_DownAttackU = ftCo_MF_DownAttack | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_DownAttackD = ftCo_MF_DownAttack | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_PassiveWall = ftCo_MF_Dazed | Ft_MF_FreezeState;
static const MotionFlags ftCo_MF_Passive = ((ftCo_MF_Down | Ft_MF_KeepGfx) | Ft_MF_KeepColAnimHitStatus) | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftCo_MF_StopWall = ((((Ft_MF_KeepFastFall | Ft_MF_KeepGfx) | Ft_MF_SkipHit) | Ft_MF_SkipAnimVel) | Ft_MF_Unk06) | Ft_MF_SkipMetalB;
static const MotionFlags ftCo_MF_Pass = ftCo_MF_StopWall | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_OttottoWait = Ft_MF_Unk19 | Ft_MF_SkipMetalB;
static const MotionFlags ftCo_MF_CliffAction = Ft_MF_UnkUpdatePhys | Ft_MF_SkipMetalB;
static const MotionFlags ftCo_MF_CliffAction_4_5 = (ftCo_MF_CliffAction | Ft_MF_SkipModel) | Ft_MF_SkipAnimVel;
static const MotionFlags ftCo_MF_CliffCatch = ftCo_MF_CliffAction_4_5 | Ft_MF_Unk06;
static const MotionFlags ftCo_MF_CliffAttackSlow = (((ftCo_MF_AttackBase | ftCo_MF_CliffAction_4_5) | Ft_MF_KeepGfx) | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_CliffWait = ftCo_MF_CliffAction | Ft_MF_Unk19;
static const MotionFlags ftCo_MF_CatchWait = Ft_MF_FreezeState | Ft_MF_SkipMetalB;
static const MotionFlags ftCo_MF_CatchBase = (ftCo_MF_CatchWait | Ft_MF_SkipModel) | Ft_MF_SkipAnimVel;
static const MotionFlags ftCo_MF_Catch = (ftCo_MF_CatchBase | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_Throw = ftCo_MF_CatchBase | Ft_MF_SkipItemVis;
static const MotionFlags ftCo_MF_CatchAttack = ftCo_MF_Throw | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCo_MF_ThrowF = ftCo_MF_CatchAttack | Ft_MF_KeepFastFall;
static const MotionFlags ftCo_MF_ThrowB = ftCo_MF_CatchAttack | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_ThrowHi = ftCo_MF_ThrowF | Ft_MF_KeepGfx;
static const MotionFlags ftCo_MF_ThrowLw = ftCo_MF_Throw | Ft_MF_SkipHit;
static const MotionFlags ftCo_MF_Capture = ftCo_MF_CatchWait | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftCo_MF_CaptureAir = ftCo_MF_Capture | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_Thrown = ftCo_MF_Capture | Ft_MF_KeepSwordTrail;
static const MotionFlags ftCo_MF_ThrownAir = ftCo_MF_Thrown | Ft_MF_SkipParasol;
static const MotionFlags ftCo_MF_Shouldered = ftCo_MF_Capture | Ft_MF_Unk19;
static const MotionFlags ftCo_MF_Rebirth = Ft_MF_SkipModelPartVis | Ft_MF_SkipMetalB;
static const MotionFlags ftCo_MF_ThrownStar = ftCo_MF_Rebirth | Ft_MF_KeepSwordTrail;
static const MotionFlags ftCo_MF_Dead = ftCo_MF_Dazed | Ft_MF_SkipMetalB;
static const MotionFlags ftCo_MF_Sleep = ftCo_MF_Dead | Ft_MF_KeepSwordTrail;
static const MotionFlags ftCo_MF_Special = ((Ft_MF_SkipModel | Ft_MF_SkipItemVis) | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftCa_MF_Special = ftCo_MF_Special | Ft_MF_KeepSfx;
static const MotionFlags ftCa_MF_SpecialN = ftCa_MF_Special | Ft_MF_KeepFastFall;
static const MotionFlags ftCa_MF_SpecialAirN = ftCa_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftCa_MF_SpecialS = ftCa_MF_Special | Ft_MF_KeepGfx;
static const MotionFlags ftCa_MF_SpecialAirSStart = ftCa_MF_SpecialS | Ft_MF_SkipParasol;
static const MotionFlags ftCa_MF_SpecialAirS = ftCa_MF_SpecialS | Ft_MF_SkipParasol;
static const MotionFlags ftCa_MF_SpecialHi = (ftCo_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftCa_MF_SpecialAirHi = ftCa_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftCa_MF_SpecialLw = ftCa_MF_Special | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftCa_MF_SpecialLwRebound = ftCa_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_MultiJump = ((Ft_MF_KeepGfx | Ft_MF_SkipHit) | Ft_MF_SkipAnimVel) | Ft_MF_Unk06;
static const MotionFlags ftKb_MF_AttackDash = ((Ft_MF_KeepFastFall | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipItemVis) | Ft_MF_FreezeState;
static const MotionFlags ftKb_MF_AttackDashAir = ftKb_MF_AttackDash | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_18_20_21 = (Ft_MF_SkipItemVis | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftKb_MF_4_18_20_21 = ftKb_MF_18_20_21 | Ft_MF_SkipModel;
static const MotionFlags ftKb_MF_2_4_18_20_21 = ftKb_MF_4_18_20_21 | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftKb_MF_5_18_20_21 = ftKb_MF_18_20_21 | Ft_MF_SkipAnimVel;
static const MotionFlags ftKb_MF_SpecialN = ftKb_MF_4_18_20_21 | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialS = ftKb_MF_4_18_20_21 | Ft_MF_KeepGfx;
static const MotionFlags ftKb_MF_SpecialHi = (ftKb_MF_4_18_20_21 | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftKb_MF_SpecialNMr = (ftKb_MF_4_18_20_21 | Ft_MF_KeepFastFall) | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftKb_MF_SpecialNKp = (ftKb_MF_4_18_20_21 | Ft_MF_KeepFastFall) | Ft_MF_SkipHit;
static const MotionFlags ftKb_MF_SpecialNPe = (ftKb_MF_2_4_18_20_21 | Ft_MF_KeepFastFall) | Ft_MF_SkipHit;
static const MotionFlags ftKb_MF_SpecialNYs = ftKb_MF_5_18_20_21 | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialNLg = ftKb_MF_5_18_20_21 | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftKb_MF_SpecialNZd = (ftKb_MF_5_18_20_21 | Ft_MF_KeepGfx) | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftKb_MF_SpecialNDr = ftKb_MF_5_18_20_21 | Ft_MF_SkipHit;
static const MotionFlags ftKb_MF_SpecialNGk = ftKb_MF_SpecialNZd | Ft_MF_SkipHit;
static const MotionFlags ftKb_MF_SpecialNFx = (ftKb_MF_2_4_18_20_21 | Ft_MF_KeepGfx) | Ft_MF_SkipThrowException;
static const MotionFlags ftKb_MF_SpecialNLk = ((ftKb_MF_4_18_20_21 | Ft_MF_KeepGfx) | Ft_MF_SkipHit) | Ft_MF_SkipThrowException;
static const MotionFlags ftKb_MF_SpecialNSk = ftKb_MF_SpecialNLk | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialNNs = (ftKb_MF_2_4_18_20_21 | Ft_MF_SkipHit) | Ft_MF_SkipThrowException;
static const MotionFlags ftKb_MF_SpecialNPp = ftKb_MF_SpecialNNs | Ft_MF_KeepGfx;
static const MotionFlags ftKb_MF_SpecialNPk = ftKb_MF_SpecialNPp | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialNSs = ftKb_MF_5_18_20_21 | Ft_MF_SkipThrowException;
static const MotionFlags ftKb_MF_SpecialNSs_1 = ftKb_MF_SpecialNSs | Ft_MF_KeepGfx;
static const MotionFlags ftKb_MF_SpecialNMt = ftKb_MF_SpecialNSs_1 | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialNCl = ftKb_MF_SpecialNMt | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftKb_MF_SpecialNFc = (ftKb_MF_SpecialNDr | Ft_MF_KeepFastFall) | Ft_MF_SkipThrowException;
static const MotionFlags ftKb_MF_SpecialNPc = ftKb_MF_SpecialNSs_1 | Ft_MF_SkipHit;
static const MotionFlags ftKb_MF_SpecialNGw = ftKb_MF_SpecialNPc | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialLw = ftKb_MF_2_4_18_20_21 | Ft_MF_KeepSfx;
static const MotionFlags ftKb_MF_SpecialNCa = (ftKb_MF_SpecialLw | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftKb_MF_SpecialNDk = (ftKb_MF_4_18_20_21 | Ft_MF_SkipHit) | Ft_MF_KeepSfx;
static const MotionFlags ftKb_MF_5_9_18_20_21 = ftKb_MF_5_18_20_21 | Ft_MF_KeepSfx;
static const MotionFlags ftKb_MF_2_5_9_18_20_21 = ftKb_MF_5_9_18_20_21 | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftKb_MF_SpecialNPr = ftKb_MF_5_9_18_20_21 | Ft_MF_KeepGfx;
static const MotionFlags ftKb_MF_SpecialNMs = ftKb_MF_2_5_9_18_20_21 | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialNGn = ftKb_MF_2_5_9_18_20_21 | Ft_MF_SkipHit;
static const MotionFlags ftKb_MF_SpecialNFeStart = ftKb_MF_SpecialNMs | Ft_MF_SkipHit;
static const MotionFlags ftKb_MF_SpecialAirN = ftKb_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirS = ftKb_MF_SpecialS | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirHi = ftKb_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNMr = ftKb_MF_SpecialNMr | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNKp = ftKb_MF_SpecialNKp | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNPe = ftKb_MF_SpecialNPe | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNYs = ftKb_MF_SpecialNYs | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNLg = ftKb_MF_SpecialNLg | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNZd = ftKb_MF_SpecialNZd | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNDr = ftKb_MF_SpecialNDr | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNGk = ftKb_MF_SpecialNGk | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNFx = ftKb_MF_SpecialNFx | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNLk = ftKb_MF_SpecialNLk | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNSk = ftKb_MF_SpecialNSk | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNNs = ftKb_MF_SpecialNNs | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNPp = ftKb_MF_SpecialNPp | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNPk = ftKb_MF_SpecialNPk | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNSs = ftKb_MF_SpecialNSs | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNMt = ftKb_MF_SpecialNMt | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNCl = ftKb_MF_SpecialNCl | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNFc = ftKb_MF_SpecialNFc | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNPc = ftKb_MF_SpecialNPc | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNGw = ftKb_MF_SpecialNGw | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirLw = ftKb_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNCa = ftKb_MF_SpecialNCa | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNDk = ftKb_MF_SpecialNDk | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNPr = ftKb_MF_SpecialNPr | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNMs = ftKb_MF_SpecialNMs | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNGn = ftKb_MF_SpecialNGn | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialNFe = ftKb_MF_SpecialNFeStart | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_0_4_18_20_21 = ftKb_MF_4_18_20_21 | Ft_MF_KeepFastFall;
static const MotionFlags ftKb_MF_SpecialNCaptureTurn = ftKb_MF_0_4_18_20_21 | Ft_MF_KeepAccessory;
static const MotionFlags ftKb_MF_SpecialAirNCaptureTurn = ftKb_MF_SpecialNCaptureTurn | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialNCaptureWalk = ftKb_MF_0_4_18_20_21 | Ft_MF_UpdateCmd;
static const MotionFlags ftKb_MF_SpecialNCaptureJumpSquat = ftKb_MF_0_4_18_20_21 | Ft_MF_SkipNametagVis;
static const MotionFlags ftKb_MF_SpecialNLoop = ftKb_MF_0_4_18_20_21 | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNKpLoop = ftKb_MF_SpecialNKp | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNGkLoop = ftKb_MF_SpecialNGk | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNFxLoop = ftKb_MF_SpecialNFx | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNLkCharged = ftKb_MF_SpecialNLk | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNSkLoop = ftKb_MF_SpecialNSk | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNMtLoop = ftKb_MF_SpecialNMt | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNClCharged = ftKb_MF_SpecialNCl | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNFcLoop = ftKb_MF_SpecialNFc | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialNPrLoop = ftKb_MF_SpecialNPr | Ft_MF_Unk19;
static const MotionFlags ftKb_MF_SpecialAirNLoop = ftKb_MF_SpecialNLoop | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNKpLoop = ftKb_MF_SpecialNKpLoop | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNGkLoop = ftKb_MF_SpecialNGkLoop | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNFxLoop = ftKb_MF_SpecialNFxLoop | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNLkCharged = ftKb_MF_SpecialNLkCharged | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNSkLoop = ftKb_MF_SpecialNSkLoop | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNMtLoop = ftKb_MF_SpecialNMtLoop | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNClCharged = ftKb_MF_SpecialNClCharged | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNFcLoop = ftKb_MF_SpecialNFcLoop | Ft_MF_SkipParasol;
static const MotionFlags ftKb_MF_SpecialAirNPrLoop = ftKb_MF_SpecialNPrLoop | Ft_MF_SkipParasol;
static const MotionFlags ftFx_MF_Appeal = ((Ft_MF_KeepGfx | Ft_MF_SkipModel) | Ft_MF_SkipAnimVel) | Ft_MF_Unk06;
static const MotionFlags ftFx_MF_Special = ((Ft_MF_SkipModel | Ft_MF_SkipItemVis) | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftFx_MF_SpecialN = (ftFx_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_SkipThrowException;
static const MotionFlags ftFx_MF_SpecialS = (ftFx_MF_Special | Ft_MF_KeepGfx) | Ft_MF_KeepSfx;
static const MotionFlags ftFx_MF_SpecialHi = ftFx_MF_SpecialS | Ft_MF_KeepFastFall;
static const MotionFlags ftFx_MF_SpecialAirN = ftFx_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftFx_MF_SpecialAirS = ftFx_MF_SpecialS | Ft_MF_SkipParasol;
static const MotionFlags ftFx_MF_SpecialAirHiHold = ftFx_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftFx_MF_SpecialLw = (ftFx_MF_Special | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipColAnim;
static const MotionFlags ftFx_MF_SpecialAirLw = ftFx_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftFx_MF_SpecialNLoop = ftFx_MF_SpecialN | Ft_MF_Unk19;
static const MotionFlags ftFx_MF_SpecialAirNLoop = ftFx_MF_SpecialNLoop | Ft_MF_SkipParasol;
static const MotionFlags ftFx_MF_SpecialLwLoop = ftFx_MF_SpecialLw | Ft_MF_Unk19;
static const MotionFlags ftFx_MF_SpecialAirLwLoop = ftFx_MF_SpecialLwLoop | Ft_MF_SkipParasol;
static const MotionFlags ftGw_MF_Base = Ft_MF_SkipItemVis | Ft_MF_FreezeState;
static const MotionFlags ftGw_MF_Landing = ((Ft_MF_KeepColAnimHitStatus | Ft_MF_SkipHit) | Ft_MF_KeepSfx) | Ft_MF_SkipParasol;
static const MotionFlags ftGw_MF_LandingAirB = ftGw_MF_Landing | Ft_MF_KeepGfx;
static const MotionFlags ftGw_MF_LandingAirHi = ftGw_MF_LandingAirB | Ft_MF_KeepFastFall;
static const MotionFlags ftGw_MF_Attack = ftGw_MF_Base | Ft_MF_KeepSfx;
static const MotionFlags ftGw_MF_AttackLw3 = ftGw_MF_Attack | Ft_MF_SkipHit;
static const MotionFlags ftGw_MF_AttackAirN = ftGw_MF_Attack | ftGw_MF_Landing;
static const MotionFlags ftGw_MF_AttackAirB = ftGw_MF_AttackAirN | Ft_MF_KeepGfx;
static const MotionFlags ftGw_MF_AttackAirHi = ftGw_MF_AttackAirB | Ft_MF_KeepFastFall;
static const MotionFlags ftGw_MF_AttackS4 = (ftGw_MF_AttackLw3 | Ft_MF_KeepFastFall) | Ft_MF_SkipRumble;
static const MotionFlags ftGw_MF_Attack11 = (ftGw_MF_Attack | Ft_MF_KeepFastFall) | Ft_MF_Unk19;
static const MotionFlags ftGw_MF_Attack100 = (ftGw_MF_Attack | Ft_MF_KeepColAnimHitStatus) | Ft_MF_Unk19;
static const MotionFlags ftGw_MF_Special = (ftGw_MF_Base | Ft_MF_SkipModel) | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftGw_MF_SpecialS = ftGw_MF_Special | Ft_MF_KeepGfx;
static const MotionFlags ftGw_MF_SpecialHi = (ftGw_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftGw_MF_SpecialLwCatch = ftGw_MF_Special | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftGw_MF_SpecialN = (ftGw_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_SkipThrowException;
static const MotionFlags ftGw_MF_SpecialAirS = ftGw_MF_SpecialS | Ft_MF_SkipParasol;
static const MotionFlags ftGw_MF_SpecialAirHi = ftGw_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftGw_MF_SpecialAirLwCatch = ftGw_MF_SpecialLwCatch | Ft_MF_SkipParasol;
static const MotionFlags ftGw_MF_SpecialAirN = ftGw_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftGw_MF_SpecialLw = ftGw_MF_SpecialLwCatch | Ft_MF_Unk19;
static const MotionFlags ftGw_MF_SpecialAirLw = ftGw_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftNs_MF_Attack4 = ((Ft_MF_SkipHit | Ft_MF_SkipRumble) | Ft_MF_SkipItemVis) | Ft_MF_FreezeState;
static const MotionFlags ftNs_MF_AttackHi4 = ftNs_MF_Attack4 | Ft_MF_KeepGfx;
static const MotionFlags ftNs_MF_AttackLw4 = ftNs_MF_AttackHi4 | Ft_MF_KeepFastFall;
static const MotionFlags ftNs_MF_AttackHi4Start = ftNs_MF_AttackHi4 | Ft_MF_KeepSfx;
static const MotionFlags ftNs_MF_AttackLw4Start = ftNs_MF_AttackLw4 | Ft_MF_KeepSfx;
static const MotionFlags ftNs_MF_AttackS4 = ((ftNs_MF_Attack4 | Ft_MF_KeepFastFall) | Ft_MF_KeepSfx) | Ft_MF_SkipColAnim;
static const MotionFlags ftNs_MF_Special = ((Ft_MF_SkipModel | Ft_MF_SkipItemVis) | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftNs_MF_SpecialLw = ftNs_MF_Special | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftNs_MF_Special_SkipUpdateThrowException = ftNs_MF_Special | Ft_MF_SkipThrowException;
static const MotionFlags ftNs_MF_SpecialN = ftNs_MF_Special_SkipUpdateThrowException | Ft_MF_KeepFastFall;
static const MotionFlags ftNs_MF_SpecialS = ftNs_MF_Special_SkipUpdateThrowException | Ft_MF_KeepGfx;
static const MotionFlags ftNs_MF_SpecialHi = ftNs_MF_SpecialN | Ft_MF_KeepGfx;
static const MotionFlags ftNs_MF_SpecialAirLw = ftNs_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftNs_MF_SpecialAirN = ftNs_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftNs_MF_SpecialAirS = ftNs_MF_SpecialS | Ft_MF_SkipParasol;
static const MotionFlags ftNs_MF_SpecialAirHi = ftNs_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftNs_MF_SpecialLwLoop = ftNs_MF_SpecialLw | Ft_MF_Unk19;
static const MotionFlags ftNs_MF_SpecialAirLwLoop = ftNs_MF_SpecialLwLoop | Ft_MF_SkipParasol;
static const MotionFlags ftLk_MF_Base0 = Ft_MF_SkipModel | Ft_MF_SkipThrowException;
static const MotionFlags ftLk_MF_Base1 = Ft_MF_SkipItemVis | Ft_MF_FreezeState;
static const MotionFlags ftLk_MF_Base2 = ftLk_MF_Base1 | Ft_MF_KeepFastFall;
static const MotionFlags ftLk_MF_Base3 = ftLk_MF_Base0 | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftLk_MF_AttackS42 = ftLk_MF_Base2 | Ft_MF_SkipHit;
static const MotionFlags ftLk_MF_SpecialN = ftLk_MF_Base2 | ftLk_MF_Base3;
static const MotionFlags ftLk_MF_SpecialNFullyCharged = ftLk_MF_SpecialN | Ft_MF_Unk19;
static const MotionFlags ftLk_MF_SpecialAirNCharge = ftLk_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftLk_MF_SpecialAirNFullyCharged = ftLk_MF_SpecialNFullyCharged | Ft_MF_SkipParasol;
static const MotionFlags ftLk_MF_SpecialAirNFire = ftLk_MF_SpecialAirNCharge | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftLk_MF_SpecialSThrow = (ftLk_MF_Base3 | ftLk_MF_Base1) | Ft_MF_KeepGfx;
static const MotionFlags ftLk_MF_SpecialSCatch = ftLk_MF_SpecialSThrow | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftLk_MF_SpecialAirSThrow = (ftLk_MF_SpecialSThrow | ftLk_MF_Base3) | Ft_MF_SkipParasol;
static const MotionFlags ftLk_MF_SpecialAirSThrowEmpty = (ftLk_MF_SpecialSCatch | ftLk_MF_Base1) | Ft_MF_SkipParasol;
static const MotionFlags ftLk_MF_SpecialHi = (((((Ft_MF_KeepFastFall | Ft_MF_KeepGfx) | Ft_MF_SkipModel) | Ft_MF_KeepSfx) | Ft_MF_SkipItemVis) | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftLk_MF_SpecialLw = (((Ft_MF_KeepColAnimHitStatus | Ft_MF_SkipModel) | Ft_MF_SkipItemVis) | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftLk_MF_SpecialAirLw = ftLk_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftLk_MF_ZairCatch = Ft_MF_SkipModelPartVis | Ft_MF_SkipMetalB;
static const MotionFlags ftMr_MF_Special = ((Ft_MF_SkipModel | Ft_MF_SkipItemVis) | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftMr_MF_SpecialN = (ftMr_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_SkipThrowException;
static const MotionFlags ftMr_MF_SpecialHi = ((ftMr_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx) | Ft_MF_KeepSfx;
static const MotionFlags ftMr_MF_SpecialLw = (ftMr_MF_Special | Ft_MF_KeepColAnimHitStatus) | Ft_MF_KeepSfx;
static const MotionFlags ftMr_MF_SpecialAirN = ftMr_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftMr_MF_SpecialAirHi = ftMr_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftMr_MF_SpecialAirLw = ftMr_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftMr_MF_SpecialS = ((ftMr_MF_Special | Ft_MF_KeepGfx) | Ft_MF_SkipModel) | Ft_MF_SkipColAnim;
static const MotionFlags ftPe_MF_Base = Ft_MF_SkipItemVis | Ft_MF_FreezeState;
static const MotionFlags ftPe_MF_FloatAttack = ftPe_MF_Base | Ft_MF_SkipParasol;
static const MotionFlags ftPe_MF_FloatAttackAirN = (ftPe_MF_FloatAttack | Ft_MF_KeepColAnimHitStatus) | Ft_MF_SkipHit;
static const MotionFlags ftPe_MF_Move_14 = ftPe_MF_FloatAttackAirN | Ft_MF_KeepFastFall;
static const MotionFlags ftPe_MF_FloatAttackAirB = ftPe_MF_FloatAttackAirN | Ft_MF_KeepGfx;
static const MotionFlags ftPe_MF_FloatAttackAirHi = (ftPe_MF_FloatAttackAirN | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx;
static const MotionFlags ftPe_MF_Move_17 = ftPe_MF_FloatAttack | Ft_MF_SkipModel;
static const MotionFlags ftPe_MF_AttackS4 = (((ftPe_MF_Base | Ft_MF_KeepFastFall) | Ft_MF_SkipHit) | Ft_MF_KeepSfx) | Ft_MF_SkipRumble;
static const MotionFlags ftPe_MF_Special = (ftPe_MF_Base | Ft_MF_SkipModel) | Ft_MF_UnkUpdatePhys;
static const MotionFlags ftPe_MF_SpecialN = ftPe_MF_Special | Ft_MF_KeepFastFall;
static const MotionFlags ftPe_MF_SpecialHi = ftPe_MF_SpecialN | Ft_MF_KeepGfx;
static const MotionFlags ftPe_MF_SpecialLw = ftPe_MF_Special | Ft_MF_KeepColAnimHitStatus;
static const MotionFlags ftPe_MF_SpecialS = (ftPe_MF_Special | Ft_MF_KeepGfx) | Ft_MF_KeepSfx;
static const MotionFlags ftPe_MF_SpecialAirN = ftPe_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftPe_MF_SpecialAirHi = ftPe_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftPe_MF_SpecialAirS = ftPe_MF_SpecialS | Ft_MF_SkipParasol;
static const MotionFlags ftPe_MF_ParasolOpen = (((Ft_MF_SkipHit | Ft_MF_SkipModel) | Ft_MF_Unk06) | Ft_MF_SkipItemVis) | Ft_MF_SkipModelPartVis;
static const MotionFlags ftPe_MF_ParasolFallSpecial = ftPe_MF_ParasolOpen | Ft_MF_Unk19;
struct lbl_803D6300_t
{
  u16 x0;
  u16 x2;
  bool (*x4)(void);
};
struct lbl_803D6300_t lbl_803D6300[] = {{0x0016, 0xFFFF, fn_801735F0}, {0x0017, 0x0001, fn_80173644}, {0x0018, 0xFFFF, fn_80173510}, {0x0019, 0xFFFF, 0L}, {0x001A, 0xFFFF, 0L}, {0x001B, 0xFFFF, fn_8017367C}, {0x001C, 0xFFFF, gm_80164ABC}, {0x001D, 0xFFFF, gm_80164600}, {0x001E, 0x0040, fn_80162CCC}, {0x001F, 0x0040, gm_80162EC8}, {0x0020, 0x0040, fn_801630C4}, {0x0021, 0x0040, gm_80162D1C}, {0x0022, 0x0040, gm_80162F18}, {0x0023, 0x0040, gm_80163114}, {0x0024, 0x0010, fn_801722BC}, {0x0025, 0x0010, fn_801722F4}, {0x0026, 0x0080, gmMainLib_8015D508}, {0x0027, 0x0020, fn_80163D24}, {0x0028, 0x0020, fn_80163D74}, {0x0029, 0x0040, fn_8017232C}, {0x002A, 0x0040, fn_80172428}, {0x002B, 0x0040, fn_80172380}, {0x002C, 0x0040, fn_80172478}, {0x002D, 0x0040, fn_801723D4}, {0x002E, 0x0040, fn_801724C8}, {0x002F, 0x0001, fn_801724D0}, {0x0030, 0x0001, fn_80172504}, {0x0031, 0x0001, fn_80172538}, {0x0032, 0x0001, fn_8017256C}, {0x0033, 0x0001, fn_801725A8}, {0x0034, 0x0001, fn_801725E4}, {0x0035, 0x0001, fn_80172624}, {0x0036, 0x0001, fn_80172664}, {0x0037, 0xFFFF, fn_80172698}, {0x0038, 0xFFFF, fn_801726CC}, {0x0039, 0xFFFF, fn_80172700}, {0x003A, 0xFFFF, fn_80172734}, {0x003B, 0xFFFF, fn_80172768}, {0x003C, 0xFFFF, un_80304470}, {0x003D, 0xFFFF, un_80304510}, {0x0041, 0x0010, gmMainLib_8015CF94}, {0x0042, 0x0000, 0L}};
bool fn_801722BC(void);
bool fn_801722F4(void);
bool fn_8017232C(void);
bool fn_80172380(void);
bool fn_801723D4(void);
bool fn_80172428(void);
bool fn_80172478(void);
bool fn_801724C8(void);
bool fn_801724D0(void);
bool fn_80172504(void);
bool fn_80172538(void);
bool fn_8017256C(void);
bool fn_801725A8(void);
bool fn_801725E4(void);
bool fn_80172624(void);
bool fn_80172664(void);
bool fn_80172698(void);
bool fn_801726CC(void);
bool fn_80172700(void);
bool fn_80172734(void);
bool fn_80172768(void);
#pragma push
#pragma dont_inline on
#pragma pop
#pragma push
#pragma dont_inline on
bool fn_80172C78(int arg0);
#pragma pop
static const struct lbl_803B7AD0_t
{
  u8 x0;
  u8 x1;
  u8 x2;
  u16 x4;
} lbl_803B7AD0[0xB] = {{0, 5, 2, 0x3E8}, {1, 5, 2, 0x320}, {2, 5, 2, 0x190}, {3, 5, 2, 0x2BC}, {4, 5, 2, 0x032}, {5, 5, 2, 0x12C}, {6, 5, 2, 0x1F4}, {7, 5, 2, 0x064}, {8, 5, 2, 0x384}, {9, 5, 2, 0x0C8}, {10, 5, 2, 0x258}};
bool fn_80173510(void);
bool fn_801735F0(void);
bool fn_80173644(void);
bool fn_8017367C(void);
#pragma push
#pragma dont_inline on
#pragma pop
#pragma push
#pragma dont_inline on
#pragma pop
static struct lbl_803D6450_t
{
  u8 x0;
  u8 x1;
  u16 x2;
} lbl_803D6450[] = {{0x02, 0x00, 0x0067}, {0x02, 0x01, 0x0067}, {0x0D, 0x02, 0x00C0}, {0x19, 0x02, 0x0092}, {0x2C, 0x02, 0x00BB}, {0x2E, 0x02, 0x00DD}, {0x32, 0x02, 0x00BF}};
static struct lbl_803D646C_t
{
  u16 x0;
  u16 x2;
} lbl_803D646C[] = {{0x032, 0xB5}, {0x064, 0xB9}, {0x096, 0xAE}, {0x0C8, 0x8C}, {0x00A, 0x55}, {0x064, 0x56}, {0x3E8, 0x54}};
inline static bool gm_80173EEC_inline(void)
{
  int i;
  bool result = 1;
  for (i = 0; i < 0x100; i++)
  {
    if (i == 0x29)
    {
      continue;
    }
    if ((i == 0x42) || (i == 0x43))
    {
      continue;
    }
    if (i == 0xB9)
    {
      continue;
    }
    if ((i == 0xC9) || (i == 0xCA))
    {
      continue;
    }
    if (i == 9)
    {
      continue;
    }
    if (!gmMainLib_8015DADC(i))
    {
      result = 0;
      break;
    }
  }

  return result;
}

void gm_80173EEC(void)
{
  int i;
  volatile unsigned long long ckind;
  u16 *temp_r29;
  for (i = 0; i < 0x19; i++)
  {
    temp_r29 = &gmMainLib_8015EDBC()->x18[i];
    if ((*temp_r29) >= 100)
    {
      ckind = gm_8016400C(i);
      fn_80172C78(gm_80160474(ckind, MJ_CLASSIC));
      if (ckind == CKIND_ZELDA)
      {
        fn_80172C78(gm_80160474(CKIND_SEAK, MJ_CLASSIC));
      }
      if (ckind == CKIND_SEAK)
      {
        fn_80172C78(gm_80160474(CKIND_ZELDA, MJ_CLASSIC));
      }
    }
    if ((*temp_r29) >= 200)
    {
      ckind = gm_8016400C(i);
      fn_80172C78(gm_80160474(ckind, MJ_ADVENTURE));
      if (ckind == CKIND_ZELDA)
      {
        fn_80172C78(gm_80160474(CKIND_SEAK, MJ_ADVENTURE));
      }
      if (ckind == CKIND_SEAK)
      {
        fn_80172C78(gm_80160474(CKIND_ZELDA, MJ_ADVENTURE));
      }
    }
    if ((*temp_r29) >= 300)
    {
      ckind = gm_8016400C(i);
      fn_80172C78(gm_80160474(ckind, MJ_ALLSTAR));
      if (ckind == CKIND_ZELDA)
      {
        fn_80172C78(gm_80160474(CKIND_SEAK, MJ_ALLSTAR));
      }
      if (ckind == CKIND_SEAK)
      {
        fn_80172C78(gm_80160474(CKIND_ZELDA, MJ_ALLSTAR));
      }
    }
  }

  if (fn_80164B48() != 0)
  {
    fn_80172C78(0xA0);
  }
  if (gm_80164ABC())
  {
    fn_80172C78(0x9F);
  }
  if (gmMainLib_8015EE90() != 0)
  {
    fn_80172C78(0xDC);
  }
  if (gmMainLib_8015EDBC()->x14 >= 0x2710)
  {
    fn_80172C78(0x10C);
  }
  if (gmMainLib_8015D94C(0x1A) != 0)
  {
    ckind = gm_8016400C(i);
    fn_80172C78(0x96);
  }
  if (un_803045A0() != (0 & 0xFFFF))
  {
    fn_80172C78(0x116);
  }
  if (un_80304690() != 0)
  {
    fn_80172C78(0xAF);
  }
  if (un_80304780() != 0)
  {
    fn_80172C78(0x100);
  }
  if (gm_80173EEC_inline())
  {
    fn_80172C78(0x123);
  }
}
