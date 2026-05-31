typedef int bool;
typedef signed char s8;
typedef unsigned char u8;
typedef signed short int s16;
typedef signed long s32;
typedef unsigned long u32;
typedef int BOOL;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wtypedef-redefinition"
#pragma clang diagnostic pop
BOOL OSDisableInterrupts(void);
BOOL OSRestoreInterrupts(BOOL level);
typedef struct HSD_AllocEntry HSD_AllocEntry;
typedef struct PreloadCache PreloadCache;
typedef struct PreloadCacheScene PreloadCacheScene;
typedef struct PreloadCacheSceneEntry PreloadCacheSceneEntry;
typedef struct PreloadEntry PreloadEntry;
int lbDvd_80018A2C(u8);
typedef enum InternalStageId
{
  InternalStageID_Unk00,
  TEST,
  CASTLE,
  RCRUISE,
  KONGO,
  GARDEN,
  GREATBAY,
  SHRINE,
  ZEBES,
  KRAID,
  STORY,
  YORSTER,
  IZUMI,
  GREENS,
  CORNERIA,
  VENOM,
  PSTADIUM,
  PURA,
  MUTECITY,
  BIGBLUE,
  ONETT,
  FOURSIDE,
  ICEMTN,
  InternalStageID_Unk23,
  INISHIE1,
  INISHIE2,
  InternalStageID_Unk26,
  FLATZONE,
  OLDPUPUPU,
  OLDYOSHI,
  OLDKONGO,
  KINOKOROUTE,
  SHRINEROUTE,
  ZEBESROUTE,
  BIGBLUEROUTE,
  InternalStageID_Unk35,
  BATTLE,
  LAST,
  FIGUREGET,
  PUSHON,
  TMARIO,
  TCAPTAIN,
  TCLINK,
  TDONKEY,
  TDRMARIO,
  TFALCO,
  TFOX,
  TICECLIMBER,
  TKIRBY,
  TKOOPA,
  TLINK,
  TLUIGI,
  TMARS,
  TMEWTWO,
  TNESS,
  TPEACH,
  TPICHU,
  TPIKACHU,
  TPURIN,
  TSAMUS,
  TSEAK,
  TYOSHI,
  TZELDA,
  TGAMEWATCH,
  TEMBLEM,
  TGANON,
  HEAL,
  HOMERUN,
  FIGURE1,
  FIGURE2,
  FIGURE3
} InternalStageId;
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
struct PreloadCacheSceneEntry
{
  int char_id;
  u8 color;
  u8 x5;
};
struct PreloadEntry
{
  s8 state;
  s8 type;
  s8 heap;
  s8 load_state;
  u8 unknown004;
  u8 field5_0x5;
  s16 entry_num;
  s16 load_score;
  u8 field8_0xa;
  u8 field9_0xb;
  u32 size;
  HSD_AllocEntry *raw_data;
  HSD_AllocEntry *archive;
  s32 effect_index;
};
struct PreloadCacheScene
{
  bool is_heap_persistent[2];
  struct GameCache
  {
    u8 major_id;
    u8 field2_0x9;
    u8 field3_0xa;
    u8 field4_0xb;
    InternalStageId stage_id;
    PreloadCacheSceneEntry entries[8];
  } game_cache;
  s32 major_scene_changes;
};
struct PreloadCache
{
  s32 persistent_heaps;
  PreloadCacheScene scene;
  PreloadCacheScene new_scene;
  PreloadEntry entries[80];
  s32 persistent_heap;
  int preloaded;
  void *x974;
};
static PreloadCacheScene lbDvd_803BA638 = {{0}, {MJ_COUNT, 0, 0, 0, 0x148, {{CHKIND_NONE, 0, 1}, {CHKIND_NONE, 0, 1}, {CHKIND_NONE, 0, 1}, {CHKIND_NONE, 0, 1}, {CHKIND_NONE, 0, 1}, {CHKIND_NONE, 0, 1}, {CHKIND_NONE, 0, 1}, {CHKIND_NONE, 0, 1}}}};
static PreloadEntry lbDvd_803BA68C = {0, 0, 0, 0, -1, 0, -1};
static PreloadCache preloadCache;
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
#pragma push
#pragma dont_inline on
#pragma pop
inline static void inline3_alt(PreloadEntry *entry, bool *var_r9, bool *var_r10)
{
  PreloadEntry *other;
  int i;
  *var_r10 = 0;
  *var_r9 = 0;
  for (i = 0; i < ((signed) ((sizeof(preloadCache.entries)) / (sizeof(preloadCache.entries[0])))); i++)
  {
    other = &preloadCache.entries[i];
    if (((other->state == 1) && (other->heap == entry->heap)) && (other->load_score > 0))
    {
      *var_r9 = 1;
    }
    if ((((other->state == 2) || (other->state == 3)) && (other->heap == entry->heap)) && (other->load_score < 0))
    {
      *var_r10 = 1;
    }
  }

}

int lbDvd_80018A2C(u8 arg0)
{
  bool var_r31_2;
  bool var_r30;
  int result = 0;
  PreloadEntry *entry;
  bool enabled = OSDisableInterrupts();
  int i;
  for (i = 0; i < 0x50; i++)
  {
    entry = &preloadCache.entries[i];
    if (entry->state == 0)
    {
      continue;
    }
    if (entry->load_score <= 0)
    {
      continue;
    }
    if (!(entry->unknown004 & arg0))
    {
      continue;
    }
    if (entry->heap == preloadCache.persistent_heap)
    {
      result = 1;
      break;
    }
    switch (entry->state)
    {
      case 1:

      case 2:
        result = 1;
        break;

      case 3:
        var_r30 = 0;
        var_r31_2 = 0;
        inline3_alt(entry, &var_r31_2, &var_r30);
        if (var_r31_2 && var_r30)
      {
        result = 1;
        break;
      }
        entry->state = 4;
        entry->load_score = 0x270F;

      case 4:
        result = 2;
        continue;

      default:
        continue;

    }

    break;
  }

  OSRestoreInterrupts(enabled);
  return result;
}

static s32 lbDvd_804D37F4[2] = {4, 5};
