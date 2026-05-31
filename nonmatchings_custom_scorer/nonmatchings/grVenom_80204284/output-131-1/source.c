
typedef int bool;
typedef signed char s8;
typedef unsigned char u8;
typedef signed short int s16;
typedef unsigned short int u16;
typedef signed long s32;
typedef unsigned long u32;
typedef unsigned long long int u64;
typedef float f32;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wtypedef-redefinition"
#pragma clang diagnostic pop
typedef struct CmSubject CmSubject;
typedef struct HSD_AObj HSD_AObj;
typedef struct HSD_DObj HSD_DObj;
typedef struct _HSD_FObj HSD_FObj;
typedef struct HSD_Generator HSD_Generator;
typedef struct HSD_GObj HSD_GObj;
typedef struct HSD_GObjProc HSD_GObjProc;
typedef struct HSD_ImageDesc HSD_ImageDesc;
typedef struct HSD_JObj HSD_JObj;
typedef struct HSD_LightAttn HSD_LightAttn;
typedef struct HSD_LightPoint HSD_LightPoint;
typedef struct HSD_LightSpot HSD_LightSpot;
typedef struct HSD_LObj HSD_LObj;
typedef struct HSD_MObj HSD_MObj;
typedef struct HSD_Obj HSD_Obj;
typedef struct HSD_RObj HSD_RObj;
typedef struct HSD_Spline HSD_Spline;
typedef struct HSD_TObj HSD_TObj;
typedef struct HSD_WObj HSD_WObj;
typedef void (*GObj_RenderFunc)(HSD_GObj *gobj, int code);
typedef void (*HSD_GObjEvent)(HSD_GObj *gobj);
typedef struct _PermuterTemp1
{
  f32 x;
  f32 y;
  f32 z;
} Vec;
typedef struct _PermuterTemp1 Vec3;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
  f32 w;
} Quaternion;
typedef f32 Mtx[3][4];
typedef f32 (*MtxPtr)[4];
struct grCorneria_GroundVars;
typedef struct grDynamicAttr_UnkStruct grDynamicAttr_UnkStruct;
typedef struct Ground Ground;
typedef struct UnkArchiveStruct UnkArchiveStruct;
typedef HSD_GObj Ground_GObj;
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
struct lb_80011A50_t;
typedef struct AbsorbDesc AbsorbDesc;
typedef struct DynamicsDesc DynamicsDesc;
typedef struct HurtCapsule HurtCapsule;
typedef enum HurtCapsuleState
{
  HurtCapsule_Enabled,
  HurtCapsule_Disabled,
  Intangible
} HurtCapsuleState;
typedef u32 MotionFlags;
typedef struct HSD_GObj Fighter_GObj;
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
typedef enum _GXLightID
{
  GX_LIGHT0 = 0x001,
  GX_LIGHT1 = 0x002,
  GX_LIGHT2 = 0x004,
  GX_LIGHT3 = 0x008,
  GX_LIGHT4 = 0x010,
  GX_LIGHT5 = 0x020,
  GX_LIGHT6 = 0x040,
  GX_LIGHT7 = 0x080,
  GX_MAX_LIGHT = 0x100,
  GX_LIGHT_NULL = 0
} GXLightID;
typedef struct _GXColor
{
  u8 r;
  u8 g;
  u8 b;
  u8 a;
} GXColor;
typedef struct _GXLightObj
{
  u32 dummy[16];
} GXLightObj;
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
typedef HSD_GObj Item_GObj;
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
struct HurtCapsule
{
  HurtCapsuleState state;
  Vec3 a_offset;
  Vec3 b_offset;
  float scale;
  HSD_JObj *bone;
  u8 skip_update_pos : 1;
  u8 x24_b1 : 1;
  u8 x24_b2 : 1;
  u8 x24_b3 : 1;
  u8 x24_b4 : 1;
  u8 x24_b5 : 1;
  u8 x24_b6 : 1;
  u8 x24_b7 : 1;
  Vec3 a_pos;
  Vec3 b_pos;
  int bone_idx;
};
struct AbsorbDesc
{
  int x0_bone_id;
  Vec3 x4_offset;
  float x10_size;
};
struct lb_80011A50_t;
struct lb_00F9_UnkDesc1Inner
{
  f32 unk_0;
  f32 unk_4;
  Quaternion unk_8;
  f32 unk_18;
  Vec3 unk_1C;
  Vec3 unk_28;
  f32 unk_34;
  f32 unk_38;
};
struct lb_00F9_UnkDesc1
{
  struct lb_00F9_UnkDesc1Inner array[2];
};
struct lb_00F9_UnkDesc0
{
  HSD_JObj *jobj;
  Quaternion rotate;
  Vec3 translate;
  Vec3 scale;
  Vec3 unk_2C;
  Vec3 unk_38;
  f32 unk_44;
  f32 unk_48;
  f32 unk_4C;
  f32 unk_50;
  s32 unk_54;
  Quaternion unk_58;
  f32 unk_68;
  Vec3 unk_6C;
  Vec3 unk_78;
  f32 unk_84;
  f32 unk_88;
  f32 unk_8C;
};
union PolymorphicDesc
{
  u8 _[0x90];
  struct lb_00F9_UnkDesc0 lb_unk0;
  struct lb_00F9_UnkDesc1 lb_unk1;
  struct AbsorbDesc absorb;
  struct HurtCapsule hurt;
};
struct DynamicsData
{
  union PolymorphicDesc desc;
  struct DynamicsData *next;
  s32 unk_94;
};
struct DynamicsDesc
{
  struct DynamicsData *data;
  unsigned int count;
  Vec3 pos;
};
struct lb_804D63A0_t
{
  struct DynamicsData entries[0x140];
};
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
struct GroundVars_unk
{
  int xC4;
  int xC8;
  int xCC;
  int xD0;
  int xD4;
  int xD8;
  int xDC;
  int xE0;
};
struct GroundVars_izumi
{
  HSD_TObj *xC4;
  HSD_GObj *xC8;
  HSD_GObj *xCC;
  HSD_JObj *xD0;
  HSD_JObj *xD4;
  int xD8;
  float xDC;
};
struct GroundVars_izumi2
{
  HSD_JObj *xC4;
  HSD_JObj *xC8;
  int xCC;
  int xD0;
  int xD4;
  int xD8;
  float xDC;
};
struct GroundVars_izumi3
{
  short xC4;
  short xC6;
  short xC8;
  short xCA;
  HSD_JObj *xCC;
  float xD0;
  float xD4;
  float xD8;
  float xDC;
};
struct GroundVars_flatzone
{
  u8 xC4;
  u8 xC5;
  u8 xC6;
  u8 xC7;
  s16 xC8;
  s16 xCA;
  s16 xCC;
  s16 xCE;
  s32 xD0;
  s32 xD4;
};
struct GroundVars_flatzone2
{
  s32 xC4;
  f32 xC8;
  grDynamicAttr_UnkStruct *xCC;
  s32 xD0;
  s32 xD4;
};
struct grKongo_GroundVars
{
  f32 xC4;
  f32 xC8;
  f32 xCC;
  union 
  {
    struct 
    {
      void *keep;
    } taru;
  } u;
  f32 xD4;
  f32 xD8;
  HSD_JObj *xDC;
  HSD_JObj *xE0;
  s16 xE4;
  s16 xE6;
  f32 xE8;
};
struct grKongo_GroundVars2
{
  HSD_Spline *xC4;
  f32 xC8;
  s16 xCC;
  s16 xCE;
  f32 xD0;
  f32 xD4;
  f32 xD8;
  f32 xDC;
  f32 xE0;
  f32 xE4;
  f32 xE8;
};
struct grKongo_GroundVars3
{
  s16 xC4;
  s16 xC6;
  s16 xC8;
  s16 xCA;
  HSD_JObj *xCC;
  HSD_JObj *xD0;
  f32 xD4;
  f32 xD8;
  f32 xDC;
  f32 xE0;
  f32 xE4;
  f32 xE8;
};
struct grKraid_GroundVars
{
  s8 x0;
  s8 x1;
  f32 x4;
  f32 x8;
  f32 xC;
  s32 x10;
};
struct grKraid_GroundVars2
{
  s8 x0;
  s8 x1;
  s8 x2;
  s8 x3;
  s8 x4;
  s8 x5;
  f32 x8;
  s32 xC;
  HSD_JObj *x10;
  HSD_JObj *x14;
};
typedef struct grZakoGenerator_Spawn grZakoGenerator_Spawn;
typedef HSD_Generator *(*grZakoGenerator_SpawnFunc)(Vec3 *, s32);
typedef struct grZakoGenerator_Config
{
  grZakoGenerator_Spawn *spawn_descs;
  grZakoGenerator_Spawn *spawns;
  int count;
  grZakoGenerator_SpawnFunc callback;
  f32 x10;
  HSD_Generator *gen;
  int x18;
} grZakoGenerator_Config;
struct grCorneria_GroundVars
{
  union 
  {
    struct 
    {
      u8 b0 : 1;
      u8 b1 : 1;
      u8 b2 : 1;
    } flags;
    u8 value;
  } xC4;
  u8 xC5;
  union 
  {
    struct 
    {
      u8 b0 : 1;
    } flags;
    u8 value;
  } xC6;
  u8 xC7;
  grZakoGenerator_Config *xC8;
  grZakoGenerator_Config *xCC;
  f32 xD0;
  f32 base_x;
  f32 base_y;
  f32 offset_x;
  union 
  {
    f32 val;
    struct 
    {
      u8 b0 : 1;
    } flags;
  } offset_y;
  Vec3 xE4;
  f32 xF0;
  f32 xF4;
  f32 xF8;
  f32 xFC;
  s32 x100;
  s32 x104;
  u32 x108;
  s32 x10C;
  s32 x110;
  f32 x114;
  s8 x118;
  u8 x119;
  u8 x11A;
  u8 x11B;
  u32 x11C;
  Item_GObj *left_cannon;
  Item_GObj *right_cannon;
  HSD_GObj *x128;
  HSD_JObj *x12C;
};
struct grCorneria_GroundVars2
{
  union 
  {
    struct 
    {
      u8 b0 : 1;
    } flags;
    u8 value;
  } xC4;
  u8 xC5;
  u8 xC6;
  u8 xC7;
  s32 xC8;
  s32 xCC;
  s32 xD0;
  s32 xD4;
  s32 xD8;
  HSD_GObj *xDC;
  HSD_GObj *xE0;
  HSD_GObj *xE4;
  HSD_GObj *xE8;
  HSD_GObj *xEC;
  s32 xF0;
  s32 xF4;
  s32 xF8;
  s32 xFC;
  s32 x100;
};
struct grKinokoRoute_GroundVars_Entry
{
  Vec3 pos;
  HSD_JObj *jobj;
};
struct grKinokoRoute_GroundVars
{
  struct grKinokoRoute_GroundVars_Entry entries[4];
};
struct grKinokoRoute_GroundVars2
{
  u8 flags;
  u8 pad_01[1];
  s16 phase;
  s16 spawn_idx;
  s16 zone_idx;
  s16 cam_timer;
  u8 pad_0A[2];
  Vec3 reb0_pos;
};
struct grSmashTaunt_GroundVars
{
  s16 state;
  s16 timer;
  s16 line;
  s16 sis_data_idx;
  s32 sound_id;
  HSD_JObj *jobj0;
  HSD_JObj *jobj1;
  HSD_JObj *jobj2;
  s16 joint_idx0;
  s16 joint_idx1;
  s16 joint_idx2;
  void *text;
  f32 xE8;
  f32 xEC;
};
struct grVenom_GroundVars
{
  u32 xC4;
  u32 xC8;
  u32 xCC;
  u32 xD0;
  f32 xD4;
  f32 xD8;
  f32 xDC;
  f32 xE0;
  f32 xE4;
  f32 xE8;
  f32 xEC;
  s32 xF0;
  s32 xF4;
  s32 xF8;
  s32 xFC;
  s32 x100;
};
struct grVenom_GroundVars2
{
  HSD_JObj *xC4;
  HSD_JObj *xC8;
  HSD_JObj *xCC;
  HSD_JObj *xD0;
  HSD_JObj *xD4;
  HSD_JObj *xD8;
  HSD_JObj *xDC;
  union 
  {
    struct 
    {
      u16 padding : 7;
      u16 state : 2;
      u16 padding2 : 7;
    } xE0_state_pad;
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
  } xE0_state;
};
struct grArwing_GroundVars
{
  u32 xC4;
  u32 xC8;
  u32 xCC;
  u32 xD0;
  s32 xD4;
  s32 xD8;
  f32 xDC;
  Vec3 xE0;
  f32 xEC;
};
struct grGreatBay_GroundVars
{
  u8 xC4;
  struct 
  {
    u8 b0123456 : 7;
    u8 b7 : 1;
  } xC5;
  s16 xC6;
  HSD_Generator *xC8;
  f32 xCC;
  s32 xD0;
  s32 xD4;
  u32 xD8;
  f32 xDC;
  f32 xE0;
};
struct grGreatBay_GroundVars2
{
  HSD_GObj *gobjs[4];
  s16 x10;
  struct 
  {
    u8 b0 : 1;
    u8 b1 : 1;
    u8 b2 : 1;
    u8 b3 : 1;
    u8 b4567 : 4;
  } x12;
  s32 x14;
  u32 x18;
  f32 x1C;
  HSD_JObj *jobj;
};
struct grGreatBay_GroundVars3
{
  Vec3 translation;
  f32 xD0;
  f32 xD4;
  f32 xD8;
  f32 xDC;
  f32 xE0;
  HSD_JObj *jobj;
  f32 xE8;
  f32 xEC;
  s32 xF0;
};
struct grGreatBay_GroundVars4
{
  s32 xC4;
  s32 xC8;
  s32 xCC;
  s32 xD0;
  s32 xD4;
  s32 xD8;
  s32 xDC;
  f32 xE0;
  Vec3 xE4;
  Item_GObj *xF0;
};
struct grGarden_GroundVars
{
  s32 xc4;
  s32 xc8;
};
struct grGarden_GroundVars2
{
  Item_GObj *xc4;
  s8 xc8;
  s32 xcc;
};
struct grIceMt_GroundVars
{
  s16 xC4;
  s16 xC6;
  s16 xC8;
  s16 xCA;
  s16 xCC;
  s16 xCE;
  s16 xD0;
  f32 xD4;
  s16 xD8;
  s16 xDA;
  s16 xDC;
  s16 xDE;
  s16 xE0;
  f32 xE4;
  u32 xE8;
  u32 xEC;
  u32 xF0;
  s16 xF4[2];
  HSD_GObj *xF8[5];
  s16 x10C;
  s16 x10E;
};
struct grIceMt_GroundVars2
{
  f32 xC4;
  HSD_JObj *xC8;
  HSD_JObj *xCC;
  HSD_JObj *xD0;
  HSD_JObj *xD4;
  HSD_JObj *xD8;
  HSD_JObj *xDC;
  HSD_JObj *xE0;
  HSD_JObj *xE4;
  HSD_JObj *xE8;
  HSD_JObj *xEC;
  HSD_JObj *xF0;
  HSD_JObj *xF4;
};
typedef struct grInishie1_Block grInishie1_Block;
typedef struct grInishie1_GroundVars
{
  union 
  {
    u32 xC4;
    struct 
    {
      u8 xC4_flags_b0 : 1;
      u8 xC4_flags_b1 : 1;
      u8 xC4_flags_b2 : 1;
      u8 xC4_flags_b3 : 1;
      u8 xC4_flags_b4 : 1;
      u8 xC4_flags_b5 : 1;
      u8 xC4_flags_b6 : 1;
      u8 xC4_flags_b7 : 1;
    };
  };
  s16 xC6;
  s16 xC8;
  s16 xCA;
  s16 xCC;
  s32 xD0;
  s32 xD4;
  s32 xD8;
  grInishie1_Block *blocks;
  f32 xE0;
  f32 xE4;
  s16 xE8;
  s16 xEA;
  s16 xEC;
  s16 xEE;
  f32 xF0;
  f32 xF4;
  f32 xF8;
  f32 xFC;
  HSD_JObj *x100;
  HSD_JObj *x104;
  HSD_JObj *x108;
  HSD_JObj *x10C;
} grInishie1_GroundVars;
struct grInishie1_GroundVars2
{
  HSD_JObj *xC4;
  s32 xC8;
  s32 xCC;
  grInishie1_Block *blocks;
  s16 xD8;
  s16 xDA;
  s16 xCA;
  s16 xC6;
};
struct grInishie1_GroundVars3
{
  HSD_JObj *xC4;
  s32 xC8;
  s32 xCC;
};
struct grInishie2_GroundVars
{
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
  } xC4_flags;
  s16 xC6;
  s16 xC8;
  s16 xCA;
  s16 xCC;
  u32 xD0;
  u32 xD4;
  Vec3 xD8;
};
struct grOldKongo_GroundVars
{
  s16 xC4;
  s16 xC6;
  s16 xC8;
  s16 xCA;
  s16 xCC;
  s16 xCE;
  void *xD0;
  void *xD4;
  f32 xD8;
  f32 xDC;
  f32 xE0;
  f32 xE4;
  f32 xE8;
  f32 xEC;
};
struct grOldPupupu_GroundVars
{
  s32 xC4;
  s32 xC8;
  s32 xCC;
  s32 xD0;
  s32 xD4;
  s32 xD8;
  s32 xDC;
  s32 xE0;
};
struct grOldPupupu_GroundVars2
{
  s16 xC4;
  s16 xC6;
};
struct grInishie2_GroundVars2
{
  Item_GObj *xC4;
  HSD_GObj *xC8;
  HSD_GObj *xCC;
};
struct grInishie2_GroundVars3
{
  s16 xC4;
  s16 xC6;
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
  } xC8_flags;
  s16 xCA;
  Vec3 xCC;
  Vec3 xD8;
};
struct grStadium_GroundVars
{
  u8 xC4_b0 : 1;
  u8 xC4_b1 : 1;
  u32 xC8;
  HSD_MObj *xCC;
  UnkArchiveStruct *xD0;
  float xD4;
  int xD8;
  s16 xDC;
  s16 xDE;
  s16 xE0;
  s16 xE2;
  HSD_GObj *xE4;
  HSD_GObj *xE8;
};
struct grStadium_Display
{
  u8 xC4_b0 : 1;
  u8 xC4_b1 : 1;
  HSD_TObj *xC8;
  HSD_MObj *xCC;
  HSD_ImageDesc *xD0;
  HSD_GObj *xD4;
  HSD_GObj *xD8;
  HSD_GObj *xDC;
  int xE0;
  s16 xE4;
  s16 xE6;
  s16 xE8;
  s16 xEA;
  s16 xEC;
  s16 xEE;
  s16 xF0;
  s16 xF2;
  CmSubject *xF4;
  u8 xF8_0 : 1;
  u8 xF8_1 : 1;
  u8 xF8_2 : 1;
};
struct grStadium_type9_GroundVars
{
  u8 xC4_b0 : 1;
  u8 xC4_b1 : 1;
  HSD_Generator *xC8;
  HSD_GObj *xCC_gobj;
  HSD_GObj *xD0_gobj;
  HSD_JObj *xD4_jobj;
};
struct grYorster_TrackElement
{
  s8 x00;
  u8 x01;
  u8 pad_02[2];
  f32 x04;
  f32 x08;
  s32 x0C;
  s32 x10;
  s32 x14;
  HSD_JObj *x18;
  HSD_GObj *x1C;
};
struct grYorster_GroundVars
{
  int xC4;
  struct grYorster_TrackElement elements[9];
};
struct grZebes_GroundVars
{
  u8 x0_b0 : 1;
  u32 x4;
  s16 x8;
  s16 xA;
  Vec3 xC;
};
struct grZebes_GroundVars2
{
  s16 xC4;
};
struct grZebes_GroundVars3
{
  Item_GObj *xC4;
  s32 xC8;
};
struct grZebes_GroundVars4
{
  u8 xC4;
  u8 xC5;
  u16 xC6;
  f32 xC8;
  f32 xCC;
  f32 xD0;
  f32 xD4;
  u32 xD8;
  u32 xDC;
  u32 xE0;
  s16 xE4;
  s16 xE6;
  s32 xE8;
  u32 xEC;
};
struct grZebes_GroundVars5
{
  s16 xC4;
  s16 xC6;
  u32 xC8;
  f32 xCC;
  f32 xD0;
  f32 xD4;
  f32 xD8;
  u32 xDC;
  u32 xE0;
  u32 xE4;
  s16 xE8;
  s16 xEA;
  u32 xEC;
  u32 xF0;
  s16 xF4;
  s16 xF6;
  u32 xF8;
  u32 xFC;
  u32 x100;
};
struct grRCruise_Entry;
struct grRCruise_SubEntry
{
  u8 x00;
  u8 pad_01;
  s16 x02;
  s32 x04;
  s32 x08;
  HSD_JObj *x0C;
};
struct grRCruise_VanishEntry;
struct grRCruise_GroundVars
{
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
  } xC4;
  struct lb_80011A50_t *x04;
  f32 x08;
  s32 x0C;
  u32 x10;
  f32 x14;
  f32 x18;
  f32 x1C;
  f32 x20;
  f32 x24;
  f32 x28;
  s32 x2C;
  s32 x30;
  s32 x34;
  s32 x38;
  struct grRCruise_SubEntry x3C[3];
  struct grRCruise_Entry *entries;
  struct grRCruise_VanishEntry *vanish;
  u8 pad_74[0xC];
};
struct grRCruise_GroundVars2
{
  DynamicsDesc xC4;
  DynamicsDesc xD0;
  HSD_GObj *xEC;
};
struct grFigureGet_GroundVars
{
  s32 x0;
  s32 x4;
  int x8;
  int xC;
  int x10[3];
  int x1C[3];
  HSD_GObj *x28[3];
  Item_GObj *x34[3];
};
struct grFourside_GroundVars
{
  HSD_JObj *x0;
  HSD_JObj *x4;
  HSD_JObj *x8;
};
struct grFourside_CraneVars
{
  u8 x0;
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
  } x1;
  int x4;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  float x1C;
};
struct grFourside_UfoVars
{
  u8 x0;
  u8 x1;
  u8 x2;
  u8 x3;
  int x4;
  int x8;
  CmSubject *xC;
};
struct grFourside_GroundVars2
{
  u8 x0;
  u8 x1;
  s32 x4;
  s32 x8;
};
struct grGreens_BlockVars;
struct grGreens_GroundVars
{
  union 
  {
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
    int whole_thing;
  } x0_flags;
  Vec *x4;
  struct grGreens_BlockVars *x8_blocks;
  int xC;
  int x10;
  int x14;
  int x18;
  int x1C;
};
struct grGreens_GroundVars2
{
  int x0;
  int x4;
  int x8;
  int xC;
  int x10;
  int x14;
  int x18;
  int x1C;
  int x20;
  int x24;
};
struct grMuteCity_GroundVars
{
  s16 xC4;
  s16 xC6;
  HSD_GObj *xC8;
  HSD_GObj *xCC;
  struct 
  {
    u8 b0 : 1;
    u8 b1 : 1;
    u8 b23 : 2;
    u8 b4 : 1;
    u8 b5 : 1;
    u8 b6 : 1;
    u8 b7 : 1;
  } xD0_flags;
  u8 xD1;
  s16 xD2;
  f32 xD4;
  f32 xD8;
  HSD_JObj *xDC;
  HSD_JObj *xE0;
  Vec3 xE4;
  Vec3 xF0;
  HSD_JObj *xFC;
  HSD_JObj *x100;
  HSD_JObj *x104;
  HSD_JObj *x108;
  HSD_JObj *x10C;
  HSD_LObj *x110;
  f32 x114;
  f32 x118;
  f32 x11C;
  f32 x120;
  f32 x124;
  f32 x128;
  f32 x12C;
  f32 x130;
};
struct grMuteCity_GroundVars2
{
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
  } xC4_flags;
  HSD_JObj *xC8;
  f32 xCC;
  f32 xD0;
  GXColor saved_colors[4];
};
struct grOnett_AwningData
{
  HSD_JObj *jobj;
  f32 initial_y;
  f32 accumulator;
  f32 velocity;
  f32 initial;
  s16 counter;
  s16 counter_prev;
  s16 cooldown;
  s16 flag;
};
struct grOnett_GroundVars
{
  struct grOnett_AwningData awnings[2];
  s32 timer;
  HSD_Generator *gen;
  CmSubject *subject;
};
struct grOnett_Building_GroundVars
{
  s16 state;
  s16 next_state;
  s32 hit_count;
  s32 frame;
  u32 timer;
};
struct grOnett_Car_GroundVars
{
  u8 x0_b0 : 1;
  u8 pad0[3];
  HSD_JObj *car_jobjs[4];
  HSD_JObj *unk_jobj;
  Item_GObj *car_items[4];
  u8 pad28[4];
  HSD_JObj *car_jobjs2[4];
  HSD_JObj *unk_jobj2;
  s8 curr_car;
  u8 state_a;
  u8 pad42[2];
  s32 x108;
  u8 pad48[4];
  s32 x110;
  f32 car_speed;
  s8 next_car;
  u8 state_b;
  u8 pad56[2];
  s32 timer_b;
  u8 pad5C[4];
  s32 sub_state_b;
  f32 speed_b;
};
struct grBigBlue_GroundData
{
  u8 index;
  u8 x1;
  s8 x2;
  u8 x3;
  s32 x4;
  f32 x8;
  Vec3 xC;
  Vec3 x18;
  f32 x24;
  f32 x28;
  s32 x2C;
  s32 x30;
  s32 x34;
  Vec3 x38;
  Vec3 x44;
  s32 x50;
};
struct grBigBlue_GroundVars
{
  union 
  {
    u32 x0_w;
    struct 
    {
      u8 x0;
      u8 x1;
      u8 x2;
      u8 x3;
    };
    struct 
    {
      u8 x0_b1 : 1;
      u8 pad[3];
    };
  };
  void *xC8;
  void *xCC;
  f32 xD0;
  HSD_JObj *xD4[3];
  char pad_3[4];
  struct grBigBlue_GroundData data[3];
};
struct grBigBlueRoute_GroundVars
{
  HSD_GObj *xC4;
  void *xC8;
  HSD_Spline *xCC;
  HSD_Spline *xD0;
  HSD_Spline *xD4;
  Vec3 xD8;
  Vec3 xE4;
  Vec3 xF0;
  Vec3 xFC;
  s16 x108;
  s16 x10A;
};
struct grCastle_GroundVars
{
  u32 xC4;
  s16 xC8;
  u8 pad[0xE0 - 0xCC];
  HSD_Spline **xE0;
};
struct grCastle_GroundVars3
{
  u8 pad_0[0x1C];
  DynamicsDesc x1C[12];
};
struct grCastle_GroundVars4
{
  u8 pad_0[0x12];
  s16 xD6;
  s16 xD8;
  s16 xDA;
  s16 xDC;
};
struct grCastle_GroundVars2
{
  HSD_GObj *xC4;
  HSD_GObj *xC8;
  HSD_GObj *xCC;
  s16 xD0;
  s16 xD2;
};
struct grCastle_GroundVars5
{
  s16 xC4;
  s16 xC6;
  u8 pad_C8[4];
  HSD_GObj *xCC;
};
struct grCastle_GroundVars6
{
  s16 xC4;
  s16 xC6;
  s16 xC8;
  u8 pad_CA[2];
  s32 xCC;
};
struct grCastle_GroundVars7
{
  s16 xC4;
  u8 pad_xC6[0xA];
  HSD_GObj *xD0;
  u32 xD4;
  s32 xD8;
};
struct grCastle_Platform
{
  HSD_JObj *jobj;
  f32 pos;
  s16 state;
  s16 timer;
  f32 wind;
};
struct grCastle_GroundVars8
{
  struct grCastle_Platform plat[2];
};
struct grCastle_GroundVars9
{
  u32 xC4;
  u32 xC8;
  u32 xCC;
  u8 pad_xD0[4];
  s16 xD4;
  s16 xD6;
  s16 xD8;
  s16 xDA;
  s16 xDC;
  u8 xDE;
  u8 pad_xDF[1];
  DynamicsDesc dynamics[12];
};
struct grCastle_GroundVars10
{
  s16 xC4;
  u8 pad_C6[2];
  s16 xC8;
  u8 pad_CA[6];
  HSD_JObj *jobjs[5];
  HSD_JObj *effect_a[5];
  HSD_JObj *effect_b[5];
  u32 x10C[5];
  s32 x120[5];
  u8 state[5];
  u8 idx[5];
  u8 pad_7A[2];
  f32 baseY[5];
};
struct grCastle_GroundVars11
{
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
  } xC4;
  u8 pad_01[3];
  s16 xC8;
  s16 xCA;
  u32 xCC;
  u32 xD0;
  u32 xD4;
  u32 xD8;
};
struct grCastle_GroundVars12
{
  u32 xC4[3];
  s16 xD0;
  s16 xD2;
};
struct grPura_GroundVars
{
  u16 xC4;
  s16 xC6;
  HSD_JObj *xC8;
};
struct grPura_GroundVars2
{
  u32 xC4;
  HSD_JObj *xC8;
};
struct Randall
{
  s16 timer;
  HSD_JObj *jobj;
};
struct ShyGuys
{
  s8 count;
  s8 pattern;
  int timer;
};
struct grShrineroute_GroundVars
{
  u16 xC4;
  u16 xC6;
  u16 xC8;
  u16 xCA;
  u16 xCC;
  u16 xCE;
  u16 xD0;
  u8 _pad[0xD4 - 0xD2];
  u32 xD4;
  struct 
  {
    Vec3 offset;
    HSD_JObj *jobj;
  } platforms[3];
  HSD_GObj *symbols[6];
};
struct grShrineroute_GroundVars2
{
  HSD_GObj *xC4;
  HSD_LObj *xC8[20];
  u32 x118[20];
  u32 x168;
  HSD_LObj *x16C;
  HSD_LObj *x170;
};
struct grShrineroute_GroundVars3
{
  HSD_JObj *xC4;
  f32 xC8;
  f32 xCC;
  f32 xD0;
  f32 xD4;
  f32 xD8;
  f32 xDC;
  f32 xE0;
  HSD_JObj *xE4;
};
struct Battlefield
{
  int bg_state;
  int curr_bg;
  int prev_bg;
  int bg_timer;
};
struct Last_GroundVars
{
  float xC4;
  float xC8;
  float xCC;
  float xD0;
  float xD4;
  float xD8;
  float xDC;
  HSD_Generator *xE0;
};
struct grPushOn_GroundVars
{
  void *gobj;
  HSD_LObj *lobjs[20];
  u32 lobj_flags[20];
  s32 count;
  HSD_LObj *point_light;
  HSD_LObj *spot_light;
};
struct ScrollVars
{
  u8 x00;
  u8 pad_01[3];
  Vec3 x04;
  Vec3 x10;
  Vec3 x1C;
  union 
  {
    HSD_JObj *scroll_jobj;
    HSD_GObj *anim_gobj;
  };
  HSD_JObj *cam_jobj;
  HSD_JObj *ctr_jobj;
  HSD_JObj *x34[3];
  HSD_JObj *x40;
};
struct grHomeRun_GroundVars
{
  u16 xC4;
  u16 xC6;
  int xC8;
  int xCC;
  float xD0;
  u8 pad_D4[0x14];
  union 
  {
    u8 xE8;
    struct 
    {
      u8 xE8_b0 : 1;
      u8 xE8_b1 : 1;
      u8 xE8_b2 : 1;
      u8 xE8_b3 : 1;
      u8 xE8_b4 : 1;
      u8 xE8_b5 : 1;
      u8 xE8_b6 : 1;
      u8 xE8_b7 : 1;
    };
  };
};
struct Map_GroundVars
{
  u32 xC4_b0 : 1;
  u32 xC4_b1 : 1;
  u32 xC4_b2_25 : 16;
  u32 xC4_b26 : 1;
  u32 xC4_b27 : 1;
  u32 xC4_b28 : 1;
  u32 xC4_b29 : 1;
  u32 xC4_b30 : 1;
  u32 xC4_b31 : 1;
  float xC8;
  HSD_GObj *lv_gobj[6];
  float xE4;
  float xE8;
  float xEC;
  float xF0;
  float xF4;
  float xF8;
  float xFC;
  float x100;
  float x104;
  u8 pad[0x130 - 0x108];
  struct grRCruise_VanishEntry *chikuwa;
  struct grRCruise_VanishEntry *vanish;
};
struct grOldYoshi_Cloud
{
  u32 xC4_0123 : 4;
  u32 xC4_4 : 1;
  u32 xC4_567 : 8;
  HSD_JObj *xC8;
  float xCC;
  float xD0;
  float xD4;
};
struct grOldYoshi_Cloud_GroundVars
{
  struct grOldYoshi_Cloud cloud[3];
};
struct grOldYoshi_Guest_GroundVars
{
  s16 xC4;
  s16 xC6;
};
struct Ground
{
  int x0;
  HSD_GObj *gobj;
  HSD_GObjEvent x8_callback;
  HSD_GObjEvent xC_callback;
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
  } x10_flags;
  struct 
  {
    u8 b012 : 3;
    u8 b3 : 1;
    u8 b4 : 1;
    u8 b5 : 1;
    u8 b6 : 1;
    u8 b7 : 1;
  } x11_flags;
  InternalStageId map_id;
  HSD_GObj *x18;
  HSD_GObjEvent x1C_callback;
  int x20[8];
  Vec3 self_vel;
  Vec3 cur_pos;
  int x58;
  int x5C;
  int x60;
  int x64;
  int x68;
  GXColor x6C;
  int x70;
  char pad_74[0xC0 - 0x74];
  f32 xC0;
  union 
  {
    union GroundVars
    {
      char pad_0[0x204 - 0xC4];
      struct grArwing_GroundVars arwing;
      struct grBigBlue_GroundVars bigblue;
      struct grBigBlueRoute_GroundVars bigblueroute;
      struct grCastle_GroundVars castle;
      struct grCastle_GroundVars2 castle2;
      struct grCastle_GroundVars3 castle3;
      struct grCastle_GroundVars4 castle4;
      struct grCastle_GroundVars5 castle5;
      struct grCastle_GroundVars6 castle6;
      struct grCastle_GroundVars7 castle7;
      struct grCastle_GroundVars8 castle8;
      struct grCastle_GroundVars9 castle9;
      struct grCastle_GroundVars10 castle10;
      struct grCastle_GroundVars11 castle11;
      struct grCastle_GroundVars12 castle12;
      struct grCorneria_GroundVars corneria;
      struct grCorneria_GroundVars2 corneria2;
      struct grGreatBay_GroundVars greatbay;
      struct grGreatBay_GroundVars2 greatbay2;
      struct grGreatBay_GroundVars3 greatbay3;
      struct grGreatBay_GroundVars4 greatbay4;
      struct grFigureGet_GroundVars figureget;
      struct GroundVars_flatzone flatzone;
      struct GroundVars_flatzone2 flatzone2;
      struct grFourside_GroundVars fourside;
      struct grFourside_CraneVars foursideCrane;
      struct grFourside_UfoVars foursideUfo;
      struct grFourside_GroundVars2 fourside2;
      struct grGreens_GroundVars greens;
      struct grGreens_GroundVars2 greens2;
      struct grGarden_GroundVars garden;
      struct grGarden_GroundVars2 garden2;
      struct grIceMt_GroundVars icemt;
      struct grIceMt_GroundVars2 icemt2;
      struct grInishie1_GroundVars inishie1;
      struct grInishie1_GroundVars2 inishie12;
      struct grInishie1_GroundVars3 inishie13;
      struct grInishie2_GroundVars inishie2;
      struct grInishie2_GroundVars2 inishie22;
      struct grInishie2_GroundVars3 inishie23;
      struct grOldKongo_GroundVars oldkongo;
      struct grOldPupupu_GroundVars oldpupupu;
      struct grOldPupupu_GroundVars2 oldpupupu2;
      struct grOldYoshi_Cloud_GroundVars oldyoshicloud;
      struct grOldYoshi_Guest_GroundVars oldyoshiguest;
      struct GroundVars_izumi izumi;
      struct GroundVars_izumi2 izumi2;
      struct GroundVars_izumi3 izumi3;
      struct grKinokoRoute_GroundVars kinokoroute;
      struct grKinokoRoute_GroundVars2 kinokoroute2;
      struct grKongo_GroundVars kongo;
      struct grKongo_GroundVars2 kongo2;
      struct grKongo_GroundVars3 kongo3;
      struct grKraid_GroundVars kraid;
      struct grKraid_GroundVars2 kraid2;
      struct grMuteCity_GroundVars mutecity;
      struct grMuteCity_GroundVars2 mutecity2;
      struct grOnett_GroundVars onett;
      struct grOnett_Building_GroundVars onett_building;
      struct grOnett_Car_GroundVars onettcar;
      struct grPura_GroundVars pura;
      struct grPura_GroundVars2 pura2;
      struct grRCruise_GroundVars rcruise;
      struct grRCruise_GroundVars2 rcruise2;
      struct grShrineroute_GroundVars shrineroute;
      struct grShrineroute_GroundVars2 shrineroute2;
      struct grShrineroute_GroundVars3 shrineroute3;
      struct grSmashTaunt_GroundVars smashtaunt;
      struct GroundVars_unk unk;
      struct grHomeRun_GroundVars homerun;
      struct grVenom_GroundVars venom;
      struct grVenom_GroundVars2 venom2;
      struct grYorster_GroundVars yorster;
      struct grZebes_GroundVars zebes;
      struct grZebes_GroundVars2 zebes2;
      struct grZebes_GroundVars3 zebes3;
      struct grZebes_GroundVars4 zebes4;
      struct grZebes_GroundVars5 zebes5;
    } gv;
    union GroundVars2
    {
      struct grStadium_GroundVars stadium;
      struct grStadium_type9_GroundVars stadium9;
      struct grStadium_Display display;
      struct Randall randall;
      struct ShyGuys shyguys;
      struct Battlefield battle;
      struct Last_GroundVars last;
      struct Map_GroundVars map;
      struct grPushOn_GroundVars pushon;
      struct ScrollVars scroll;
    } u;
  };
};
typedef struct _HSD_Class
{
  struct _HSD_ClassInfo *class_info;
} HSD_Class;
typedef struct _HSD_ClassInfoHead
{
  void (*info_init)(void);
  u32 flags;
  char *library_name;
  char *class_name;
  s16 obj_size;
  s16 info_size;
  struct _HSD_ClassInfo *parent;
  struct _HSD_ClassInfo *next;
  struct _HSD_ClassInfo *child;
  u32 nb_exist;
  u32 nb_peak;
} HSD_ClassInfoHead;
typedef struct _HSD_ClassInfo
{
  struct _HSD_ClassInfoHead head;
  HSD_Class *(*alloc)(struct _HSD_ClassInfo *c);
  int (*init)(struct _HSD_Class *c);
  void (*release)(struct _HSD_Class *c);
  void (*destroy)(struct _HSD_Class *c);
  void (*amnesia)(struct _HSD_ClassInfo *c);
} HSD_ClassInfo;
void __assert(char *, u32, char *);
typedef struct _HSD_SList HSD_SList;
struct HSD_Obj
{
  struct _HSD_Class parent;
  u16 ref_count;
  u16 ref_count_individual;
};
typedef struct _HSD_ObjInfo
{
  struct _HSD_ClassInfo parent;
} HSD_ObjInfo;
typedef struct _HSD_FObj HSD_FObj;
struct HSD_AObj
{
  u32 flags;
  f32 curr_frame;
  f32 rewind_frame;
  f32 end_frame;
  f32 framerate;
  HSD_FObj *fobj;
  struct HSD_Obj *hsd_obj;
};
struct HSD_JObj;
struct HSD_JObj
{
  HSD_Obj object;
  HSD_JObj *next;
  HSD_JObj *parent;
  HSD_JObj *child;
  u32 flags;
  union 
  {
    HSD_SList *ptcl;
    struct HSD_DObj *dobj;
    HSD_Spline *spline;
  } u;
  Quaternion rotate;
  Vec3 scale;
  Vec3 translate;
  Mtx mtx;
  Vec3 *scl;
  MtxPtr envelopemtx;
  HSD_AObj *aobj;
  HSD_RObj *robj;
  u32 id;
};
void HSD_JObjSetMtxDirtySub(HSD_JObj *);
inline static bool HSD_JObjMtxIsDirty(HSD_JObj *jobj)
{
  bool result;
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 564, "jobj"));
  result = 0;
  if ((!(jobj->flags & (1 << 23))) && (jobj->flags & (1 << 6)))
  {
    result = 1;
  }
  return result;
}

inline static void HSD_JObjSetTranslate(HSD_JObj *jobj, Vec3 *translate)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 916, "jobj"));
  (translate) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 917, "translate"));
  jobj->translate = *translate;
  if (!(jobj->flags & (1 << 25)))
  {
    {
      if ((jobj != 0L) && (!HSD_JObjMtxIsDirty(jobj)))
      {
        HSD_JObjSetMtxDirtySub(jobj);
      }
    }
    ;
  }
}

inline static void HSD_JObjGetTranslation(HSD_JObj *jobj, Vec3 *translate)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 979, "jobj"));
  (translate) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 980, "translate"));
  *translate = jobj->translate;
}

struct HSD_GObj
{
  u16 classifier;
  u8 p_link;
  u8 gx_link;
  u8 p_priority;
  u8 render_priority;
  u8 obj_kind;
  u8 user_data_kind;
  HSD_GObj *next;
  HSD_GObj *prev;
  HSD_GObj *next_gx;
  HSD_GObj *prev_gx;
  HSD_GObjProc *proc;
  GObj_RenderFunc render_cb;
  u64 gxlink_prios;
  void *hsd_obj;
  void *user_data;
  void (*user_data_remove_func)(void *data);
  void *x34_unk;
};
inline static void *HSD_GObjGetUserData(HSD_GObj *gobj)
{
  return gobj->user_data;
}

inline static void *HSD_GObjGetHSDObj(HSD_GObj *gobj)
{
  return gobj->hsd_obj;
}

void grVenom_8020362C(void);
HSD_GObj *grVenom_80203EAC(int);
void grVenom_80204284(Ground_GObj *);
void grCorneria_801E25C4(HSD_GObj *, void *, int, int, int);
HSD_GObj *Ground_801C2BA4(s32);
bool Ground_801C2FE0(Ground_GObj *);
void Ground_801C39C0(void);
void Ground_801C3BB4(void);
void un_802FF570(void);
void un_802FF620(void);
void ifStatus_802F6898(void);
void ifStatus_802F68F0(void);
void lb_800115F4(void);
struct HSD_LightPoint
{
  f32 cutoff;
  u32 point_func;
  f32 ref_br;
  f32 ref_dist;
  u32 dist_func;
};
struct HSD_LightSpot
{
  f32 cutoff;
  u32 spot_func;
  f32 ref_br;
  f32 ref_dist;
  u32 dist_func;
};
struct HSD_LightAttn
{
  f32 a0;
  f32 a1;
  f32 a2;
  f32 k0;
  f32 k1;
  f32 k2;
};
struct HSD_LObj
{
  HSD_Obj parent;
  u16 flags;
  u16 priority;
  HSD_LObj *next;
  GXColor color;
  GXColor hw_color;
  HSD_WObj *position;
  HSD_WObj *interest;
  union 
  {
    HSD_LightPoint point;
    HSD_LightSpot spot;
    HSD_LightAttn attn;
  } u;
  f32 shininess;
  Vec3 lvec;
  HSD_AObj *aobj;
  GXLightID id;
  GXLightObj lightobj;
  GXLightID spec_id;
  GXLightObj spec_lightobj;
};
void grVenom_8020362C(void);
Ground_GObj *grVenom_80203EAC(int gobj_id);
void grVenom_80204284(Ground_GObj *gobj)
{
  s32 new_var;
  Ground *gp;
  Ground_GObj *new_var2;
  HSD_JObj *src_jobj;
  HSD_JObj *dst_jobj;
  u32 pad2;
  Ground_GObj *other_gobj;
  Vec3 pos;
  s32 timer;
  u32 pad;
  gp = (Ground *) HSD_GObjGetUserData(gobj);
  src_jobj = HSD_GObjGetHSDObj(gobj);
  dst_jobj = (HSD_JObj *) ((HSD_GObj *) gp->gv.venom.xC4)->hsd_obj;
  HSD_JObjSetTranslate(dst_jobj, &pos);
  HSD_JObjGetTranslation(src_jobj, &pos);
  new_var = (s32) gp->gv.venom.xC8;
  Ground_801C39C0();
  Ground_801C3BB4();
  timer = gp->gv.venom.xC8;
  if (timer > 0)
  {
    gp->gv.venom.xC8 = timer + 1;
    if (new_var >= 0x3C)
    {
      if (((s32) gp->gv.venom.xC8) == 0x3C)
      {
        ifStatus_802F6898();
        new_var2 = (Ground_GObj *) grVenom_80203EAC(1);
        un_802FF570();
        other_gobj = new_var2;
        if (other_gobj != 0L)
        {
          Ground *other_gp = (Ground *) HSD_GObjGetUserData(other_gobj);
          grCorneria_801E25C4(other_gobj, &other_gp->gv.venom.xC4, 4, 6, 0x6B6CC);
        }
      }
      else
      {
        ifStatus_802F6898();
        un_802FF570();
        if (Ground_801C2BA4(1) == 0L)
        {
          ifStatus_802F68F0();
          un_802FF620();
          gp->gv.venom.xC8 = -1;
        }
      }
    }
  }
  lb_800115F4();
  grVenom_8020362C();
  Ground_801C2FE0(gobj);
}
