
typedef int bool;
typedef unsigned short wchar_t;
typedef signed int ssize_t;
typedef unsigned long size_t;
typedef unsigned int usize_t;
typedef signed int intptr_t;
typedef unsigned int uintptr_t;
typedef signed char s8;
typedef unsigned char u8;
typedef signed short int s16;
typedef unsigned short int u16;
typedef signed long s32;
typedef unsigned long u32;
typedef signed long long int s64;
typedef unsigned long long int u64;
typedef float f32;
typedef double f64;
typedef volatile f32 vf32;
typedef volatile f64 vf64;
typedef char *Ptr;
typedef int BOOL;
f32 powf(f32 x, f32 y);
f32 tanf(f32);
extern const unsigned char __ctype_map[];
extern const unsigned char __lower_map[];
extern const unsigned char __upper_map[];
inline int isalpha(int c)
{
  return (int) (__ctype_map[(unsigned char) c] & (0x40 | 0x80));
}

inline int isdigit(int c)
{
  return (int) (__ctype_map[(unsigned char) c] & 0x10);
}

inline int isspace(int c)
{
  return (int) (__ctype_map[(unsigned char) c] & (0x02 | 0x04));
}

inline int isupper(int c)
{
  return (int) (__ctype_map[(unsigned char) c] & 0x80);
}

inline int isxdigit(int c)
{
  return (int) (__ctype_map[(unsigned char) c] & 0x20);
}

int toupper(int c);
int tolower(int c);
typedef struct 
{
  char gpr;
  char fpr;
  char reserved[2];
  char *input_arg_area;
  char *reg_save_area;
} __va_list[1];
typedef __va_list va_list;
extern void __builtin_va_info(void *);
void *__va_arg(va_list v_list, unsigned char type);
typedef unsigned long __file_handle;
typedef unsigned long fpos_t;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wtypedef-redefinition"
typedef unsigned short wchar_t;
#pragma clang diagnostic pop
enum __io_modes
{
  __read = 1,
  __write = 2,
  __read_write = 3,
  __append = 4
};
enum __file_kinds
{
  __closed_file,
  __disk_file,
  __console_file,
  __unavailable_file
};
enum __file_orientation
{
  __unoriented,
  __char_oriented,
  __wide_oriented
};
enum __io_results
{
  __no_io_error,
  __io_error,
  __io_EOF
};
typedef struct 
{
  unsigned int open_mode : 2;
  unsigned int io_mode : 3;
  unsigned int buffer_mode : 2;
  unsigned int file_kind : 3;
  unsigned int file_orientation : 2;
  unsigned int binary_io : 1;
} __file_modes;
enum __io_states
{
  __neutral,
  __writing,
  __reading,
  __rereading
};
typedef struct 
{
  unsigned int io_state : 3;
  unsigned int free_buffer : 1;
  unsigned char eof;
  unsigned char error;
} __file_state;
typedef void (*__idle_proc)(void);
typedef int (*__pos_proc)(__file_handle file, fpos_t *position, int mode, __idle_proc idle_proc);
typedef int (*__io_proc)(__file_handle file, unsigned char *buff, size_t *count, __idle_proc idle_proc);
typedef int (*__close_proc)(__file_handle file);
typedef struct _IO_FILE
{
  __file_handle handle;
  __file_modes mode;
  __file_state state;
  unsigned char char_buffer;
  unsigned char char_buffer_overflow;
  unsigned char ungetc_buffer[2];
  wchar_t ungetwc_buffer[2];
  unsigned long position;
  unsigned char *buffer;
  unsigned long buffer_size;
  unsigned char *buffer_ptr;
  unsigned long buffer_len;
  unsigned long buffer_alignment;
  unsigned long saved_buffer_len;
  unsigned long buffer_pos;
  __pos_proc position_proc;
  __io_proc read_proc;
  __io_proc write_proc;
  __close_proc close_proc;
  __idle_proc idle_proc;
} FILE;
typedef struct 
{
  char *CharStr;
  size_t MaxCharCount;
  size_t CharsWritten;
} __OutStrCtrl;
typedef struct 
{
  char *NextChar;
  int NullCharDetected;
} __InStrCtrl;
enum __ReadProcActions
{
  __GetAChar,
  __UngetAChar,
  __TestForError
};
int __StringRead(void *str, int ch, int behavior);
extern FILE __files[3];
int sprintf(char *s, const char *format, ...);
int vprintf(const char *format, va_list arg);
int vsprintf(char *s, const char *format, va_list arg);
size_t fwrite(const void *, size_t memb_size, size_t num_memb, FILE *);
char *strcpy(char *dst, const char *src);
char *strncpy(char *dst, const char *src, size_t num);
char *strcat(char *dest, const char *src);
size_t strlen(const char *s);
int strcmp(const char *s1, const char *s2);
int strncmp(const char *s1, const char *s2, size_t n);
char *strchr(const char *str, int chr);
void *memchr(const void *p, int val, size_t n);
int memcmp(const void *p1, const void *p2, size_t n);
void *memset(void *dst, int val, size_t n);
void *memcpy(void *dst, const void *src, size_t n);
void *memmove(void *dst, const void *src, size_t n);
typedef int enum_t;
typedef void (*Event)(void);
typedef s32 M2C_UNK;
typedef s8 M2C_UNK8;
typedef s16 M2C_UNK16;
typedef s32 M2C_UNK32;
typedef s64 M2C_UNK64;
typedef s64 OSTime;
typedef u32 OSTick;
typedef s16 __OSInterrupt;
typedef u32 OSInterruptMask;
typedef struct OSContext
{
  u32 gpr[32];
  u32 cr;
  u32 lr;
  u32 ctr;
  u32 xer;
  f64 fpr[32];
  u32 fpscr_pad;
  u32 fpscr;
  u32 srr0;
  u32 srr1;
  u16 mode;
  u16 state;
  u32 gqr[8];
  f64 psf[32];
} OSContext;
u32 OSGetStackPointer(void);
void OSDumpContext(OSContext *context);
void OSLoadContext(OSContext *context);
u32 OSSaveContext(OSContext *context);
void OSClearContext(OSContext *context);
OSContext *OSGetCurrentContext(void);
void OSSetCurrentContext(OSContext *context);
void OSLoadFPUContext(OSContext *fpuContext);
void OSSaveFPUContext(OSContext *fpuContext);
u32 OSSwitchStack(u32 newsp);
int OSSwitchFiber(u32 pc, u32 newsp);
void OSInitContext(OSContext *context, u32 pc, u32 newsp);
void OSFillFPUContext(OSContext *context);
typedef void (*__OSInterruptHandler)(__OSInterrupt interrupt, OSContext *context);
typedef struct OSAlarm OSAlarm;
typedef void (*OSAlarmHandler)(OSAlarm *alarm, OSContext *context);
struct OSAlarm
{
  OSAlarmHandler handler;
  u32 tag;
  OSTime fire;
  OSAlarm *prev;
  OSAlarm *next;
  OSTime period;
  OSTime start;
};
BOOL OSCheckAlarmQueue(void);
void OSInitAlarm(void);
void OSCreateAlarm(OSAlarm *alarm);
void OSSetAlarm(OSAlarm *alarm, OSTime tick, OSAlarmHandler handler);
void OSSetAbsAlarm(struct OSAlarm *alarm, long long time, void (*handler)(struct OSAlarm *, struct OSContext *));
void OSSetPeriodicAlarm(OSAlarm *alarm, OSTime start, OSTime period, OSAlarmHandler handler);
void OSCancelAlarm(OSAlarm *alarm);
typedef int OSHeapHandle;
extern volatile OSHeapHandle __OSCurrHeap;
void *OSAllocFromHeap(int heap, unsigned long size);
void *OSAllocFixed(void *rstart, void *rend);
void OSFreeToHeap(int heap, void *ptr);
int OSSetCurrentHeap(int heap);
void *OSInitAlloc(void *arenaStart, void *arenaEnd, int maxHeaps);
int OSCreateHeap(void *start, void *end);
void OSDestroyHeap(int heap);
void OSAddToHeap(int heap, void *start, void *end);
long OSCheckHeap(int heap);
unsigned long OSReferentSize(void *ptr);
void OSDumpHeap(int heap);
void OSVisitAllocated(void (*visitor)(void *, unsigned long));
void DCInvalidateRange(void *addr, u32 nBytes);
void DCFlushRange(void *addr, u32 nBytes);
void DCStoreRange(void *addr, u32 nBytes);
void DCFlushRangeNoSync(void *addr, u32 nBytes);
void DCStoreRangeNoSync(void *addr, u32 nBytes);
void DCZeroRange(void *addr, u32 nBytes);
void DCTouchRange(void *addr, u32 nBytes);
void ICInvalidateRange(void *addr, u32 nBytes);
void LCEnable(void);
void LCDisable(void);
void LCLoadBlocks(void *destTag, void *srcAddr, u32 numBlocks);
void LCStoreBlocks(void *destAddr, void *srcTag, u32 numBlocks);
u32 LCLoadData(void *destAddr, void *srcAddr, u32 nBytes);
u32 LCStoreData(void *destAddr, void *srcAddr, u32 nBytes);
u32 LCQueueLength(void);
void LCQueueWait(u32 len);
void LCFlushQueue(void);
void __OSCacheInit(void);
void DCFlashInvalidate(void);
void DCEnable(void);
void DCDisable(void);
void DCFreeze(void);
void DCUnfreeze(void);
void DCTouchLoad(void *addr);
void DCBlockZero(void *addr);
void DCBlockStore(void *addr);
void DCBlockFlush(void *addr);
void DCBlockInvalidate(void *addr);
typedef u16 OSError;
typedef void (*OSErrorHandler)(OSError error, OSContext *context, ...);
extern OSErrorHandler OSErrorTable[15];
OSErrorHandler OSSetErrorHandler(OSError error, OSErrorHandler handler);
typedef u8 __OSException;
typedef void (*__OSExceptionHandler)(__OSException exception, OSContext *context);
__OSExceptionHandler __OSSetExceptionHandler(__OSException exception, __OSExceptionHandler handler);
__OSExceptionHandler __OSGetExceptionHandler(__OSException exception);
typedef struct OSFontHeader
{
  u16 fontType;
  u16 firstChar;
  u16 lastChar;
  u16 invalChar;
  u16 ascent;
  u16 descent;
  u16 width;
  u16 leading;
  u16 cellWidth;
  u16 cellHeight;
  u32 sheetSize;
  u16 sheetFormat;
  u16 sheetColumn;
  u16 sheetRow;
  u16 sheetWidth;
  u16 sheetHeight;
  u16 widthTable;
  u32 sheetImage;
  u32 sheetFullSize;
  u8 c0;
  u8 c1;
  u8 c2;
  u8 c3;
} OSFontHeader;
u16 OSGetFontEncode(void);
BOOL OSInitFont(OSFontHeader *fontData);
u32 OSLoadFont(OSFontHeader *fontData, void *temp);
char *OSGetFontTexture(char *string, void **image, s32 *x, s32 *y, s32 *width);
char *OSGetFontWidth(char *string, s32 *width);
char *OSGetFontTexel(char *string, void *image, s32 pos, s32 stride, s32 *width);
void ICFlashInvalidate(void);
void ICEnable(void);
void ICDisable(void);
void ICFreeze(void);
void ICUnfreeze(void);
void ICBlockInvalidate(void *addr);
void ICSync(void);
extern volatile __OSInterrupt __OSLastInterrupt;
extern volatile u32 __OSLastInterruptSrr0;
extern volatile OSTime __OSLastInterruptTime;
__OSInterruptHandler __OSSetInterruptHandler(__OSInterrupt interrupt, __OSInterruptHandler handler);
__OSInterruptHandler __OSGetInterruptHandler(__OSInterrupt interrupt);
void __OSDispatchInterrupt(__OSException exception, OSContext *context);
OSInterruptMask OSGetInterruptMask(void);
OSInterruptMask OSSetInterruptMask(OSInterruptMask mask);
OSInterruptMask __OSMaskInterrupts(OSInterruptMask mask);
OSInterruptMask __OSUnmaskInterrupts(OSInterruptMask mask);
void L2Enable(void);
void L2Disable(void);
void L2GlobalInvalidate(void);
void L2SetDataOnly(BOOL dataOnly);
void L2SetWriteThrough(BOOL writeThrough);
void LCAllocOneTag(BOOL invalidate, void *tag);
void LCAllocTags(BOOL invalidate, void *startTag, u32 numBlocks);
void LCAlloc(void *addr, u32 nBytes);
void LCAllocNoInvalidate(void *addr, u32 nBytes);
typedef s32 OSPriority;
struct OSThread;
struct OSMutex;
struct OSMutexQueue;
typedef struct OSThread OSThread;
typedef struct OSThreadQueue
{
  struct OSThread *head;
  struct OSThread *tail;
} OSThreadQueue;
typedef struct OSThreadLink
{
  struct OSThread *next;
  struct OSThread *prev;
} OSThreadLink;
typedef struct OSMutexQueue
{
  struct OSMutex *head;
  struct OSMutex *tail;
} OSMutexQueue;
typedef struct OSMutexLink
{
  struct OSMutex *next;
  struct OSMutex *prev;
} OSMutexLink;
typedef struct OSThread
{
  struct OSContext context;
  u16 state;
  u16 attr;
  s32 suspend;
  OSPriority priority;
  OSPriority base;
  void *val;
  struct OSThreadQueue *queue;
  struct OSThreadLink link;
  struct OSThreadQueue queueJoin;
  struct OSMutex *mutex;
  struct OSMutexQueue queueMutex;
  struct OSThreadLink linkActive;
  u8 *stackBase;
  u32 *stackEnd;
} OSThread;
enum OS_THREAD_STATE
{
  OS_THREAD_STATE_READY = 1,
  OS_THREAD_STATE_RUNNING = 2,
  OS_THREAD_STATE_WAITING = 4,
  OS_THREAD_STATE_MORIBUND = 8
};
void OSInitThreadQueue(OSThreadQueue *queue);
void OSSleepThread(OSThreadQueue *queue);
void OSWakeupThread(OSThreadQueue *queue);
s32 OSSuspendThread(OSThread *thread);
s32 OSResumeThread(OSThread *thread);
void OSCancelThread(OSThread *thread);
OSThread *OSGetCurrentThread(void);
s32 OSEnableScheduler(void);
s32 OSDisableScheduler(void);
long OSCheckActiveThreads(void);
int OSCreateThread(struct OSThread *thread, void *(*func)(void *), void *param, void *stack, unsigned long stackSize, long priority, unsigned short attr);
struct OSMessageQueue
{
  struct OSThreadQueue queueSend;
  struct OSThreadQueue queueReceive;
  void *msgArray;
  long msgCount;
  long firstIndex;
  long usedCount;
};
void OSInitMessageQueue(struct OSMessageQueue *mq, void *msgArray, long msgCount);
int OSSendMessage(struct OSMessageQueue *mq, void *msg, long flags);
int OSReceiveMessage(struct OSMessageQueue *mq, void *msg, long flags);
int OSJamMessage(struct OSMessageQueue *mq, void *msg, long flags);
typedef struct OSModuleHeader OSModuleHeader;
typedef u32 OSModuleID;
typedef struct OSModuleQueue OSModuleQueue;
typedef struct OSModuleLink OSModuleLink;
typedef struct OSModuleInfo OSModuleInfo;
typedef struct OSSectionInfo OSSectionInfo;
typedef struct OSImportInfo OSImportInfo;
typedef struct OSRel OSRel;
struct OSModuleQueue
{
  OSModuleInfo *head;
  OSModuleInfo *tail;
};
struct OSModuleLink
{
  OSModuleInfo *next;
  OSModuleInfo *prev;
};
struct OSModuleInfo
{
  OSModuleID id;
  OSModuleLink link;
  u32 numSections;
  u32 sectionInfoOffset;
  u32 nameOffset;
  u32 nameSize;
  u32 version;
};
struct OSModuleHeader
{
  OSModuleInfo info;
  u32 bssSize;
  u32 relOffset;
  u32 impOffset;
  u32 impSize;
  u8 prologSection;
  u8 epilogSection;
  u8 unresolvedSection;
  u8 bssSection;
  u32 prolog;
  u32 epilog;
  u32 unresolved;
};
struct OSSectionInfo
{
  u32 offset;
  u32 size;
};
struct OSImportInfo
{
  OSModuleID id;
  u32 offset;
};
struct OSRel
{
  u16 offset;
  u8 type;
  u8 section;
  u32 addend;
};
void OSSetStringTable(const void *stringTable);
BOOL OSLink(OSModuleInfo *newModule, void *bss);
BOOL OSUnlink(OSModuleInfo *oldModule);
OSModuleInfo *OSSearchModule(void *ptr, u32 *section, u32 *offset);
void OSNotifyLink(void);
void OSNotifyUnlink(void);
typedef struct OSMutex
{
  OSThreadQueue queue;
  OSThread *thread;
  s32 count;
  OSMutexLink link;
} OSMutex;
struct OSCond
{
  OSThreadQueue queue;
};
void OSInitMutex(struct OSMutex *mutex);
void OSLockMutex(struct OSMutex *mutex);
void OSUnlockMutex(struct OSMutex *mutex);
BOOL OSTryLockMutex(struct OSMutex *mutex);
void OSInitCond(struct OSCond *cond);
void OSWaitCond(struct OSCond *cond, struct OSMutex *mutex);
void OSSignalCond(struct OSCond *cond);
typedef void (*RunCallback)(void);
void Run(RunCallback);
void __OSReboot(u32 resetCode, u32 bootDol);
struct OSResetFunctionQueue
{
  struct OSResetFunctionInfo *head;
  struct OSResetFunctionInfo *tail;
};
typedef BOOL (*OSResetFunction)(BOOL);
typedef struct OSResetFunctionInfo OSResetFunctionInfo;
struct OSResetFunctionInfo
{
  OSResetFunction func;
  u32 priority;
  OSResetFunctionInfo *next;
  OSResetFunctionInfo *prev;
};
void OSRegisterResetFunction(OSResetFunctionInfo *info);
void OSUnregisterResetFunction(OSResetFunctionInfo *info);
void OSResetSystem(int reset, u32 resetCode, BOOL forceMenu);
unsigned long OSGetResetCode();
typedef void (*OSResetCallback)(void);
OSResetCallback OSSetResetCallback(OSResetCallback callback);
BOOL OSGetResetSwitchState();
BOOL OSGetResetButtonState(void);
struct SramControl
{
  unsigned char sram[64];
  unsigned long offset;
  int enabled;
  int locked;
  int sync;
  void (*callback)();
};
typedef struct OSSram
{
  unsigned short checkSum;
  unsigned short checkSumInv;
  unsigned long ead0;
  unsigned long ead1;
  unsigned long counterBias;
  signed char displayOffsetH;
  unsigned char ntd;
  unsigned char language;
  unsigned char flags;
} OSSram;
typedef struct OSSramEx
{
  unsigned char flashID[2][12];
  unsigned long wirelessKeyboardID;
  unsigned short wirelessPadID[4];
  unsigned char dvdErrorCode;
  unsigned char _padding0;
  unsigned char flashIDCheckSum[2];
  unsigned char _padding1[4];
} OSSramEx;
unsigned long OSGetSoundMode();
void OSSetSoundMode(unsigned long mode);
unsigned long OSGetVideoMode();
void OSSetVideoMode(unsigned long mode);
unsigned char OSGetLanguage();
void OSSetLanguage(unsigned char language);
unsigned long OSGetProgressiveMode(void);
void OSSetProgressiveMode(u32 mode);
u16 OSGetWirelessID(s32);
typedef void (*SITypeAndStatusCallback)(long chan, unsigned long type);
struct SIControl
{
  long chan;
  unsigned long poll;
  unsigned long inputBytes;
  void *input;
  void (*callback)(long, unsigned long, struct OSContext *);
};
struct SIPacket
{
  long chan;
  void *output;
  unsigned long outputBytes;
  void *input;
  unsigned long inputBytes;
  void (*callback)(long, unsigned long, struct OSContext *);
  long long time;
};
int SIBusy();
BOOL SIIsChanBusy(int chan);
BOOL SIRegisterPollingHandler(__OSInterruptHandler);
BOOL SIUnregisterPollingHandler(__OSInterruptHandler);
void SIInit();
unsigned long SISync();
unsigned long SIGetStatus(int);
void SISetCommand(long chan, unsigned long command);
unsigned long SIGetCommand(long chan);
void SITransferCommands();
unsigned long SISetXY(unsigned long x, unsigned long y);
unsigned long SIEnablePolling(unsigned long poll);
unsigned long SIDisablePolling(unsigned long poll);
int SIGetResponse(long chan, void *data);
int SITransfer(long chan, void *output, unsigned long outputBytes, void *input, unsigned long inputBytes, void (*callback)(long, unsigned long, struct OSContext *), OSTime delay);
unsigned long SIGetType(long chan);
unsigned long SIGetTypeAsync(long chan, SITypeAndStatusCallback callback);
struct OSStopwatch
{
  char *name;
  long long total;
  unsigned long hits;
  long long min;
  long long max;
  long long last;
  int running;
};
void OSInitStopwatch(struct OSStopwatch *sw, char *name);
void OSStartStopwatch(struct OSStopwatch *sw);
void OSStopStopwatch(struct OSStopwatch *sw);
long long OSCheckStopwatch(struct OSStopwatch *sw);
void OSResetStopwatch(struct OSStopwatch *sw);
void OSDumpStopwatch(struct OSStopwatch *sw);
u32 OSGetPhysicalMemSize(void);
u32 OSGetConsoleSimulatedMemSize(void);
unsigned long OSGetConsoleType(void);
void OSInit(void);
void *OSGetArenaHi(void);
void *OSGetArenaLo(void);
void OSSetArenaHi(void *);
void OSSetArenaLo(void *);
void *OSAllocFromArenaLo(u32 size, u32 align);
void *OSAllocFromArenaHi(u32 size, u32 align);
u32 OSGetPhysicalMemSize(void);
void __OSPSInit();
u32 __OSGetDIConfig(void);
typedef struct OSCalendarTime
{
  int sec;
  int min;
  int hour;
  int mday;
  int mon;
  int year;
  int wday;
  int yday;
  int msec;
  int usec;
} OSCalendarTime;
typedef struct DVDDiskID
{
  char gameName[4];
  char company[2];
  u8 diskNumber;
  u8 gameVersion;
  u8 streaming;
  u8 streamingBufSize;
  u8 padding[22];
} DVDDiskID;
typedef struct DVDCommandBlock DVDCommandBlock;
typedef void (*DVDCBCallback)(s32 result, DVDCommandBlock *block);
struct DVDCommandBlock
{
  DVDCommandBlock *next;
  DVDCommandBlock *prev;
  u32 command;
  s32 state;
  u32 offset;
  u32 length;
  void *addr;
  u32 currTransferSize;
  u32 transferredSize;
  DVDDiskID *id;
  DVDCBCallback callback;
  void *userData;
};
typedef struct DVDFileInfo DVDFileInfo;
typedef void (*DVDCallback)(s32 result, DVDFileInfo *fileInfo);
struct DVDFileInfo
{
  DVDCommandBlock cb;
  u32 startAddr;
  u32 length;
  DVDCallback callback;
};
typedef struct 
{
  u32 entryNum;
  u32 location;
  u32 next;
} DVDDir;
typedef struct 
{
  u32 entryNum;
  BOOL isDir;
  char *name;
} DVDDirEntry;
typedef struct DVDBB2
{
  u32 bootFilePosition;
  u32 FSTPosition;
  u32 FSTLength;
  u32 FSTMaxLength;
  void *FSTAddress;
  u32 userPosition;
  u32 userLength;
  u32 padding0;
} DVDBB2;
typedef struct DVDDriveInfo
{
  u16 revisionLevel;
  u16 deviceCode;
  u32 releaseDate;
  u8 padding[24];
} DVDDriveInfo;
void DVDDumpWaitingQueue(void);
int DVDLowRead(void *addr, unsigned long length, unsigned long offset, void (*callback)(unsigned long));
int DVDLowSeek(unsigned long offset, void (*callback)(unsigned long));
int DVDLowWaitCoverClose(void (*callback)(unsigned long));
int DVDLowReadDiskID(struct DVDDiskID *diskID, void (*callback)(unsigned long));
int DVDLowStopMotor(void (*callback)(unsigned long));
int DVDLowRequestError(void (*callback)(unsigned long));
int DVDLowInquiry(struct DVDDriveInfo *info, void (*callback)(unsigned long));
int DVDLowAudioStream(unsigned long subcmd, unsigned long length, unsigned long offset, void (*callback)(unsigned long));
int DVDLowRequestAudioStatus(unsigned long subcmd, void (*callback)(unsigned long));
int DVDLowAudioBufferConfig(int enable, unsigned long size, void (*callback)(unsigned long));
void DVDLowReset();
void (*DVDLowSetResetCoverCallback(void (*callback)(unsigned long)))(unsigned long);
int DVDLowBreak();
void (*DVDLowClearCallback())(unsigned long);
unsigned long DVDLowGetCoverStatus();
void DVDInit();
int DVDReadAbsAsyncPrio(struct DVDCommandBlock *block, void *addr, long length, long offset, void (*callback)(long, struct DVDCommandBlock *), long prio);
int DVDSeekAbsAsyncPrio(struct DVDCommandBlock *block, long offset, void (*callback)(long, struct DVDCommandBlock *), long prio);
int DVDReadAbsAsyncForBS(struct DVDCommandBlock *block, void *addr, long length, long offset, void (*callback)(long, struct DVDCommandBlock *));
int DVDReadDiskID(struct DVDCommandBlock *block, struct DVDDiskID *diskID, void (*callback)(long, struct DVDCommandBlock *));
int DVDPrepareStreamAbsAsync(struct DVDCommandBlock *block, unsigned long length, unsigned long offset, void (*callback)(long, struct DVDCommandBlock *));
int DVDCancelStreamAsync(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
long DVDCancelStream(struct DVDCommandBlock *block);
int DVDStopStreamAtEndAsync(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
long DVDStopStreamAtEnd(struct DVDCommandBlock *block);
int DVDGetStreamErrorStatusAsync(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
long DVDGetStreamErrorStatus(struct DVDCommandBlock *block);
int DVDGetStreamPlayAddrAsync(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
long DVDGetStreamPlayAddr(struct DVDCommandBlock *block);
int DVDGetStreamStartAddrAsync(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
long DVDGetStreamStartAddr(struct DVDCommandBlock *block);
int DVDGetStreamLengthAsync(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
long DVDGetStreamLength(struct DVDCommandBlock *block);
int DVDChangeDiskAsyncForBS(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
int DVDChangeDiskAsync(struct DVDCommandBlock *block, struct DVDDiskID *id, void (*callback)(long, struct DVDCommandBlock *));
long DVDChangeDisk(struct DVDCommandBlock *block, struct DVDDiskID *id);
int DVDInquiryAsync(struct DVDCommandBlock *block, struct DVDDriveInfo *info, void (*callback)(long, struct DVDCommandBlock *));
long DVDInquiry(struct DVDCommandBlock *block, struct DVDDriveInfo *info);
void DVDReset();
int DVDResetRequired();
long DVDGetCommandBlockStatus(struct DVDCommandBlock *block);
long DVDGetDriveStatus();
int DVDSetAutoInvalidation(int autoInval);
void DVDPause();
void DVDResume();
int DVDCancelAsync(struct DVDCommandBlock *block, void (*callback)(long, struct DVDCommandBlock *));
long DVDCancel(volatile struct DVDCommandBlock *block);
int DVDCancelAllAsync(DVDCBCallback callback);
long DVDCancelAll(void);
struct DVDDiskID *DVDGetCurrentDiskID(void);
BOOL DVDCheckDisk(void);
s32 DVDConvertPathToEntrynum(const char *pathPtr);
BOOL DVDFastOpen(s32 entrynum, DVDFileInfo *fileInfo);
BOOL DVDOpen(char *fileName, DVDFileInfo *fileInfo);
BOOL DVDClose(DVDFileInfo *fileInfo);
BOOL DVDGetCurrentDir(char *path, u32 maxlen);
BOOL DVDChangeDir(char *dirName);
BOOL DVDReadAsyncPrio(DVDFileInfo *fileInfo, void *addr, s32 length, s32 offset, DVDCallback callback, s32 prio);
long DVDReadPrio(struct DVDFileInfo *fileInfo, void *addr, long length, long offset, long prio);
int DVDSeekAsyncPrio(struct DVDFileInfo *fileInfo, long offset, void (*callback)(long, struct DVDFileInfo *), long prio);
long DVDSeekPrio(struct DVDFileInfo *fileInfo, long offset, long prio);
long DVDGetFileInfoStatus(struct DVDFileInfo *fileInfo);
int DVDOpenDir(char *dirName, DVDDir *dir);
int DVDReadDir(DVDDir *dir, DVDDirEntry *dirent);
int DVDCloseDir(DVDDir *dir);
void *DVDGetFSTLocation();
BOOL DVDPrepareStreamAsync(DVDFileInfo *fileInfo, u32 length, u32 offset, DVDCallback callback);
s32 DVDPrepareStream(DVDFileInfo *fileInfo, u32 length, u32 offset);
s32 DVDGetTransferredSize(DVDFileInfo *fileinfo);
extern int DVDReadAbsAsyncForBS(struct DVDCommandBlock *block, void *addr, long length, long offset, void (*callback)(long, struct DVDCommandBlock *));
extern int DVDReadDiskID(struct DVDCommandBlock *block, struct DVDDiskID *diskID, void (*callback)(long, struct DVDCommandBlock *));
extern void DVDReset(void);
int DVDReadAbsAsyncPrio(struct DVDCommandBlock *block, void *addr, long length, long offset, void (*callback)(long, struct DVDCommandBlock *), long prio);
int DVDSeekAbsAsyncPrio(struct DVDCommandBlock *block, long offset, void (*callback)(long, struct DVDCommandBlock *), long prio);
int DVDPrepareStreamAbsAsync(struct DVDCommandBlock *block, unsigned long length, unsigned long offset, void (*callback)(long, struct DVDCommandBlock *));
void __DVDStoreErrorCode(u32 error);
typedef struct OSBootInfo_s
{
  DVDDiskID DVDDiskID;
  unsigned long magic;
  unsigned long version;
  unsigned long memorySize;
  unsigned long consoleType;
  void *arenaLo;
  void *arenaHi;
  void *FSTLocation;
  unsigned long FSTMaxLength;
} OSBootInfo;
OSTick OSGetTick(void);
OSTime OSGetTime(void);
void OSTicksToCalendarTime(OSTime ticks, OSCalendarTime *td);
OSTime OSCalendarTimeToTicks(OSCalendarTime *td);
BOOL OSEnableInterrupts(void);
BOOL OSDisableInterrupts(void);
BOOL OSRestoreInterrupts(BOOL level);
u32 OSGetSoundMode(void);
void OSSetSoundMode(u32 mode);
void OSReport(char *, ...);
void OSPanic(char *file, int line, char *msg, ...);
void *OSPhysicalToCached(u32 paddr);
void *OSPhysicalToUncached(u32 paddr);
u32 OSCachedToPhysical(void *caddr);
u32 OSUncachedToPhysical(void *ucaddr);
void *OSCachedToUncached(void *caddr);
void *OSUncachedToCached(void *ucaddr);
typedef void (*jmp_t)(void);
typedef jmp_t jtbl_t[];
typedef struct _GObjFuncs GObjFuncs;
typedef struct HSD_AnimJoint HSD_AnimJoint;
typedef struct HSD_AObj HSD_AObj;
typedef struct HSD_AObjDesc HSD_AObjDesc;
typedef struct HSD_Archive HSD_Archive;
typedef struct HSD_ArchiveExternInfo HSD_ArchiveExternInfo;
typedef struct HSD_ArchiveHeader HSD_ArchiveHeader;
typedef struct HSD_ArchivePublicInfo HSD_ArchivePublicInfo;
typedef struct HSD_ArchiveRelocationInfo HSD_ArchiveRelocationInfo;
typedef struct HSD_ByteCodeExpDesc HSD_ByteCodeExpDesc;
typedef struct HSD_CameraAnim HSD_CameraAnim;
typedef struct HSD_CameraDescCommon HSD_CameraDescCommon;
typedef struct HSD_CameraDescFrustum HSD_CameraDescFrustum;
typedef struct HSD_CameraDescPerspective HSD_CameraDescPerspective;
typedef struct HSD_CObj HSD_CObj;
typedef struct HSD_CObjInfo HSD_CObjInfo;
typedef struct HSD_DevCom HSD_DevCom;
typedef struct HSD_DObj HSD_DObj;
typedef struct HSD_DObjDesc HSD_DObjDesc;
typedef struct HSD_DObjInfo HSD_DObjInfo;
typedef struct HSD_Envelope HSD_Envelope;
typedef struct HSD_EnvelopeDesc HSD_EnvelopeDesc;
typedef struct HSD_Exp HSD_Exp;
typedef struct HSD_ExpDesc HSD_ExpDesc;
typedef struct _HSD_FObj HSD_FObj;
typedef struct HSD_Fog HSD_Fog;
typedef struct HSD_FogAdj HSD_FogAdj;
typedef struct HSD_FogAdjDesc HSD_FogAdjDesc;
typedef struct HSD_FogAdjInfo HSD_FogAdjInfo;
typedef struct HSD_FogDesc HSD_FogDesc;
typedef struct HSD_FogInfo HSD_FogInfo;
typedef struct HSD_Generator HSD_Generator;
typedef struct HSD_GObj HSD_GObj;
typedef struct HSD_GObjProc HSD_GObjProc;
typedef struct HSD_Hash HSD_Hash;
typedef struct HSD_HashEntry HSD_HashEntry;
typedef struct HSD_IKHint HSD_IKHint;
typedef struct HSD_IKHintDesc HSD_IKHintDesc;
typedef struct HSD_ImageDesc HSD_ImageDesc;
typedef struct HSD_JObj HSD_JObj;
typedef struct HSD_Joint HSD_Joint;
typedef struct HSD_LightAnim HSD_LightAnim;
typedef struct HSD_LightAttn HSD_LightAttn;
typedef struct HSD_LightDesc HSD_LightDesc;
typedef struct HSD_LightPoint HSD_LightPoint;
typedef struct HSD_LightPointDesc HSD_LightPointDesc;
typedef struct HSD_LightSpot HSD_LightSpot;
typedef struct HSD_LightSpotDesc HSD_LightSpotDesc;
typedef struct HSD_LObj HSD_LObj;
typedef struct HSD_LObjInfo HSD_LObjInfo;
typedef struct HSD_MatAnimJoint HSD_MatAnimJoint;
typedef struct HSD_Material HSD_Material;
typedef struct HSD_MObj HSD_MObj;
typedef struct HSD_MObjInfo HSD_MObjInfo;
typedef struct HSD_Obj HSD_Obj;
typedef struct HSD_PadData HSD_PadData;
typedef struct HSD_PadRumbleListData HSD_PadRumbleListData;
typedef struct HSD_PadStatus HSD_PadStatus;
typedef struct HSD_Particle HSD_Particle;
typedef struct HSD_PEDesc HSD_PEDesc;
typedef struct HSD_PObj HSD_PObj;
typedef struct HSD_PObjDesc HSD_PObjDesc;
typedef struct HSD_PObjInfo HSD_PObjInfo;
typedef struct HSD_psAppSRT HSD_psAppSRT;
typedef struct HSD_RObj HSD_RObj;
typedef struct HSD_RObjAnimJoint HSD_RObjAnimJoint;
typedef struct HSD_RObjDesc HSD_RObjDesc;
typedef struct HSD_RumbleData HSD_RumbleData;
typedef struct HSD_Rvalue HSD_Rvalue;
typedef struct HSD_RvalueList HSD_RvalueList;
typedef struct HSD_Shadow HSD_Shadow;
typedef struct HSD_ShapeAnim HSD_ShapeAnim;
typedef struct HSD_ShapeAnimDObj HSD_ShapeAnimDObj;
typedef struct HSD_ShapeAnimJoint HSD_ShapeAnimJoint;
typedef struct HSD_ShapeSet HSD_ShapeSet;
typedef struct HSD_ShapeSetDesc HSD_ShapeSetDesc;
typedef struct HSD_SM HSD_SM;
typedef struct HSD_SObj_803A477C_t HSD_SObj_803A477C_t;
typedef struct HSD_Spline HSD_Spline;
typedef struct HSD_TExpDag HSD_TExpDag;
typedef struct HSD_TExpRes HSD_TExpRes;
typedef struct HSD_Text HSD_Text;
typedef struct HSD_TObj HSD_TObj;
typedef struct HSD_ViewingRect HSD_ViewingRect;
typedef struct HSD_VtxDescList HSD_VtxDescList;
typedef struct HSD_WObj HSD_WObj;
typedef struct HSD_WObjAnim HSD_WObjAnim;
typedef struct HSD_WObjDesc HSD_WObjDesc;
typedef struct HSD_WObjInfo HSD_WObjInfo;
typedef struct PadLibData PadLibData;
typedef struct RumbleCommand RumbleCommand;
typedef struct RumbleInfo RumbleInfo;
typedef struct sislib_UnkAlloc3 sislib_UnkAlloc3;
typedef struct sislib_UnkAllocData sislib_UnkAllocData;
typedef struct TextKerning TextKerning;
typedef union HSD_CObjDesc HSD_CObjDesc;
typedef union HSD_ObjData HSD_ObjData;
typedef union HSD_Rumble HSD_Rumble;
typedef union HSD_TExp HSD_TExp;
typedef void (*GObj_RenderFunc)(HSD_GObj *gobj, int code);
typedef void (*HSD_ObjUpdateFunc)(void *obj, enum_t type, HSD_ObjData *fval);
typedef void (*HSD_DevComCallback)(int, int, void *, bool cancelflag);
typedef void (*HSD_GObjEvent)(HSD_GObj *gobj);
typedef void (*HSD_UserDataEvent)(void *user_data);
typedef bool (*HSD_GObjPredicate)(HSD_GObj *gobj);
typedef void (*HSD_GObjInteraction)(HSD_GObj *gobj0, HSD_GObj *gobj1);
typedef void (*HSD_MObjSetupFunc)(HSD_MObj *mobj, u32 rendermode);
typedef enum PObjSetupFlag
{
  SETUP_NORMAL = 1,
  SETUP_REFLECTION = 2,
  SETUP_HIGHLIGHT = 4,
  SETUP_NORMAL_PROJECTION = 6,
  SETUP_JOINT0 = 1,
  SETUP_JOINT1 = 2,
  SETUP_NONE = 0
} PObjSetupFlag;
typedef enum HSD_TrspMask
{
  HSD_TRSP_OPA = 1,
  HSD_TRSP_XLU = 2,
  HSD_TRSP_TEXEDGE = 4,
  HSD_TRSP_ALL = 7
} HSD_TrspMask;
struct grCorneria_GroundVars;
typedef struct grDynamicAttr_UnkStruct grDynamicAttr_UnkStruct;
typedef struct Ground Ground;
typedef struct IceMountainParams IceMountainParams;
typedef struct StageInfo StageInfo;
typedef struct UnkArchiveStruct UnkArchiveStruct;
typedef struct UnkBgmStruct UnkBgmStruct;
typedef struct UnkStage6B0 UnkStage6B0;
typedef struct UnkStageDatInternal UnkStageDatInternal;
typedef struct UnkStageDat UnkStageDat;
typedef HSD_GObj Ground_GObj;
typedef enum InternalStageId
{
  InternalStageID_Unk00,
  InternalStageID_Unk01,
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
  SHRINEROUTE,
  STAGEKIND_UNK32,
  STAGEKIND_UNK33,
  STAGEKIND_UNK34,
  STAGEKIND_UNK35,
  STAGEKIND_UNK36,
  STAGEKIND_UNK37,
  STAGEKIND_UNK38,
  STAGEKIND_UNK39,
  HOMERUN = 0x43
} InternalStageId;
typedef struct unkCastle unkCastle;
typedef void (*unkCastleCallback)(void *, struct unkCastle *);
typedef void (*unkCastleCallback2)(void *, struct unkCastle *, Ground_GObj *);
struct lb_80011A50_t;
typedef struct AbsorbDesc AbsorbDesc;
typedef struct CollData CollData;
typedef struct ColorOverlay ColorOverlay;
typedef struct CommandInfo CommandInfo;
typedef struct DynamicsDesc DynamicsDesc;
typedef struct FigaTrack FigaTrack;
typedef struct FigaTree FigaTree;
typedef struct FighterHurtCapsule FighterHurtCapsule;
typedef struct ColorOverlay_UnkInner ColorOverlay_UnkInner;
typedef struct ftDeviceUnk2 ftDeviceUnk2;
typedef struct HitCapsule HitCapsule;
typedef struct HitResult HitResult;
typedef struct HitVictim HitVictim;
typedef struct HSD_AllocEntry HSD_AllocEntry;
typedef struct HurtCapsule HurtCapsule;
typedef struct lbRefract_CallbackData lbRefract_CallbackData;
typedef struct PreloadCache PreloadCache;
typedef struct PreloadCacheScene PreloadCacheScene;
typedef struct PreloadCacheSceneEntry PreloadCacheSceneEntry;
typedef struct PreloadEntry PreloadEntry;
typedef struct ReflectDesc ReflectDesc;
typedef struct ShieldDesc ShieldDesc;
typedef struct Unk80433380_48 Unk80433380_48;
typedef struct LbShadow LbShadow;
typedef enum HurtCapsuleState
{
  HurtCapsule_Enabled,
  HurtCapsule_Disabled,
  Intangible
} HurtCapsuleState;
typedef enum HitElement
{
  HitElement_Normal,
  HitElement_Fire,
  HitElement_Electric,
  HitElement_Slash,
  HitElement_Coin,
  HitElement_Ice,
  HitElement_Nap,
  HitElement_Sleep,
  HitElement_Catch,
  HitElement_Ground,
  HitElement_Cape,
  HitElement_Inert,
  HitElement_Disable,
  HitElement_Dark,
  HitElement_Scball,
  HitElement_Lipstick,
  HitElement_Leadead
} HitElement;
typedef enum HitCapsuleState
{
  HitCapsule_Disabled,
  HitCapsule_Enabled,
  HitCapsule_Unk2,
  HitCapsule_Unk3,
  HitCapsule_Max = HitCapsule_Unk3
} HitCapsuleState;
typedef enum HurtHeight
{
  HurtHeight_Low,
  HurtHeight_Mid,
  HurtHeight_High
} HurtHeight;
typedef void (*RefractCallbackTypeA)(struct lbRefract_CallbackData *, s32, u32, s8, s8);
typedef void (*RefractCallbackTypeB)(struct lbRefract_CallbackData *, s32, u32, s8, s8, s8, s8);
typedef void (*RefractCallbackTypeC)(struct lbRefract_CallbackData *, s32, u32, s32 *, s32 *, s32 *, s32 *);
typedef struct lbColl_80008D30_arg1
{
  HitCapsuleState state;
  u32 damage;
  int kb_angle;
  u32 unkC;
  u32 unk10;
  u32 unk14;
  u32 element;
  int sfx_severity;
  enum_t sfx_kind;
} lbColl_80008D30_arg1;
typedef enum ECBSourceKind
{
  ECBSource_None,
  ECBSource_JObj,
  ECBSource_Fixed
} ECBSourceKind;
typedef struct 
{
  f32 x;
  f32 y;
} Vec2;
typedef struct 
{
  f32 x;
  f32 y;
} *Vec2Ptr;
typedef struct 
{
  f32 x;
  f32 y;
} Point2d;
typedef struct 
{
  f32 x;
  f32 y;
} *Point2dPtr;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
} Vec;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
} Vec3;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
} *VecPtr;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
} Point3d;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
} *Point3dPtr;
typedef struct 
{
  s8 x;
  s8 y;
  s8 z;
} S8Vec3;
typedef struct 
{
  s8 x;
  s8 y;
  s8 z;
} S8Vec;
typedef struct 
{
  s8 x;
  s8 y;
  s8 z;
} *S8Vec3Ptr;
typedef struct 
{
  s8 x;
  s8 y;
  s8 z;
} *S8VecPtr;
typedef struct 
{
  u8 x;
  u8 y;
  u8 z;
  u8 w;
} U8Vec4;
typedef struct 
{
  u8 x;
  u8 y;
  u8 z;
  u8 w;
} *U8Vec4Ptr;
typedef struct 
{
  s16 x;
  s16 y;
  s16 z;
} S16Vec;
typedef struct 
{
  s16 x;
  s16 y;
  s16 z;
} S16Vec3;
typedef struct 
{
  s16 x;
  s16 y;
  s16 z;
} *S16VecPtr;
typedef struct 
{
  s16 x;
  s16 y;
  s16 z;
} *S16Vec3Ptr;
typedef struct 
{
  int x;
  int y;
} IntVec2;
typedef struct 
{
  int x;
  int y;
} *IntVec2Ptr;
typedef struct 
{
  s32 x;
  s32 y;
} S32Vec2;
typedef struct 
{
  s32 x;
  s32 y;
} *S32Vec2Ptr;
typedef struct 
{
  int x;
  int y;
  int z;
} IntVec3;
typedef struct 
{
  int x;
  int y;
  int z;
} *IntVec3Ptr;
typedef struct 
{
  s32 x;
  s32 y;
  s32 z;
} S32Vec;
typedef struct 
{
  s32 x;
  s32 y;
  s32 z;
} S32Vec3;
typedef struct 
{
  s32 x;
  s32 y;
  s32 z;
} *S32VecPtr;
typedef struct 
{
  s32 x;
  s32 y;
  s32 z;
} *S32Vec3Ptr;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
  f32 w;
} Quaternion;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
  f32 w;
} Vec4;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
  f32 w;
} *QuaternionPtr;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
  f32 w;
} Qtrn;
typedef struct 
{
  f32 x;
  f32 y;
  f32 z;
  f32 w;
} *QtrnPtr;
typedef f32 Mtx[3][4];
typedef f32 Mtx44[4][4];
typedef f32 (*MtxPtr)[4];
typedef f32 (*Mtx44Ptr)[4];
typedef f32 ROMtx[4][3];
typedef f32 (*ROMtxPtr)[3];
void MTXFrustum(Mtx m, f32 t, f32 b, f32 l, f32 r, f32 n, f32 f);
void MTXPerspective(Mtx m, f32 fovY, f32 aspect, f32 n, f32 f);
void MTXOrtho(Mtx m, f32 t, f32 b, f32 l, f32 r, f32 n, f32 f);
void MTXPerspective(Mtx44 m, f32 fovY, f32 aspect, f32 n, f32 f);
void C_MTXLookAt(Mtx m, Point3dPtr camPos, VecPtr camUp, Point3dPtr target);
void MTXRotRad(Mtx m, char axis, f32 rad);
void PSMTXTrans(Mtx m, f32 xT, f32 yT, f32 zT);
void MTXTransApply(Mtx src, Mtx dst, f32 xT, f32 yT, f32 zT);
void MTXScaleApply(Mtx src, Mtx dst, f32 xS, f32 yS, f32 zS);
void MTXReflect(Mtx m, Vec *p, Vec *n);
void MTXLookAt(Mtx m, Vec *camPos, Vec *camUp, Vec *target);
void MTXLightFrustum(Mtx m, f32 t, f32 b, f32 l, f32 r, f32 n, f32 scaleS, f32 scaleT, f32 transS, f32 transT);
void MTXLightPerspective(Mtx m, f32 fovY, f32 aspect, f32 scaleS, f32 scaleT, f32 transS, f32 transT);
void MTXLightOrtho(Mtx m, f32 t, f32 b, f32 l, f32 r, f32 scaleS, f32 scaleT, f32 transS, f32 transT);
void C_MTXIdentity(Mtx m);
void C_MTXCopy(Mtx src, Mtx dst);
void C_MTXConcat(Mtx a, Mtx b, Mtx ab);
void C_MTXTranspose(Mtx src, Mtx xPose);
void C_MTXScale(Mtx m, f32 xS, f32 yS, f32 zS);
void C_MTXRotAxisRad(Mtx m, Vec *axis, f32 rad);
void C_MTXRotTrig(Mtx m, char axis, f32 sinA, f32 cosA);
void C_MTXQuat(Mtx m, QuaternionPtr q);
u32 C_MTXInverse(Mtx src, Mtx inv);
u32 C_MTXInvXpose(Mtx src, Mtx invX);
void PSMTXIdentity(Mtx m);
void PSMTXCopy(Mtx src, Mtx dst);
void PSMTXConcat(Mtx mA, Mtx mB, Mtx mAB);
void PSMTXTranspose(Mtx src, Mtx xPose);
void PSMTXScale(Mtx m, f32 xS, f32 yS, f32 zS);
void PSMTXRotAxisRad(Mtx m, Vec *axis, f32 rad);
void PSMTXRotTrig(Mtx m, char axis, f32 sinA, f32 cosA);
void PSMTXQuat(Mtx m, QuaternionPtr q);
u32 PSMTXInverse(Mtx src, Mtx inv);
u32 PSMTXInvXpose(Mtx src, Mtx invX);
typedef struct 
{
  u32 numMtx;
  Mtx *stackBase;
  Mtx *stackPtr;
} MTXStack;
void MTXInitStack(MTXStack *sPtr, u32 numMtx);
Mtx *MTXPush(MTXStack *sPtr, Mtx m);
Mtx *MTXPushFwd(MTXStack *sPtr, Mtx m);
Mtx *MTXPushInv(MTXStack *sPtr, Mtx m);
Mtx *MTXPushInvXpose(MTXStack *sPtr, Mtx m);
Mtx *MTXPop(MTXStack *sPtr);
Mtx *MTXGetStackPtr(MTXStack *sPtr);
void C_MTXMultVecSR(Mtx44 m, Vec *src, Vec *dst);
void PSMTXMultVecSR(Mtx44 m, Vec *src, Vec *dst);
void MTXMultVecArraySR(Mtx44 m, Vec *srcBase, Vec *dstBase, u32 count);
void C_MTXMultVec(Mtx44 m, Vec *src, Vec *dst);
void C_MTXMultVecArray(Mtx m, Vec *srcBase, Vec *dstBase, u32 count);
void PSMTXMultVec(Mtx44 m, Vec *src, Vec *dst);
void PSMTXMultVecArray(Mtx m, Vec *srcBase, Vec *dstBase, u32 count);
void PSMTXReorder(Mtx src, ROMtx dest);
void PSMTXROMultVecArray(ROMtx *m, Vec *srcBase, Vec *dstBase, u32 count);
void PSMTXROSkin2VecArray(ROMtx *m0, ROMtx *m1, f32 *wtBase, Vec *srcBase, Vec *dstBase, u32 count);
void PSMTXROMultS16VecArray(ROMtx *m, S16Vec *srcBase, Vec *dstBase, u32 count);
void PSMTXMultS16VecArray(Mtx44 *m, S16Vec *srcBase, Vec *dstBase, u32 count);
f32 C_VECMag(Vec *v);
f32 PSVECMag(Vec *v);
void VECHalfAngle(Vec *a, Vec *b, Vec *half);
void VECReflect(Vec *src, Vec *normal, Vec *dst);
f32 VECDistance(Vec *a, Vec *b);
void C_VECAdd(Vec *a, Vec *b, Vec *c);
void C_VECSubtract(Vec *a, Vec *b, Vec *c);
void C_VECScale(Vec *src, Vec *dst, f32 scale);
void C_VECNormalize(Vec *src, Vec *unit);
f32 C_VECSquareMag(Vec *v);
f32 C_VECDotProduct(Vec *a, Vec *b);
void C_VECCrossProduct(Vec *a, Vec *b, Vec *axb);
f32 C_VECSquareDistance(Vec *a, Vec *b);
void PSVECAdd(Vec *a, Vec *b, Vec *c);
void PSVECSubtract(Vec *a, Vec *b, Vec *c);
void PSVECScale(Vec *src, Vec *dst, f32 scale);
void PSVECNormalize(Vec *vec1, Vec *dst);
f32 PSVECSquareMag(Vec *vec1);
f32 PSVECDotProduct(Vec *vec1, Vec *vec2);
void PSVECCrossProduct(Vec *vec1, Vec *vec2, Vec *dst);
f32 PSVECSquareDistance(Vec *vec1, Vec *vec2);
typedef enum_t FtMotionId;
typedef struct DObjList DObjList;
typedef struct Fighter Fighter;
typedef struct Fighter_804D653C_t Fighter_804D653C_t;
typedef struct Fighter_x1670_t Fighter_x1670_t;
typedef struct Fighter_CostumeStrings Fighter_CostumeStrings;
typedef struct Fighter_DemoStrings Fighter_DemoStrings;
typedef struct FighterBone FighterBone;
typedef struct FighterPartsTable FighterPartsTable;
typedef struct UnkPlBonusBits UnkPlBonusBits;
typedef struct ft_800898B4_t ft_800898B4_t;
typedef struct ftCo_DatAttrs_xBC_t ftCo_DatAttrs_xBC_t;
typedef struct ftCommonData ftCommonData;
typedef struct ftData ftData;
typedef struct ftData_UnkCountStruct ftData_UnkCountStruct;
typedef struct ftLk_SpecialN_Vec3Group ftLk_SpecialN_Vec3Group;
typedef struct ftMaterial_UnkTevStruct ftMaterial_UnkTevStruct;
typedef struct FtSFX FtSFX;
typedef struct ftSubactionList ftSubactionList;
typedef struct gmScriptEventDefault gmScriptEventDefault;
typedef struct MotionState MotionState;
typedef struct UnkFloat6_Camera UnkFloat6_Camera;
typedef u32 MotionFlags;
typedef struct HSD_GObj Fighter_GObj;
typedef char *(*Fighter_MotionFileStringGetter)(enum_t arg0);
typedef void (*Fighter_ItemEvent)(HSD_GObj *gobj, bool arg1);
typedef void (*Fighter_ModelEvent)(Fighter *fp, int arg1, bool arg2);
typedef void (*Fighter_UnkMtxEvent)(HSD_GObj *gobj, int arg1, Mtx vmtx);
typedef void (*Fighter_UnkPtrEvent)(int arg0, int *arg1, int *arg2);
typedef void (*FighterEvent)(Fighter *fp);
typedef void (*FtCmd)(Fighter_GObj *, CommandInfo *);
typedef void (*FtCmd2)(Fighter_GObj *, CommandInfo *, int);
typedef bool (*ftDevice_Callback0)(Ground_GObj *, Fighter_GObj *, Vec3 *);
typedef enum FighterKind
{
  FTKIND_MARIO,
  FTKIND_FOX,
  FTKIND_CAPTAIN,
  FTKIND_DONKEY,
  FTKIND_KIRBY,
  FTKIND_KOOPA,
  FTKIND_LINK,
  FTKIND_SEAK,
  FTKIND_NESS,
  FTKIND_PEACH,
  FTKIND_POPO,
  FTKIND_NANA,
  FTKIND_PIKACHU,
  FTKIND_SAMUS,
  FTKIND_YOSHI,
  FTKIND_PURIN,
  FTKIND_MEWTWO,
  FTKIND_LUIGI,
  FTKIND_MARS,
  FTKIND_ZELDA,
  FTKIND_CLINK,
  FTKIND_DRMARIO,
  FTKIND_FALCO,
  FTKIND_PICHU,
  FTKIND_GAMEWATCH,
  FTKIND_GANON,
  FTKIND_EMBLEM,
  FTKIND_MASTERH,
  FTKIND_CREZYH,
  FTKIND_BOY,
  FTKIND_GIRL,
  FTKIND_GKOOPS,
  FTKIND_SANDBAG,
  FTKIND_NONE,
  FTKIND_MAX = FTKIND_NONE
} FighterKind;
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
typedef enum Fighter_Part
{
  FtPart_TopN,
  FtPart_TransN,
  FtPart_XRotN,
  FtPart_YRotN,
  FtPart_HipN,
  FtPart_WaistN,
  FtPart_LLegJA,
  FtPart_LLegJ,
  FtPart_LKneeJ,
  FtPart_LFootJA,
  FtPart_LFootJ,
  FtPart_RLegJA,
  FtPart_RLegJ,
  FtPart_RKneeJ,
  FtPart_RFootJA,
  FtPart_RFootJ,
  FtPart_BustN,
  FtPart_LShoulderN,
  FtPart_LShoulderJA,
  FtPart_LShoulderJ,
  FtPart_LArmJ,
  FtPart_LHandN,
  FtPart_L1stNa,
  FtPart_L1stNb,
  FtPart_L2ndNa,
  FtPart_L2ndNb,
  FtPart_L3rdNa,
  FtPart_L3rdNb,
  FtPart_L4thNa,
  FtPart_L4thNb,
  FtPart_LThumbNa,
  FtPart_LThumbNb,
  FtPart_LHandNb,
  FtPart_NeckN,
  FtPart_HeadN,
  FtPart_RShoulderN,
  FtPart_RShoulderJA,
  FtPart_RShoulderJ,
  FtPart_RArmJ,
  FtPart_RHandN,
  FtPart_R1stNa,
  FtPart_R1stNb,
  FtPart_R2ndNa,
  FtPart_R2ndNb,
  FtPart_R3rdNa,
  FtPart_R3rdNb,
  FtPart_R4thNa,
  FtPart_R4thNb,
  FtPart_RThumbNa,
  FtPart_RThumbNb,
  FtPart_RHandNb,
  FtPart_ThrowN,
  FtPart_TransN2,
  FtPart_109 = 109
} Fighter_Part;
typedef enum FtWalkType
{
  FtWalkType_Slow,
  FtWalkType_Middle,
  FtWalkType_Fast
} FtWalkType;
typedef enum FtMoveId
{
  FtMoveId_None,
  FtMoveId_Default,
  FtMoveId_Attack11,
  FtMoveId_Attack12,
  FtMoveId_Attack13,
  FtMoveId_Attack100,
  FtMoveId_AttackDash,
  FtMoveId_AttackS3,
  FtMoveId_AttackHi3,
  FtMoveId_AttackLw3,
  FtMoveId_AttackS4,
  FtMoveId_AttackHi4,
  FtMoveId_AttackLw4,
  FtMoveId_AttackAirN,
  FtMoveId_AttackAirF,
  FtMoveId_AttackAirB,
  FtMoveId_AttackAirHi,
  FtMoveId_AttackAirLw,
  FtMoveId_SpecialN,
  FtMoveId_SpecialS,
  FtMoveId_SpecialHi,
  FtMoveId_SpecialLw,
  FtMoveId_KbSpecialNMr,
  FtMoveId_KbSpecialNFx,
  FtMoveId_KbSpecialNCa,
  FtMoveId_KbSpecialNDk,
  FtMoveId_KbSpecialNKp,
  FtMoveId_KbSpecialNLk,
  FtMoveId_KbSpecialNSk,
  FtMoveId_KbSpecialNNs,
  FtMoveId_KbSpecialNPe,
  FtMoveId_KbSpecialNPp,
  FtMoveId_KbSpecialNPk,
  FtMoveId_KbSpecialNSs,
  FtMoveId_KbSpecialNYs,
  FtMoveId_KbSpecialNPr,
  FtMoveId_KbSpecialNMt,
  FtMoveId_KbSpecialNLg,
  FtMoveId_KbSpecialNMs,
  FtMoveId_KbSpecialNZd,
  FtMoveId_KbSpecialNCl,
  FtMoveId_KbSpecialNDr,
  FtMoveId_KbSpecialNFc,
  FtMoveId_KbSpecialNPc,
  FtMoveId_KbSpecialNGw,
  FtMoveId_KbSpecialNGn,
  FtMoveId_KbSpecialNFe,
  FtMoveId_KbSpecialNGk,
  FtMoveId_Unk48,
  FtMoveId_Unk49,
  FtMoveId_DownAttackU,
  FtMoveId_DownAttackD,
  FtMoveId_CatchAttack,
  FtMoveId_ThrowF,
  FtMoveId_ThrowB,
  FtMoveId_ThrowHi,
  FtMoveId_ThrowLw,
  FtMoveId_CargoThrowF,
  FtMoveId_CargoThrowB,
  FtMoveId_CargoThrowHi,
  FtMoveId_CargoThrowLw,
  FtMoveId_CliffAttackSlow,
  FtMoveId_CliffAttackQuick,
  FtMoveId_SwordSwing1,
  FtMoveId_SwordSwing3,
  FtMoveId_SwordSwing4,
  FtMoveId_SwordSwingDash,
  FtMoveId_BatSwing1,
  FtMoveId_BatSwing3,
  FtMoveId_BatSwing4,
  FtMoveId_BatSwingDash,
  FtMoveId_ParasolSwing1,
  FtMoveId_ParasolSwing3,
  FtMoveId_ParasolSwing4,
  FtMoveId_ParasolSwingDash,
  FtMoveId_HarisenSwing1,
  FtMoveId_HarisenSwing3,
  FtMoveId_HarisenSwing4,
  FtMoveId_HarisenSwingDash,
  FtMoveId_StarRodSwing1,
  FtMoveId_StarRodSwing3,
  FtMoveId_StarRodSwing4,
  FtMoveId_StarRodSwingDash,
  FtMoveId_LipstickSwing1,
  FtMoveId_LipstickSwing3,
  FtMoveId_LipstickSwing4,
  FtMoveId_LipstickSwingDash,
  FtMoveId_Parasol,
  FtMoveId_LGunShoot,
  FtMoveId_FireFlowerShoot,
  FtMoveId_Screw,
  FtMoveId_ScopeRapid,
  FtMoveId_ScopeFire,
  FtMoveId_Hammer,
  FtMoveId_WarpStarFall
} FtMoveId;
typedef enum SmashState
{
  SmashState_None,
  SmashState_PreCharge,
  SmashState_Charging,
  SmashState_Release
} SmashState;
typedef enum ftCommon_BuryType
{
  BuryType_Unk0,
  BuryType_Unk1,
  BuryType_Unk2,
  BuryType_Unk3
} ftCommon_BuryType;
enum 
{
  Ft_Dynamics_NumMax = 10
};
enum EntityKind
{
  EntityKind_None,
  EntityKind_Fighter,
  EntityKind_Item
};
typedef struct ftHurtboxInit ftHurtboxInit;
typedef struct ftCollisionBox ftCollisionBox;
typedef enum ftCo_JumpInput
{
  JumpInput_None,
  JumpInput_LStick,
  JumpInput_CStick,
  JumpInput_XY
} ftCo_JumpInput;
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
typedef enum ftCommon_MotionState
{
  ftCo_MS_None = -1,
  ftCo_MS_DeadDown,
  ftCo_MS_DeadLeft,
  ftCo_MS_DeadRight,
  ftCo_MS_DeadUp,
  ftCo_MS_DeadUpStar,
  ftCo_MS_DeadUpStarIce,
  ftCo_MS_DeadUpFall,
  ftCo_MS_DeadUpFallHitCamera,
  ftCo_MS_DeadUpFallHitCameraFlat,
  ftCo_MS_DeadUpFallIce,
  ftCo_MS_DeadUpFallHitCameraIce,
  ftCo_MS_Sleep,
  ftCo_MS_Rebirth,
  ftCo_MS_RebirthWait,
  ftCo_MS_Wait,
  ftCo_MS_WalkSlow,
  ftCo_MS_WalkMiddle,
  ftCo_MS_WalkFast,
  ftCo_MS_Turn,
  ftCo_MS_TurnRun,
  ftCo_MS_Dash,
  ftCo_MS_Run,
  ftCo_MS_RunDirect,
  ftCo_MS_RunBrake,
  ftCo_MS_KneeBend,
  ftCo_MS_JumpF,
  ftCo_MS_JumpB,
  ftCo_MS_JumpAerialF,
  ftCo_MS_JumpAerialB,
  ftCo_MS_Fall,
  ftCo_MS_FallF,
  ftCo_MS_FallB,
  ftCo_MS_FallAerial,
  ftCo_MS_FallAerialF,
  ftCo_MS_FallAerialB,
  ftCo_MS_FallSpecial,
  ftCo_MS_FallSpecialF,
  ftCo_MS_FallSpecialB,
  ftCo_MS_DamageFall,
  ftCo_MS_Squat,
  ftCo_MS_SquatWait,
  ftCo_MS_SquatRv,
  ftCo_MS_Landing,
  ftCo_MS_LandingFallSpecial,
  ftCo_MS_Attack11,
  ftCo_MS_Attack12,
  ftCo_MS_Attack13,
  ftCo_MS_Attack100Start,
  ftCo_MS_Attack100Loop,
  ftCo_MS_Attack100End,
  ftCo_MS_AttackDash,
  ftCo_MS_AttackS3Hi,
  ftCo_MS_AttackS3HiS,
  ftCo_MS_AttackS3S,
  ftCo_MS_AttackS3LwS,
  ftCo_MS_AttackS3Lw,
  ftCo_MS_AttackHi3,
  ftCo_MS_AttackLw3,
  ftCo_MS_AttackS4Hi,
  ftCo_MS_AttackS4HiS,
  ftCo_MS_AttackS4S,
  ftCo_MS_AttackS4LwS,
  ftCo_MS_AttackS4Lw,
  ftCo_MS_AttackHi4,
  ftCo_MS_AttackLw4,
  ftCo_MS_AttackAirN,
  ftCo_MS_AttackAirF,
  ftCo_MS_AttackAirB,
  ftCo_MS_AttackAirHi,
  ftCo_MS_AttackAirLw,
  ftCo_MS_LandingAirN,
  ftCo_MS_LandingAirF,
  ftCo_MS_LandingAirB,
  ftCo_MS_LandingAirHi,
  ftCo_MS_LandingAirLw,
  ftCo_MS_DamageHi1,
  ftCo_MS_DamageHi2,
  ftCo_MS_DamageHi3,
  ftCo_MS_DamageN1,
  ftCo_MS_DamageN2,
  ftCo_MS_DamageN3,
  ftCo_MS_DamageLw1,
  ftCo_MS_DamageLw2,
  ftCo_MS_DamageLw3,
  ftCo_MS_DamageAir1,
  ftCo_MS_DamageAir2,
  ftCo_MS_DamageAir3,
  ftCo_MS_DamageFlyHi,
  ftCo_MS_DamageFlyN,
  ftCo_MS_DamageFlyLw,
  ftCo_MS_DamageFlyTop,
  ftCo_MS_DamageFlyRoll,
  ftCo_MS_LightGet,
  ftCo_MS_HeavyGet,
  ftCo_MS_LightThrowF,
  ftCo_MS_LightThrowB,
  ftCo_MS_LightThrowHi,
  ftCo_MS_LightThrowLw,
  ftCo_MS_LightThrowDash,
  ftCo_MS_LightThrowDrop,
  ftCo_MS_LightThrowAirF,
  ftCo_MS_LightThrowAirB,
  ftCo_MS_LightThrowAirHi,
  ftCo_MS_LightThrowAirLw,
  ftCo_MS_HeavyThrowF,
  ftCo_MS_HeavyThrowB,
  ftCo_MS_HeavyThrowHi,
  ftCo_MS_HeavyThrowLw,
  ftCo_MS_LightThrowF4,
  ftCo_MS_LightThrowB4,
  ftCo_MS_LightThrowHi4,
  ftCo_MS_LightThrowLw4,
  ftCo_MS_LightThrowAirF4,
  ftCo_MS_LightThrowAirB4,
  ftCo_MS_LightThrowAirHi4,
  ftCo_MS_LightThrowAirLw4,
  ftCo_MS_HeavyThrowF4,
  ftCo_MS_HeavyThrowB4,
  ftCo_MS_HeavyThrowHi4,
  ftCo_MS_HeavyThrowLw4,
  ftCo_MS_SwordSwing1,
  ftCo_MS_SwordSwing3,
  ftCo_MS_SwordSwing4,
  ftCo_MS_SwordSwingDash,
  ftCo_MS_BatSwing1,
  ftCo_MS_BatSwing3,
  ftCo_MS_BatSwing4,
  ftCo_MS_BatSwingDash,
  ftCo_MS_ParasolSwing1,
  ftCo_MS_ParasolSwing3,
  ftCo_MS_ParasolSwing4,
  ftCo_MS_ParasolSwingDash,
  ftCo_MS_HarisenSwing1,
  ftCo_MS_HarisenSwing3,
  ftCo_MS_HarisenSwing4,
  ftCo_MS_HarisenSwingDash,
  ftCo_MS_StarRodSwing1,
  ftCo_MS_StarRodSwing3,
  ftCo_MS_StarRodSwing4,
  ftCo_MS_StarRodSwingDash,
  ftCo_MS_LipstickSwing1,
  ftCo_MS_LipstickSwing3,
  ftCo_MS_LipstickSwing4,
  ftCo_MS_LipstickSwingDash,
  ftCo_MS_ItemParasolOpen,
  ftCo_MS_ItemParasolFall,
  ftCo_MS_ItemParasolFallSpecial,
  ftCo_MS_ItemParasolDamageFall,
  ftCo_MS_LGunShoot,
  ftCo_MS_LGunShootAir,
  ftCo_MS_LGunShootEmpty,
  ftCo_MS_LGunShootAirEmpty,
  ftCo_MS_FireFlowerShoot,
  ftCo_MS_FireFlowerShootAir,
  ftCo_MS_ItemScrew,
  ftCo_MS_ItemScrewAir,
  ftCo_MS_DamageScrew,
  ftCo_MS_DamageScrewAir,
  ftCo_MS_ItemScopeStart,
  ftCo_MS_ItemScopeRapid,
  ftCo_MS_ItemScopeFire,
  ftCo_MS_ItemScopeEnd,
  ftCo_MS_ItemScopeAirStart,
  ftCo_MS_ItemScopeAirRapid,
  ftCo_MS_ItemScopeAirFire,
  ftCo_MS_ItemScopeAirEnd,
  ftCo_MS_ItemScopeStartEmpty,
  ftCo_MS_ItemScopeRapidEmpty,
  ftCo_MS_ItemScopeFireEmpty,
  ftCo_MS_ItemScopeEndEmpty,
  ftCo_MS_ItemScopeAirStartEmpty,
  ftCo_MS_ItemScopeAirRapidEmpty,
  ftCo_MS_ItemScopeAirFireEmpty,
  ftCo_MS_ItemScopeAirEndEmpty,
  ftCo_MS_LiftWait,
  ftCo_MS_LiftWalk1,
  ftCo_MS_LiftWalk2,
  ftCo_MS_LiftTurn,
  ftCo_MS_GuardOn,
  ftCo_MS_Guard,
  ftCo_MS_GuardOff,
  ftCo_MS_GuardSetOff,
  ftCo_MS_GuardReflect,
  ftCo_MS_DownBoundU,
  ftCo_MS_DownWaitU,
  ftCo_MS_DownDamageU,
  ftCo_MS_DownStandU,
  ftCo_MS_DownAttackU,
  ftCo_MS_DownFowardU,
  ftCo_MS_DownBackU,
  ftCo_MS_DownSpotU,
  ftCo_MS_DownBoundD,
  ftCo_MS_DownWaitD,
  ftCo_MS_DownDamageD,
  ftCo_MS_DownStandD,
  ftCo_MS_DownAttackD,
  ftCo_MS_DownFowardD,
  ftCo_MS_DownBackD,
  ftCo_MS_DownSpotD,
  ftCo_MS_Passive,
  ftCo_MS_PassiveStandF,
  ftCo_MS_PassiveStandB,
  ftCo_MS_PassiveWall,
  ftCo_MS_PassiveWallJump,
  ftCo_MS_PassiveCeil,
  ftCo_MS_ShieldBreakFly,
  ftCo_MS_ShieldBreakFall,
  ftCo_MS_ShieldBreakDownU,
  ftCo_MS_ShieldBreakDownD,
  ftCo_MS_ShieldBreakStandU,
  ftCo_MS_ShieldBreakStandD,
  ftCo_MS_Furafura,
  ftCo_MS_Catch,
  ftCo_MS_CatchPull,
  ftCo_MS_CatchDash,
  ftCo_MS_CatchDashPull,
  ftCo_MS_CatchWait,
  ftCo_MS_CatchAttack,
  ftCo_MS_CatchCut,
  ftCo_MS_ThrowF,
  ftCo_MS_ThrowB,
  ftCo_MS_ThrowHi,
  ftCo_MS_ThrowLw,
  ftCo_MS_CapturePulledHi,
  ftCo_MS_CaptureWaitHi,
  ftCo_MS_CaptureDamageHi,
  ftCo_MS_CapturePulledLw,
  ftCo_MS_CaptureWaitLw,
  ftCo_MS_CaptureDamageLw,
  ftCo_MS_CaptureCut,
  ftCo_MS_CaptureJump,
  ftCo_MS_CaptureNeck,
  ftCo_MS_CaptureFoot,
  ftCo_MS_EscapeF,
  ftCo_MS_EscapeB,
  ftCo_MS_EscapeN,
  ftCo_MS_EscapeAir,
  ftCo_MS_ReboundStop,
  ftCo_MS_Rebound,
  ftCo_MS_ThrownF,
  ftCo_MS_ThrownB,
  ftCo_MS_ThrownHi,
  ftCo_MS_ThrownLw,
  ftCo_MS_ThrownlwWomen,
  ftCo_MS_Pass,
  ftCo_MS_Ottotto,
  ftCo_MS_OttottoWait,
  ftCo_MS_FlyReflectWall,
  ftCo_MS_FlyReflectCeil,
  ftCo_MS_StopWall,
  ftCo_MS_StopCeil,
  ftCo_MS_MissFoot,
  ftCo_MS_CliffCatch,
  ftCo_MS_CliffWait,
  ftCo_MS_CliffClimbSlow,
  ftCo_MS_CliffClimbQuick,
  ftCo_MS_CliffAttackSlow,
  ftCo_MS_CliffAttackQuick,
  ftCo_MS_CliffEscapeSlow,
  ftCo_MS_CliffEscapeQuick,
  ftCo_MS_CliffJumpSlow1,
  ftCo_MS_CliffJumpSlow2,
  ftCo_MS_CliffJumpQuick1,
  ftCo_MS_CliffJumpQuick2,
  ftCo_MS_AppealSR,
  ftCo_MS_AppealSL,
  ftCo_MS_ShoulderedWait,
  ftCo_MS_ShoulderedWalkSlow,
  ftCo_MS_ShoulderedWalkMiddle,
  ftCo_MS_ShoulderedWalkFast,
  ftCo_MS_ShoulderedTurn,
  ftCo_MS_ThrownFF,
  ftCo_MS_ThrownFB,
  ftCo_MS_ThrownFHi,
  ftCo_MS_ThrownFLw,
  ftCo_MS_CaptureCaptain,
  ftCo_MS_CaptureYoshi,
  ftCo_MS_YoshiEgg,
  ftCo_MS_CaptureKoopa,
  ftCo_MS_CaptureDamageKoopa,
  ftCo_MS_CaptureWaitKoopa,
  ftCo_MS_ThrownKoopaF,
  ftCo_MS_ThrownKoopaB,
  ftCo_MS_CaptureKoopaAir,
  ftCo_MS_CaptureDamageKoopaAir,
  ftCo_MS_CaptureWaitKoopaAir,
  ftCo_MS_ThrownKoopaAirF,
  ftCo_MS_ThrownKoopaAirB,
  ftCo_MS_CaptureKirby,
  ftCo_MS_CaptureWaitKirby,
  ftCo_MS_ThrownKirbyStar,
  ftCo_MS_ThrownCopyStar,
  ftCo_MS_ThrownKirby,
  ftCo_MS_BarrelWait,
  ftCo_MS_Bury,
  ftCo_MS_BuryWait,
  ftCo_MS_BuryJump,
  ftCo_MS_DamageSong,
  ftCo_MS_DamageSongWait,
  ftCo_MS_DamageSongRv,
  ftCo_MS_DamageBind,
  ftCo_MS_CaptureMewtwo,
  ftCo_MS_CaptureMewtwoAir,
  ftCo_MS_ThrownMewtwo,
  ftCo_MS_ThrownMewtwoAir,
  ftCo_MS_WarpStarJump,
  ftCo_MS_WarpStarFall,
  ftCo_MS_HammerWait,
  ftCo_MS_HammerWalk,
  ftCo_MS_HammerTurn,
  ftCo_MS_HammerKneeBend,
  ftCo_MS_HammerFall,
  ftCo_MS_HammerJump,
  ftCo_MS_HammerLanding,
  ftCo_MS_KinokoGiantStart,
  ftCo_MS_KinokoGiantStartAir,
  ftCo_MS_KinokoGiantEnd,
  ftCo_MS_KinokoGiantEndAir,
  ftCo_MS_KinokoSmallStart,
  ftCo_MS_KinokoSmallStartAir,
  ftCo_MS_KinokoSmallEnd,
  ftCo_MS_KinokoSmallEndAir,
  ftCo_MS_Entry,
  ftCo_MS_EntryStart,
  ftCo_MS_EntryEnd,
  ftCo_MS_DamageIce,
  ftCo_MS_DamageIceJump,
  ftCo_MS_CaptureMasterHand,
  ftCo_MS_CaptureDamageMasterHand,
  ftCo_MS_CaptureWaitMasterHand,
  ftCo_MS_ThrownMasterHand,
  ftCo_MS_CaptureKirbyYoshi,
  ftCo_MS_KirbyYoshiEgg,
  ftCo_MS_CaptureLeadead,
  ftCo_MS_CaptureLikelike,
  ftCo_MS_DownReflect,
  ftCo_MS_CaptureCrazyHand,
  ftCo_MS_CaptureDamageCrazyHand,
  ftCo_MS_CaptureWaitCrazyHand,
  ftCo_MS_ThrownCrazyHand,
  ftCo_MS_Barrel,
  ftCo_MS_Count
} ftCommon_MotionState;
typedef enum ftCo_Submotion
{
  ftCo_SM_None = -1,
  ftCo_SM_DeadUpFallHitCamera,
  ftCo_SM_DeadUpFallHitCameraFlat,
  ftCo_SM_Wait1_0,
  ftCo_SM_Wait2,
  ftCo_SM_Unk004,
  ftCo_SM_Unk005,
  ftCo_SM_Wait1_1,
  ftCo_SM_WalkSlow,
  ftCo_SM_WalkMiddle,
  ftCo_SM_WalkFast,
  ftCo_SM_Turn,
  ftCo_SM_TurnRun,
  ftCo_SM_Dash,
  ftCo_SM_Run,
  ftCo_SM_RunBrake,
  ftCo_SM_Kneebend,
  ftCo_SM_JumpF,
  ftCo_SM_JumpB,
  ftCo_SM_JumpAerialF,
  ftCo_SM_JumpAerialB,
  ftCo_SM_Fall,
  ftCo_SM_FallF,
  ftCo_SM_FallB,
  ftCo_SM_FallAerial,
  ftCo_SM_FallAerialF,
  ftCo_SM_FallAerialB,
  ftCo_SM_FallSpecial,
  ftCo_SM_FallSpecialF,
  ftCo_SM_FallSpecialB,
  ftCo_SM_DamageFall,
  ftCo_SM_Squat,
  ftCo_SM_SquatWait,
  ftCo_SM_Unk032,
  ftCo_SM_SquatWaitItem,
  ftCo_SM_SquatRv,
  ftCo_SM_Landing,
  ftCo_SM_LandingFallSpecial,
  ftCo_SM_GuardOn,
  ftCo_SM_Guard,
  ftCo_SM_GuardOff,
  ftCo_SM_GuardDamage,
  ftCo_SM_EscapeN,
  ftCo_SM_EscapeF,
  ftCo_SM_EscapeB,
  ftCo_SM_EscapeAir,
  ftCo_SM_Rebound,
  ftCo_SM_Attack11,
  ftCo_SM_Attack12,
  ftCo_SM_Attack13,
  ftCo_SM_Attack100Start,
  ftCo_SM_Attack100Loop,
  ftCo_SM_Attack100End,
  ftCo_SM_AttackDash,
  ftCo_SM_AttackS3Hi,
  ftCo_SM_AttackS3HiS,
  ftCo_SM_AttackS3,
  ftCo_SM_AttackS3LwS,
  ftCo_SM_AttackS3Lw,
  ftCo_SM_AttackHi3,
  ftCo_SM_AttackLw3,
  ftCo_SM_AttackS4Hi,
  ftCo_SM_AttackS4HiS,
  ftCo_SM_AttackS4,
  ftCo_SM_AttackS4LwS,
  ftCo_SM_AttackS4Lw,
  ftCo_SM_Unk065,
  ftCo_SM_AttackHi4,
  ftCo_SM_AttackLw4,
  ftCo_SM_AttackAirN,
  ftCo_SM_AttackAirF,
  ftCo_SM_AttackAirB,
  ftCo_SM_AttackAirHi,
  ftCo_SM_AttackAirLw,
  ftCo_SM_LandingAirN,
  ftCo_SM_LandingAirF,
  ftCo_SM_LandingAirB,
  ftCo_SM_LandingAirHi,
  ftCo_SM_LandingAirLw,
  ftCo_SM_LightGet,
  ftCo_SM_LightThrowF,
  ftCo_SM_LightThrowB,
  ftCo_SM_LightThrowHi,
  ftCo_SM_LightThrowLw,
  ftCo_SM_LightThrowDash,
  ftCo_SM_LightThrowDrop,
  ftCo_SM_LightThrowAirF,
  ftCo_SM_LightThrowAirB,
  ftCo_SM_LightThrowAirHi,
  ftCo_SM_LightThrowAirLw,
  ftCo_SM_HeavyGet,
  ftCo_SM_HeavyWalk1,
  ftCo_SM_HeavyWalk2,
  ftCo_SM_HeavyThrowF,
  ftCo_SM_HeavyThrowB,
  ftCo_SM_HeavyThrowHi,
  ftCo_SM_HeavyThrowLw,
  ftCo_SM_LightThrowF4,
  ftCo_SM_LightThrowB4,
  ftCo_SM_LightThrowHi4,
  ftCo_SM_LightThrowLw4,
  ftCo_SM_LightThrowAirF4,
  ftCo_SM_LightThrowAirB4,
  ftCo_SM_LightThrowAirHi4,
  ftCo_SM_LightThrowAirLw4,
  ftCo_SM_HeavyThrowF4,
  ftCo_SM_HeavyThrowB4,
  ftCo_SM_HeavyThrowHi4,
  ftCo_SM_HeavyThrowLw4,
  ftCo_SM_SwordSwing1,
  ftCo_SM_SwordSwing3,
  ftCo_SM_SwordSwing4,
  ftCo_SM_SwordSwingDash,
  ftCo_SM_BatSwing1,
  ftCo_SM_BatSwing3,
  ftCo_SM_BatSwing4,
  ftCo_SM_BatSwingDash,
  ftCo_SM_ParasolSwing1,
  ftCo_SM_ParasolSwing3,
  ftCo_SM_ParasolSwing4,
  ftCo_SM_ParasolSwingDash,
  ftCo_SM_HarisenSwing1,
  ftCo_SM_HarisenSwing3,
  ftCo_SM_HarisenSwing4,
  ftCo_SM_HarisenSwingDash,
  ftCo_SM_StarRodSwing1,
  ftCo_SM_StarRodSwing3,
  ftCo_SM_StarRodSwing4,
  ftCo_SM_StarRodSwingDash,
  ftCo_SM_LipstickSwing1,
  ftCo_SM_LipstickSwing3,
  ftCo_SM_LipstickSwing4,
  ftCo_SM_LipstickSwingDash,
  ftCo_SM_HammerWait,
  ftCo_SM_HammerMove,
  ftCo_SM_ItemParasolOpen,
  ftCo_SM_ItemParasolFall,
  ftCo_SM_ItemParasolFallSpecial,
  ftCo_SM_ItemParasolDamageFall,
  ftCo_SM_LGunShoot,
  ftCo_SM_LGunShootAir,
  ftCo_SM_LGunShootEmpty,
  ftCo_SM_LGunShootAirEmpty,
  ftCo_SM_FireFlowerShoot,
  ftCo_SM_FireFlowerShootAir,
  ftCo_SM_ItemScrew,
  ftCo_SM_ItemScrewAir,
  ftCo_SM_ItemScrewDamage,
  ftCo_SM_ItemScrewDamageAir,
  ftCo_SM_ItemBlind,
  ftCo_SM_ItemScopeStart,
  ftCo_SM_ItemScopeRapid,
  ftCo_SM_ItemScopeFire,
  ftCo_SM_ItemScopeEnd,
  ftCo_SM_ItemScopeAirStart,
  ftCo_SM_ItemScopeAirRapid,
  ftCo_SM_ItemScopeAirFire,
  ftCo_SM_ItemScopeAirEnd,
  ftCo_SM_ItemScopeStartEmpty,
  ftCo_SM_ItemScopeRapidEmpty,
  ftCo_SM_ItemScopeFireEmpty,
  ftCo_SM_ItemScopeEndEmpty,
  ftCo_SM_ItemScopeAirStartEmpty,
  ftCo_SM_ItemScopeAirRapidEmpty,
  ftCo_SM_ItemScopeAirFireEmpty,
  ftCo_SM_ItemScopeAirEndEmpty,
  ftCo_SM_DamageHi1,
  ftCo_SM_DamageHi2,
  ftCo_SM_DamageHi3,
  ftCo_SM_DamageN1,
  ftCo_SM_DamageN2,
  ftCo_SM_DamageN3,
  ftCo_SM_DamageLw1,
  ftCo_SM_DamageLw2,
  ftCo_SM_DamageLw3,
  ftCo_SM_DamageAir1,
  ftCo_SM_DamageAir2,
  ftCo_SM_DamageAir3,
  ftCo_SM_DamageFlyHi,
  ftCo_SM_DamageFlyN,
  ftCo_SM_DamageFlyLw,
  ftCo_SM_DamageFlyTop,
  ftCo_SM_DamageFlyRoll,
  ftCo_SM_Unk182,
  ftCo_SM_DownBoundU,
  ftCo_SM_DownWaitU,
  ftCo_SM_DownDamageU,
  ftCo_SM_DownStandU,
  ftCo_SM_DownAttackU,
  ftCo_SM_DownFowardU,
  ftCo_SM_DownBackU,
  ftCo_SM_DownSpotU,
  ftCo_SM_DownBoundD,
  ftCo_SM_DownWaitD,
  ftCo_SM_DownDamageD,
  ftCo_SM_DownStandD,
  ftCo_SM_DownAttackD,
  ftCo_SM_DownFowardD,
  ftCo_SM_DownBackD,
  ftCo_SM_DownSpotD,
  ftCo_SM_Passive,
  ftCo_SM_PassiveStandF,
  ftCo_SM_PassiveStandB,
  ftCo_SM_PassiveWall,
  ftCo_SM_PassiveWallJump,
  ftCo_SM_PassiveCeil,
  ftCo_SM_FuraFura,
  ftCo_SM_FuraSleepStart,
  ftCo_SM_FuraSleepLoop,
  ftCo_SM_FuraSleepEnd,
  ftCo_SM_Pass,
  ftCo_SM_Ottotto,
  ftCo_SM_OttottoWait,
  ftCo_SM_WallDamage,
  ftCo_SM_StopWall,
  ftCo_SM_StopCeil,
  ftCo_SM_MissFoot,
  ftCo_SM_CliffCatch,
  ftCo_SM_CliffWait,
  ftCo_SM_Unk218,
  ftCo_SM_CliffClimbSlow,
  ftCo_SM_CliffClimbQuick,
  ftCo_SM_CliffAttackSlow,
  ftCo_SM_CliffAttackQuick,
  ftCo_SM_CliffEscapeSlow,
  ftCo_SM_CliffEscapeQuick,
  ftCo_SM_CliffJumpSlow1,
  ftCo_SM_CliffJumpSlow2,
  ftCo_SM_CliffJumpQuick1,
  ftCo_SM_CliffJumpQuick2,
  ftCo_SM_Unk229,
  ftCo_SM_Unk230,
  ftCo_SM_Unk231,
  ftCo_SM_Unk232,
  ftCo_SM_Unk233,
  ftCo_SM_Unk234,
  ftCo_SM_Unk235,
  ftCo_SM_Unk236,
  ftCo_SM_Unk237,
  ftCo_SM_EntryStart,
  ftCo_SM_AppealSR,
  ftCo_SM_AppealSL,
  ftCo_SM_Unk241,
  ftCo_SM_Catch,
  ftCo_SM_CatchDash,
  ftCo_SM_CatchWait,
  ftCo_SM_CatchAttack,
  ftCo_SM_CatchCut,
  ftCo_SM_ThrowF,
  ftCo_SM_ThrowB,
  ftCo_SM_ThrowHi,
  ftCo_SM_ThrowLw,
  ftCo_SM_CapturePulledHi,
  ftCo_SM_CaptureWaitHi,
  ftCo_SM_CaptureDamageHi,
  ftCo_SM_CapturePulledLw,
  ftCo_SM_CaptureWaitLw,
  ftCo_SM_CaptureDamageLw,
  ftCo_SM_CaptureCut,
  ftCo_SM_CaptureJump,
  ftCo_SM_CaptureNeck,
  ftCo_SM_CaptureFoot,
  ftCo_SM_Unk261,
  ftCo_SM_ThrownF,
  ftCo_SM_ThrownB,
  ftCo_SM_ThrownHi,
  ftCo_SM_ThrownLw,
  ftCo_SM_ThrownlwWomen,
  ftCo_SM_ShoulderedWait,
  ftCo_SM_ShoulderedWalkSlow,
  ftCo_SM_ShoulderedWalkMiddle,
  ftCo_SM_ShoulderedWalkFast,
  ftCo_SM_ShoulderedTurn,
  ftCo_SM_ThrownFF,
  ftCo_SM_ThrownFB,
  ftCo_SM_ThrownFHi,
  ftCo_SM_ThrownFLw,
  ftCo_SM_CaptureCaptain,
  ftCo_SM_YoshiEgg,
  ftCo_SM_CaptureDamageKoopa,
  ftCo_SM_ThrownKoopaF,
  ftCo_SM_ThrownKoopaB,
  ftCo_SM_CaptureDamageKoopaAir,
  ftCo_SM_ThrownKoopaAirF,
  ftCo_SM_ThrownKoopaAirB,
  ftCo_SM_ThrownCopyStar,
  ftCo_SM_ThrownKirbyStar,
  ftCo_SM_ShieldBreakFly,
  ftCo_SM_ShieldBreakFall,
  ftCo_SM_ShieldBreakDownU,
  ftCo_SM_ShieldBreakDownD,
  ftCo_SM_ShieldBreakStandU,
  ftCo_SM_ShieldBreakStandD,
  ftCo_SM_ThrownMewtwo,
  ftCo_SM_ThrownMewtwoAir,
  ftCo_SM_KirbyYoshiEgg,
  ftCo_SM_Count
} ftCo_Submotion;
typedef enum ftCo_Surface
{
  FTCO_Surface_None,
  ftCo_Surface_LeftWall,
  ftCo_Surface_RightWall,
  ftCo_Surface_Ceiling
} ftCo_Surface;
typedef struct mpIsland_PaletteEntry mpIsland_PaletteEntry;
typedef struct mpIsland_Palette mpIsland_Palette;
typedef struct mp_UnkStruct0 mp_UnkStruct0;
typedef struct MapLine MapLine;
typedef struct CollLine CollLine;
typedef struct mp_UnkStruct3 mp_UnkStruct3;
typedef struct mpisland mpisland;
typedef struct CollVtx CollVtx;
typedef struct MapJoint MapJoint;
typedef struct CollJoint CollJoint;
typedef struct MapCollData MapCollData;
typedef enum mp_Terrain
{
  mp_Terrain_Basic,
  mp_Terrain_Rock,
  mp_Terrain_Grass,
  mp_Terrain_Dirt,
  mp_Terrain_Wood,
  mp_Terrain_LightMetal,
  mp_Terrain_HeavyMetal,
  mp_Terrain_Paper,
  mp_Terrain_Goop,
  mp_Terrain_Birdo,
  mp_Terrain_Water,
  mp_Terrain_Unk11,
  mp_Terrain_UFO,
  mp_Terrain_Turtle,
  mp_Terrain_Snow,
  mp_Terrain_Ice,
  mp_Terrain_GnW,
  mp_Terrain_Unk17,
  mp_Terrain_Checkered,
  mp_Terrain_Unk19
} mp_Terrain;
typedef enum mpLib_GroundEnum
{
  mpLib_GroundEnum_Unk0,
  mpLib_GroundEnum_Unk1,
  mpLib_GroundEnum_Unk2
} mpLib_GroundEnum;
typedef void (*mpLib_Callback)(Ground *, s32, CollData *, s32, mpLib_GroundEnum, f32);
typedef bool (*mpColl_Callback)(CollData *, u32);
typedef enum CollLineKind
{
  CollLine_Floor = 1 << 0,
  CollLine_Ceiling = 1 << 1,
  CollLine_RightWall = 1 << 2,
  CollLine_LeftWall = 1 << 3
} CollLineKind;
enum CollDataX130Flags
{
  CollData_X130_Locked = 1 << 4,
  CollData_X130_Clear = 1 << 5
};
enum CollJointFlags
{
  CollJoint_B8 = 1 << 8,
  CollJoint_B9 = 1 << 9,
  CollJoint_B10 = 1 << 10,
  CollJoint_B11 = 1 << 11,
  CollJoint_TooFar = 1 << 12,
  CollJoint_Enabled = 1 << 16,
  CollJoint_Hidden = 1 << 18
};
void mpColl_80041C78(void);
void mpCollPrev(CollData *cd);
void mpCollCheckBounding(CollData *cd, u32 flags);
void mpColl_80041EE4(CollData *);
void mpColl_SetECBSource_JObj(CollData *cd, HSD_GObj *gobj, HSD_JObj *, HSD_JObj *, HSD_JObj *, HSD_JObj *, HSD_JObj *, HSD_JObj *, HSD_JObj *, float);
void mpColl_SetECBSource_Fixed(CollData *cd, HSD_GObj *gobj, float, float, float, float);
void mpColl_SetLedgeSnap(CollData *, float, float, float);
void mpColl_80042384(CollData *cd);
void mpColl_LoadECB_JObj(CollData *, u32 flags);
void mpColl_LoadECB_Fixed(CollData *);
void mpColl_80042C58(CollData *, ftCollisionBox *);
void mpColl_LoadECB(CollData *);
void mpCollInterpolateECB(CollData *, float time);
void mpColl_80043268(CollData *, int line_id, bool, float);
void mpCollEnd(CollData *, bool, bool);
void mpColl_80043558(CollData *, int line_id);
void mpColl_80043670(CollData *);
void mpColl_80043680(CollData *, Vec3 *);
void mpCollSetFacingDir(CollData *, int facing_dir);
void mpColl_800436E4(CollData *, float);
bool mpColl_80043754(mpColl_Callback, CollData *, u32);
void mpColl_800439FC(CollData *);
void mpColl_80043ADC(CollData *);
bool mpColl_80043BBC(CollData *, int *line_id_out);
void mpColl_80043C6C(CollData *, int, bool);
bool mpColl_80043E90(CollData *, int *line_id_out);
void mpColl_80043F40(CollData *, int, bool);
bool mpColl_80044164(CollData *cd, int *p_ledge_id);
bool mpColl_800443C4(CollData *cd, int *p_ledge_id);
bool mpColl_80044628_Floor(CollData *, bool (*)(Fighter_GObj *, int), Fighter_GObj *, int);
bool mpColl_80044838_Floor(CollData *coll, bool ignore_bottom);
bool mpColl_80044948_Floor(CollData *coll);
bool mpColl_80044AD8_Ceiling(CollData *, int);
bool mpColl_80044C74_Ceiling(CollData *);
bool mpColl_80044E10_RightWall(CollData *);
bool mpColl_800454A4_RightWall(CollData *);
bool mpColl_80045B74_LeftWall(CollData *);
bool mpColl_80046224_LeftWall(CollData *);
bool mpColl_80046904(CollData *, u32 flags);
bool mpColl_80046F78(CollData *, u32);
bool mpColl_800471F8(CollData *);
bool mpColl_8004730C(CollData *, ftCollisionBox *);
bool mpColl_800473CC(CollData *);
bool mpColl_800474E0(CollData *);
bool mpColl_800475F4(CollData *, ftCollisionBox *);
bool mpColl_800476B4(CollData *, bool (*)(Fighter_GObj *, enum_t), Fighter_GObj *);
bool mpColl_800477E0(CollData *);
bool mpColl_800478F4(CollData *);
bool mpColl_80047A08(CollData *, ftCollisionBox *);
bool mpColl_80047AC8(CollData *, bool (*)(Fighter_GObj *, enum_t), Fighter_GObj *);
bool mpColl_80047BF4(CollData *, bool (*)(Fighter_GObj *, enum_t), Fighter_GObj *);
bool mpColl_80047D20(CollData *, bool (*)(Fighter_GObj *, enum_t), Fighter_GObj *);
bool mpColl_80047E14(CollData *, bool (*)(Fighter_GObj *, enum_t), Fighter_GObj *);
bool mpColl_80047F40(CollData *, bool (*)(Fighter_GObj *, enum_t), Fighter_GObj *);
bool mpColl_8004806C(CollData *, bool (*)(Fighter_GObj *, enum_t), Fighter_GObj *);
bool mpColl_80048160(CollData *);
bool mpColl_80048274(CollData *);
bool mpColl_80048388(CollData *);
bool mpColl_80048464(CollData *);
bool mpColl_80048578(CollData *);
bool mpColl_80048654(CollData *);
bool mpColl_80048768(CollData *);
bool mpColl_80048844(CollData *, f32);
bool mpColl_800488F4(CollData *);
bool mpColl_80048AB0_RightWall(CollData *);
bool mpColl_800491C8_RightWall(CollData *);
bool mpColl_80049778_LeftWall(CollData *);
bool mpColl_80049EAC_LeftWall(CollData *);
bool mpColl_8004A45C_Floor(CollData *, int line_id);
bool mpColl_8004A678_Floor(CollData *, int line_id);
bool mpColl_8004A908_Floor(CollData *, int line_id);
bool mpColl_8004AB80(CollData *);
bool mpColl_8004ACE4(CollData *, int);
bool mpColl_8004B108(CollData *);
bool mpColl_8004B21C(CollData *, ftCollisionBox *);
bool mpColl_8004B2DC(CollData *);
bool mpColl_8004B3F0(CollData *, ftCollisionBox *);
bool mpColl_8004B4B0(CollData *);
bool mpColl_8004B5C4(CollData *);
bool mpColl_8004B6D8(CollData *);
bool mpColl_8004B894_RightWall(CollData *);
bool mpColl_8004BDD4_LeftWall(CollData *);
bool mpColl_8004C328_Ceiling(CollData *, int line_id);
bool mpColl_8004C534(CollData *, u32);
bool mpColl_8004C750(CollData *);
void mpCollSqueezeHorizontal(CollData *, bool airborne, float left, float right);
void mpCollSqueezeVertical(CollData *, bool airborne, float top, float bottom);
float mpColl_8004CA6C(CollData *);
bool mpCollGetSpeedCeiling(CollData *, Vec3 *speed);
bool mpCollGetSpeedLeftWall(CollData *, Vec3 *speed);
bool mpCollGetSpeedRightWall(CollData *, Vec3 *speed);
bool mpCollGetSpeedFloor(CollData *, Vec3 *speed);
bool mpColl_IsOnPlatform(CollData *);
void mpUpdateFloorSkip(CollData *);
void mpClearFloorSkip(CollData *);
void mpCopyCollData(CollData *src, CollData *dst, int);
bool mpColl_8004D024(Vec3 *);
extern int mpColl_804D64AC;
void __sync(void);
void __isync(void);
int __cntlzw(unsigned int);
float sqrtf__Ff(float);
float __fnmsubs(float, float, float);
double __fabs(double);
float __fabsf(float);
double __frsqrte(double);
void *__memcpy(void *dst, const void *src, unsigned long n);
static const float deg_to_rad = 3.14159265358979323846 / 180;
static const float rad_to_deg = 180 / 3.14159265358979323846;
enum FloatType
{
  FP_NAN = 1,
  FP_INFINITE = 2,
  FP_ZERO = 3,
  FP_NORMAL = 4,
  FP_SUBNORMAL = 5
};
inline static s32 __fpclassifyf(float x)
{
  const s32 exp_mask = 0b01111111100000000000000000000000;
  const s32 mantissa_mask = 0b00000000011111111111111111111111;
  switch ((*((s32 *) (&x))) & exp_mask)
  {
    case exp_mask:
      return ((*((s32 *) (&x))) & mantissa_mask) ? (FP_NAN) : (FP_INFINITE);

    case 0:
      return ((*((s32 *) (&x))) & mantissa_mask) ? (FP_SUBNORMAL) : (FP_ZERO);

    default:
      return FP_NORMAL;

  }

}

extern int __HI(double);
extern int __LO(double);
inline static s32 __fpclassifyd(double x)
{
  switch (__HI(x) & 0x7ff00000)
  {
    case 0x7ff00000:
      return ((__HI(x) & 0x000fffff) || (__LO(x) & 0xffffffff)) ? (FP_NAN) : (FP_INFINITE);

    case 0:
      return ((__HI(x) & 0x000fffff) || (__LO(x) & 0xffffffff)) ? (FP_SUBNORMAL) : (FP_ZERO);

    default:
      return FP_NORMAL;

  }

}

inline static double fabs(double f)
{
  return __fabs(f);
}

double frexp(double x, int *exponent);
float fabsf__Ff(float);
float tanf(float x);
float cos__Ff(float x);
float sin__Ff(float x);
float cosf(float x);
float sinf(float x);
void __sinit_trigf_c(void);
float logf(float);
typedef struct Article Article;
typedef struct BobOmbRain BobOmbRain;
typedef struct BoneDynamicsDesc BoneDynamicsDesc;
typedef struct CameraBoxFlags CameraBoxFlags;
typedef struct DynamicBoneTable DynamicBoneTable;
typedef struct flag32 flag32;
typedef struct HSD_ObjAllocUnk HSD_ObjAllocUnk;
typedef struct HSD_ObjAllocUnk2 HSD_ObjAllocUnk2;
typedef struct HSD_ObjAllocUnk4 HSD_ObjAllocUnk4;
typedef struct HSD_ObjAllocUnk5 HSD_ObjAllocUnk5;
typedef struct HSD_ObjAllocUnk6 HSD_ObjAllocUnk6;
typedef struct it_2F28_DatAttrs it_2F28_DatAttrs;
typedef struct Item Item;
typedef struct Item_DynamicBones Item_DynamicBones;
typedef struct ItemAttr ItemAttr;
typedef struct ItemCommonData ItemCommonData;
typedef struct ItemDynamics ItemDynamics;
typedef struct ItemModelDesc ItemModelDesc;
typedef struct ItemModStruct ItemModStruct;
typedef struct ItemStateArray ItemStateArray;
typedef struct ItemStateDesc ItemStateDesc;
typedef struct itSword_ItemVars itSword_ItemVars;
typedef struct SpawnItem SpawnItem;
typedef struct UnkItemArticles3 UnkItemArticles3;
typedef HSD_GObj Item_GObj;
typedef void (*ItCmd)(Item_GObj *gobj, CommandInfo *cmd);
typedef enum Item_StateChangeFlags
{
  ITEM_UNK_0x1 = 1 << 0,
  ITEM_ANIM_UPDATE = 1 << 1,
  ITEM_DROP_UPDATE = 1 << 2,
  ITEM_MODEL_UPDATE = 1 << 3,
  ITEM_HIT_PRESERVE = 1 << 4,
  ITEM_SFX_PRESERVE = 1 << 5,
  ITEM_COLANIM_PRESERVE = 1 << 6,
  ITEM_UNK_UPDATE = 1 << 7,
  ITEM_CMD_UPDATE = 1 << 8
} Item_StateChangeFlags;
typedef enum Item_UnkKinds
{
  ITEM_UNK_MATO = 4,
  ITEM_UNK_LOCKON,
  ITEM_UNK_ENEMY,
  ITEM_UNK_7
} Item_UnkKinds;
typedef enum Item_HoldKinds
{
  ITEM_HOLD_0,
  ITEM_HOLD_1,
  ITEM_HOLD_2,
  ITEM_HOLD_3,
  ITEM_HOLD_4,
  ITEM_HOLD_5,
  ITEM_HOLD_6,
  ITEM_HOLD_7,
  ITEM_HOLD_8,
  ITEM_HOLD_9,
  ITEM_HOLD_10,
  ITEM_HOLD_11,
  ITEM_HOLD_12
} Item_HoldKinds;
typedef enum ItemKind
{
  It_Kind_Capsule,
  It_Kind_Box,
  It_Kind_Taru,
  It_Kind_Egg,
  It_Kind_Kusudama,
  It_Kind_TaruCann,
  It_Kind_BombHei,
  It_Kind_Dosei,
  It_Kind_Heart,
  It_Kind_Tomato,
  It_Kind_Star,
  It_Kind_Bat,
  It_Kind_Sword,
  It_Kind_Parasol,
  It_Kind_G_Shell,
  It_Kind_R_Shell,
  It_Kind_L_Gun,
  It_Kind_Freeze,
  It_Kind_Foods,
  It_Kind_MSBomb,
  It_Kind_Flipper,
  It_Kind_S_Scope,
  It_Kind_StarRod,
  It_Kind_LipStick,
  It_Kind_Harisen,
  It_Kind_F_Flower,
  It_Kind_Kinoko,
  It_Kind_DKinoko,
  It_Kind_Hammer,
  It_Kind_WStar,
  It_Kind_ScBall,
  It_Kind_RabbitC,
  It_Kind_MetalB,
  It_Kind_Spycloak,
  It_Kind_M_Ball,
  It_Kind_L_Gun_Ray,
  It_Kind_StarRod_Star,
  It_Kind_LipStick_Spore,
  It_Kind_S_Scope_Beam,
  It_Kind_L_Gun_Beam,
  It_Kind_Hammer_Head,
  It_Kind_F_Flower_Flame,
  It_Kind_EvYoshiEgg,
  It_Kind_Kuriboh,
  It_Kind_Leadead,
  It_Kind_Octarock,
  It_Kind_Ottosea,
  It_Kind_Octarock_Stone,
  It_Kind_Mario_Fire,
  It_Kind_DrMario_Vitamin,
  It_Kind_Kirby_CBeam,
  It_Kind_Kirby_Hammer,
  It_Kind_Unk1,
  It_Kind_Unk2,
  It_Kind_Fox_Laser,
  It_Kind_Falco_Laser,
  It_Kind_Fox_Illusion,
  It_Kind_Falco_Phantasm,
  It_Kind_Link_Bomb,
  It_Kind_CLink_Bomb,
  It_Kind_Link_Boomerang,
  It_Kind_CLink_Boomerang,
  It_Kind_Link_HShot,
  It_Kind_CLink_HShot,
  It_Kind_Link_Arrow,
  It_Kind_CLink_Arrow,
  It_Kind_Ness_PKFire,
  It_Kind_Ness_PKFire_Flame,
  It_Kind_Ness_PKFlush,
  It_Kind_Ness_PKThunder,
  It_Kind_Ness_PKThunder1,
  It_Kind_Ness_PKThunder2,
  It_Kind_Ness_PKThunder3,
  It_Kind_Ness_PKThunder4,
  It_Kind_Fox_Blaster,
  It_Kind_Falco_Blaster,
  It_Kind_Link_Bow,
  It_Kind_CLink_Bow,
  It_Kind_Ness_PKFlush_Explode,
  It_Kind_Seak_NeedleThrow,
  It_Kind_Seak_NeedleHeld,
  It_Kind_Pikachu_Thunder,
  It_Kind_Pichu_Thunder,
  It_Kind_Mario_Cape,
  It_Kind_DrMario_Sheet,
  It_Kind_Seak_Vanish,
  It_Kind_Yoshi_EggThrow,
  It_Kind_Yoshi_EggLay,
  It_Kind_Yoshi_Star,
  It_Kind_Pikachu_TJolt_Ground,
  It_Kind_Pikachu_TJolt_Air,
  It_Kind_Pichu_TJolt_Ground,
  It_Kind_Pichu_TJolt_Air,
  It_Kind_Samus_Bomb,
  It_Kind_Samus_Charge,
  It_Kind_Samus_Missile,
  It_Kind_Samus_GBeam,
  It_Kind_Seak_Chain,
  It_Kind_Peach_Explode,
  It_Kind_Peach_Turnip,
  It_Kind_Koopa_Flame,
  It_Kind_Ness_Bat,
  It_Kind_Ness_Yoyo,
  It_Kind_Peach_Parasol,
  It_Kind_Peach_Toad,
  It_Kind_Luigi_Fire,
  It_Kind_IceClimber_Ice,
  It_Kind_IceClimber_Blizzard,
  It_Kind_Zelda_DinFire,
  It_Kind_Zelda_DinFire_Explode,
  It_Kind_Mewtwo_Disable,
  It_Kind_Peach_ToadSpore,
  It_Kind_Mewtwo_ShadowBall,
  It_Kind_IceClimber_GumStrings,
  It_Kind_GameWatch_Greenhouse,
  It_Kind_GameWatch_Manhole,
  It_Kind_GameWatch_Fire,
  It_Kind_GameWatch_Parachute,
  It_Kind_GameWatch_Turtle,
  It_Kind_GameWatch_Breath,
  It_Kind_GameWatch_Judge,
  It_Kind_GameWatch_Panic,
  It_Kind_GameWatch_Chef,
  It_Kind_CLink_Milk,
  It_Kind_GameWatch_Rescue,
  It_Kind_MasterHand_Laser,
  It_Kind_MasterHand_Bullet,
  It_Kind_CrazyHand_Laser,
  It_Kind_CrazyHand_Bullet,
  It_Kind_CrazyHand_Bomb,
  It_Kind_Kirby_MarioFire,
  It_Kind_Kirby_DrMarioVitamin,
  It_Kind_Kirby_LuigiFire,
  It_Kind_Kirby_IceClimberIce,
  It_Kind_Kirby_PeachToad,
  It_Kind_Kirby_PeachToadSpore,
  It_Kind_Kirby_FoxLaser,
  It_Kind_Kirby_FalcoLaser,
  It_Kind_Kirby_FoxBlaster,
  It_Kind_Kirby_FalcoBlaster,
  It_Kind_Kirby_LinkArrow,
  It_Kind_Kirby_CLinkArrow,
  It_Kind_Kirby_LinkBow,
  It_Kind_Kirby_CLinkBow,
  It_Kind_Kirby_MewtwoShadowBall,
  It_Kind_Kirby_NessPKFlush,
  It_Kind_Kirby_NessPKFlush_Explode,
  It_Kind_Kirby_PikachuTJolt_Ground,
  It_Kind_Kirby_PikachuTJolt_Air,
  It_Kind_Kirby_PichuTJolt_Ground,
  It_Kind_Kirby_PichuTJolt_Air,
  It_Kind_Kirby_SamusCharge,
  It_Kind_Kirby_SeakNeedleThrow,
  It_Kind_Kirby_SeakNeedleHeld,
  It_Kind_Kirby_KoopaFlame,
  It_Kind_Kirby_GameWatchChef,
  It_Kind_Kirby_GameWatchChefPan,
  It_Kind_Kirby_YoshiEggLay,
  It_Kind_Unk4,
  It_Kind_Coin,
  Pokemon_Random,
  Pokemon_Tosakinto,
  Pokemon_Chicorita,
  Pokemon_Kabigon,
  Pokemon_Kamex,
  Pokemon_Matadogas,
  Pokemon_Lizardon,
  Pokemon_Fire,
  Pokemon_Thunder,
  Pokemon_Freezer,
  Pokemon_Sonans,
  Pokemon_Hassam,
  Pokemon_Unknown,
  Pokemon_Entei,
  Pokemon_Raikou,
  Pokemon_Suikun,
  Pokemon_Kireihana,
  Pokemon_Marumine,
  Pokemon_Lugia,
  Pokemon_Houou,
  Pokemon_Metamon,
  Pokemon_Pippi,
  Pokemon_Togepy,
  Pokemon_Mew,
  Pokemon_Cerebi,
  Pokemon_Hitodeman,
  Pokemon_Lucky,
  Pokemon_Porygon2,
  Pokemon_Hinoarashi,
  Pokemon_Maril,
  Pokemon_Fushigibana,
  Pokemon_Chicorita_Leaf,
  Pokemon_Kamex_HydroPump,
  Pokemon_Matadogas_Gas1,
  Pokemon_Matadogas_Gas2,
  Pokemon_Lizardon_Flame1,
  Pokemon_Lizardon_Flame2,
  Pokemon_Lizardon_Flame3,
  Pokemon_Lizardon_Flame4,
  Pokemon_Unknown_Swarm,
  Pokemon_Lugia_Aeroblast,
  Pokemon_Lugia_Aeroblast2,
  Pokemon_Lugia_Aeroblast3,
  Pokemon_Houou_SacredFire,
  Pokemon_Hitodeman_Star,
  Pokemon_Lucky_Egg,
  Pokemon_Hinoarashi_Flame,
  Pokemon_Unk,
  It_Kind_Old_Kuri,
  It_Kind_Mato,
  It_Kind_Heiho,
  It_Kind_Nokonoko,
  It_Kind_Patapata,
  It_Kind_Likelike,
  It_Kind_Old_Lead,
  It_Kind_Old_Octa,
  It_Kind_Old_Otto,
  It_Kind_Whitebea,
  It_Kind_Klap,
  It_Kind_ZGShell,
  It_Kind_ZRShell,
  It_Kind_Tincle,
  It_Kind_Invalid1,
  It_Kind_Invalid2,
  It_Kind_Invalid3,
  It_Kind_WhispyApple,
  It_Kind_WhispyHealApple,
  It_Kind_Invalid4,
  It_Kind_Invalid5,
  It_Kind_Invalid6,
  It_Kind_Tools,
  It_Kind_Invalid7,
  It_Kind_Invalid8,
  It_Kind_Kyasarin,
  It_Kind_Arwing_Laser,
  It_Kind_GreatFox_Laser,
  It_Kind_Kyasarin_Egg
} ItemKind;
typedef u8 GXBool;
typedef enum _GXProjectionType
{
  GX_PERSPECTIVE,
  GX_ORTHOGRAPHIC
} GXProjectionType;
typedef enum _GXCompare
{
  GX_NEVER,
  GX_LESS,
  GX_EQUAL,
  GX_LEQUAL,
  GX_GREATER,
  GX_NEQUAL,
  GX_GEQUAL,
  GX_ALWAYS
} GXCompare;
typedef enum _GXAlphaOp
{
  GX_AOP_AND,
  GX_AOP_OR,
  GX_AOP_XOR,
  GX_AOP_XNOR,
  GX_MAX_ALPHAOP
} GXAlphaOp;
typedef enum _GXZFmt16
{
  GX_ZC_LINEAR,
  GX_ZC_NEAR,
  GX_ZC_MID,
  GX_ZC_FAR
} GXZFmt16;
typedef enum _GXGamma
{
  GX_GM_1_0,
  GX_GM_1_7,
  GX_GM_2_2
} GXGamma;
typedef enum _GXPixelFmt
{
  GX_PF_RGB8_Z24,
  GX_PF_RGBA6_Z24,
  GX_PF_RGB565_Z16,
  GX_PF_Z24,
  GX_PF_Y8,
  GX_PF_U8,
  GX_PF_V8,
  GX_PF_YUV420
} GXPixelFmt;
typedef enum _GXPrimitive
{
  GX_QUADS = 0x80,
  GX_TRIANGLES = 0x90,
  GX_TRIANGLESTRIP = 0x98,
  GX_TRIANGLEFAN = 0xA0,
  GX_LINES = 0xA8,
  GX_LINESTRIP = 0xB0,
  GX_POINTS = 0xB8
} GXPrimitive;
typedef enum _GXVtxFmt
{
  GX_VTXFMT0,
  GX_VTXFMT1,
  GX_VTXFMT2,
  GX_VTXFMT3,
  GX_VTXFMT4,
  GX_VTXFMT5,
  GX_VTXFMT6,
  GX_VTXFMT7,
  GX_MAX_VTXFMT
} GXVtxFmt;
typedef enum _GXAttr
{
  GX_VA_PNMTXIDX,
  GX_VA_TEX0MTXIDX,
  GX_VA_TEX1MTXIDX,
  GX_VA_TEX2MTXIDX,
  GX_VA_TEX3MTXIDX,
  GX_VA_TEX4MTXIDX,
  GX_VA_TEX5MTXIDX,
  GX_VA_TEX6MTXIDX,
  GX_VA_TEX7MTXIDX,
  GX_VA_POS,
  GX_VA_NRM,
  GX_VA_CLR0,
  GX_VA_CLR1,
  GX_VA_TEX0,
  GX_VA_TEX1,
  GX_VA_TEX2,
  GX_VA_TEX3,
  GX_VA_TEX4,
  GX_VA_TEX5,
  GX_VA_TEX6,
  GX_VA_TEX7,
  GX_POS_MTX_ARRAY,
  GX_NRM_MTX_ARRAY,
  GX_TEX_MTX_ARRAY,
  GX_LIGHT_ARRAY,
  GX_VA_NBT,
  GX_VA_MAX_ATTR,
  GX_VA_NULL = 0xFF
} GXAttr;
typedef enum _GXAttrType
{
  GX_NONE,
  GX_DIRECT,
  GX_INDEX8,
  GX_INDEX16
} GXAttrType;
typedef enum _GXTexFmt
{
  GX_TF_I4 = 0x0,
  GX_TF_I8 = 0x1,
  GX_TF_IA4 = 0x2,
  GX_TF_IA8 = 0x3,
  GX_TF_RGB565 = 0x4,
  GX_TF_RGB5A3 = 0x5,
  GX_TF_RGBA8 = 0x6,
  GX_TF_CMPR = 0xE,
  GX_CTF_R4 = 0x0 | 0x20,
  GX_CTF_RA4 = 0x2 | 0x20,
  GX_CTF_RA8 = 0x3 | 0x20,
  GX_CTF_YUVA8 = 0x6 | 0x20,
  GX_CTF_A8 = 0x7 | 0x20,
  GX_CTF_R8 = 0x8 | 0x20,
  GX_CTF_G8 = 0x9 | 0x20,
  GX_CTF_B8 = 0xA | 0x20,
  GX_CTF_RG8 = 0xB | 0x20,
  GX_CTF_GB8 = 0xC | 0x20,
  GX_TF_Z8 = 0x1 | 0x10,
  GX_TF_Z16 = 0x3 | 0x10,
  GX_TF_Z24X8 = 0x6 | 0x10,
  GX_CTF_Z4 = (0x0 | 0x10) | 0x20,
  GX_CTF_Z8M = (0x9 | 0x10) | 0x20,
  GX_CTF_Z8L = (0xA | 0x10) | 0x20,
  GX_CTF_Z16L = (0xC | 0x10) | 0x20,
  GX_TF_A8 = GX_CTF_A8
} GXTexFmt;
typedef enum _GXCITexFmt
{
  GX_TF_C4 = 0x8,
  GX_TF_C8 = 0x9,
  GX_TF_C14X2 = 0xA
} GXCITexFmt;
typedef enum _GXTexWrapMode
{
  GX_CLAMP,
  GX_REPEAT,
  GX_MIRROR,
  GX_MAX_TEXWRAPMODE
} GXTexWrapMode;
typedef enum _GXTexFilter
{
  GX_NEAR,
  GX_LINEAR,
  GX_NEAR_MIP_NEAR,
  GX_LIN_MIP_NEAR,
  GX_NEAR_MIP_LIN,
  GX_LIN_MIP_LIN
} GXTexFilter;
typedef enum _GXAnisotropy
{
  GX_ANISO_1,
  GX_ANISO_2,
  GX_ANISO_4,
  GX_MAX_ANISOTROPY
} GXAnisotropy;
typedef enum _GXTexMapID
{
  GX_TEXMAP0,
  GX_TEXMAP1,
  GX_TEXMAP2,
  GX_TEXMAP3,
  GX_TEXMAP4,
  GX_TEXMAP5,
  GX_TEXMAP6,
  GX_TEXMAP7,
  GX_MAX_TEXMAP,
  GX_TEXMAP_NULL = 0xFF,
  GX_TEX_DISABLE = 0x100
} GXTexMapID;
typedef enum _GXTexCoordID
{
  GX_TEXCOORD0,
  GX_TEXCOORD1,
  GX_TEXCOORD2,
  GX_TEXCOORD3,
  GX_TEXCOORD4,
  GX_TEXCOORD5,
  GX_TEXCOORD6,
  GX_TEXCOORD7,
  GX_MAX_TEXCOORD,
  GX_TEXCOORD_NULL = 0xFF
} GXTexCoordID;
typedef enum _GXTevStageID
{
  GX_TEVSTAGE0,
  GX_TEVSTAGE1,
  GX_TEVSTAGE2,
  GX_TEVSTAGE3,
  GX_TEVSTAGE4,
  GX_TEVSTAGE5,
  GX_TEVSTAGE6,
  GX_TEVSTAGE7,
  GX_TEVSTAGE8,
  GX_TEVSTAGE9,
  GX_TEVSTAGE10,
  GX_TEVSTAGE11,
  GX_TEVSTAGE12,
  GX_TEVSTAGE13,
  GX_TEVSTAGE14,
  GX_TEVSTAGE15,
  GX_MAX_TEVSTAGE
} GXTevStageID;
typedef enum _GXTevMode
{
  GX_MODULATE,
  GX_DECAL,
  GX_BLEND,
  GX_REPLACE,
  GX_PASSCLR
} GXTevMode;
typedef enum _GXTexMtxType
{
  GX_MTX3x4,
  GX_MTX2x4
} GXTexMtxType;
typedef enum _GXTexGenType
{
  GX_TG_MTX3x4,
  GX_TG_MTX2x4,
  GX_TG_BUMP0,
  GX_TG_BUMP1,
  GX_TG_BUMP2,
  GX_TG_BUMP3,
  GX_TG_BUMP4,
  GX_TG_BUMP5,
  GX_TG_BUMP6,
  GX_TG_BUMP7,
  GX_TG_SRTG
} GXTexGenType;
typedef enum _GXPosNrmMtx
{
  GX_PNMTX0 = 0,
  GX_PNMTX1 = 3,
  GX_PNMTX2 = 6,
  GX_PNMTX3 = 9,
  GX_PNMTX4 = 12,
  GX_PNMTX5 = 15,
  GX_PNMTX6 = 18,
  GX_PNMTX7 = 21,
  GX_PNMTX8 = 24,
  GX_PNMTX9 = 27
} GXPosNrmMtx;
typedef enum _GXTexMtx
{
  GX_TEXMTX0 = 30,
  GX_TEXMTX1 = 33,
  GX_TEXMTX2 = 36,
  GX_TEXMTX3 = 39,
  GX_TEXMTX4 = 42,
  GX_TEXMTX5 = 45,
  GX_TEXMTX6 = 48,
  GX_TEXMTX7 = 51,
  GX_TEXMTX8 = 54,
  GX_TEXMTX9 = 57,
  GX_IDENTITY = 60
} GXTexMtx;
typedef enum _GXChannelID
{
  GX_COLOR0,
  GX_COLOR1,
  GX_ALPHA0,
  GX_ALPHA1,
  GX_COLOR0A0,
  GX_COLOR1A1,
  GX_COLOR_ZERO,
  GX_ALPHA_BUMP,
  GX_ALPHA_BUMPN,
  GX_COLOR_NULL = 0xFF
} GXChannelID;
typedef enum _GXTexGenSrc
{
  GX_TG_POS,
  GX_TG_NRM,
  GX_TG_BINRM,
  GX_TG_TANGENT,
  GX_TG_TEX0,
  GX_TG_TEX1,
  GX_TG_TEX2,
  GX_TG_TEX3,
  GX_TG_TEX4,
  GX_TG_TEX5,
  GX_TG_TEX6,
  GX_TG_TEX7,
  GX_TG_TEXCOORD0,
  GX_TG_TEXCOORD1,
  GX_TG_TEXCOORD2,
  GX_TG_TEXCOORD3,
  GX_TG_TEXCOORD4,
  GX_TG_TEXCOORD5,
  GX_TG_TEXCOORD6,
  GX_TG_COLOR0,
  GX_TG_COLOR1
} GXTexGenSrc;
typedef enum _GXBlendMode
{
  GX_BM_NONE,
  GX_BM_BLEND,
  GX_BM_LOGIC,
  GX_BM_SUBTRACT,
  GX_MAX_BLENDMODE
} GXBlendMode;
typedef enum _GXBlendFactor
{
  GX_BL_ZERO,
  GX_BL_ONE,
  GX_BL_SRCCLR,
  GX_BL_INVSRCCLR,
  GX_BL_SRCALPHA,
  GX_BL_INVSRCALPHA,
  GX_BL_DSTALPHA,
  GX_BL_INVDSTALPHA,
  GX_BL_DSTCLR = GX_BL_SRCCLR,
  GX_BL_INVDSTCLR = GX_BL_INVSRCCLR
} GXBlendFactor;
typedef enum _GXLogicOp
{
  GX_LO_CLEAR,
  GX_LO_AND,
  GX_LO_REVAND,
  GX_LO_COPY,
  GX_LO_INVAND,
  GX_LO_NOOP,
  GX_LO_XOR,
  GX_LO_OR,
  GX_LO_NOR,
  GX_LO_EQUIV,
  GX_LO_INV,
  GX_LO_REVOR,
  GX_LO_INVCOPY,
  GX_LO_INVOR,
  GX_LO_NAND,
  GX_LO_SET
} GXLogicOp;
typedef enum _GXCompCnt
{
  GX_POS_XY = 0,
  GX_POS_XYZ = 1,
  GX_NRM_XYZ = 0,
  GX_NRM_NBT = 1,
  GX_NRM_NBT3 = 2,
  GX_CLR_RGB = 0,
  GX_CLR_RGBA = 1,
  GX_TEX_S = 0,
  GX_TEX_ST = 1
} GXCompCnt;
typedef enum _GXCompType
{
  GX_U8 = 0,
  GX_S8 = 1,
  GX_U16 = 2,
  GX_S16 = 3,
  GX_F32 = 4,
  GX_RGB565 = 0,
  GX_RGB8 = 1,
  GX_RGBX8 = 2,
  GX_RGBA4 = 3,
  GX_RGBA6 = 4,
  GX_RGBA8 = 5
} GXCompType;
typedef enum _GXPTTexMtx
{
  GX_PTTEXMTX0 = 64,
  GX_PTTEXMTX1 = 67,
  GX_PTTEXMTX2 = 70,
  GX_PTTEXMTX3 = 73,
  GX_PTTEXMTX4 = 76,
  GX_PTTEXMTX5 = 79,
  GX_PTTEXMTX6 = 82,
  GX_PTTEXMTX7 = 85,
  GX_PTTEXMTX8 = 88,
  GX_PTTEXMTX9 = 91,
  GX_PTTEXMTX10 = 94,
  GX_PTTEXMTX11 = 97,
  GX_PTTEXMTX12 = 100,
  GX_PTTEXMTX13 = 103,
  GX_PTTEXMTX14 = 106,
  GX_PTTEXMTX15 = 109,
  GX_PTTEXMTX16 = 112,
  GX_PTTEXMTX17 = 115,
  GX_PTTEXMTX18 = 118,
  GX_PTTEXMTX19 = 121,
  GX_PTIDENTITY = 125
} GXPTTexMtx;
typedef enum _GXTevRegID
{
  GX_TEVPREV,
  GX_TEVREG0,
  GX_TEVREG1,
  GX_TEVREG2,
  GX_MAX_TEVREG
} GXTevRegID;
typedef enum _GXDiffuseFn
{
  GX_DF_NONE,
  GX_DF_SIGN,
  GX_DF_CLAMP
} GXDiffuseFn;
typedef enum _GXColorSrc
{
  GX_SRC_REG,
  GX_SRC_VTX
} GXColorSrc;
typedef enum _GXAttnFn
{
  GX_AF_SPEC,
  GX_AF_SPOT,
  GX_AF_NONE
} GXAttnFn;
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
typedef enum _GXTexOffset
{
  GX_TO_ZERO,
  GX_TO_SIXTEENTH,
  GX_TO_EIGHTH,
  GX_TO_FOURTH,
  GX_TO_HALF,
  GX_TO_ONE,
  GX_MAX_TEXOFFSET
} GXTexOffset;
typedef enum _GXSpotFn
{
  GX_SP_OFF,
  GX_SP_FLAT,
  GX_SP_COS,
  GX_SP_COS2,
  GX_SP_SHARP,
  GX_SP_RING1,
  GX_SP_RING2
} GXSpotFn;
typedef enum _GXDistAttnFn
{
  GX_DA_OFF,
  GX_DA_GENTLE,
  GX_DA_MEDIUM,
  GX_DA_STEEP
} GXDistAttnFn;
typedef enum _GXCullMode
{
  GX_CULL_NONE,
  GX_CULL_FRONT,
  GX_CULL_BACK,
  GX_CULL_ALL
} GXCullMode;
typedef enum _GXTevSwapSel
{
  GX_TEV_SWAP0 = 0,
  GX_TEV_SWAP1,
  GX_TEV_SWAP2,
  GX_TEV_SWAP3,
  GX_MAX_TEVSWAP
} GXTevSwapSel;
typedef enum _GXTevColorChan
{
  GX_CH_RED = 0,
  GX_CH_GREEN,
  GX_CH_BLUE,
  GX_CH_ALPHA
} GXTevColorChan;
typedef enum _GXFogType
{
  GX_FOG_NONE = 0,
  GX_FOG_LIN = 2,
  GX_FOG_EXP = 4,
  GX_FOG_EXP2 = 5,
  GX_FOG_REVEXP = 6,
  GX_FOG_REVEXP2 = 7
} GXFogType;
typedef enum _GXTevColorArg
{
  GX_CC_CPREV,
  GX_CC_APREV,
  GX_CC_C0,
  GX_CC_A0,
  GX_CC_C1,
  GX_CC_A1,
  GX_CC_C2,
  GX_CC_A2,
  GX_CC_TEXC,
  GX_CC_TEXA,
  GX_CC_RASC,
  GX_CC_RASA,
  GX_CC_ONE,
  GX_CC_HALF,
  GX_CC_KONST,
  GX_CC_ZERO,
  GX_CC_TEXRRR,
  GX_CC_TEXGGG,
  GX_CC_TEXBBB,
  GX_CC_QUARTER = GX_CC_KONST
} GXTevColorArg;
typedef enum _GXTevAlphaArg
{
  GX_CA_APREV,
  GX_CA_A0,
  GX_CA_A1,
  GX_CA_A2,
  GX_CA_TEXA,
  GX_CA_RASA,
  GX_CA_KONST,
  GX_CA_ZERO,
  GX_CA_ONE = GX_CA_KONST
} GXTevAlphaArg;
typedef enum _GXTevOp
{
  GX_TEV_ADD = 0,
  GX_TEV_SUB = 1,
  GX_TEV_COMP_R8_GT = 8,
  GX_TEV_COMP_R8_EQ = 9,
  GX_TEV_COMP_GR16_GT = 10,
  GX_TEV_COMP_GR16_EQ = 11,
  GX_TEV_COMP_BGR24_GT = 12,
  GX_TEV_COMP_BGR24_EQ = 13,
  GX_TEV_COMP_RGB8_GT = 14,
  GX_TEV_COMP_RGB8_EQ = 15,
  GX_TEV_COMP_A8_GT = GX_TEV_COMP_RGB8_GT,
  GX_TEV_COMP_A8_EQ = GX_TEV_COMP_RGB8_EQ
} GXTevOp;
typedef enum _GXTevBias
{
  GX_TB_ZERO,
  GX_TB_ADDHALF,
  GX_TB_SUBHALF,
  GX_MAX_TEVBIAS
} GXTevBias;
typedef enum _GXTevClampMode
{
  GX_TC_LINEAR,
  GX_TC_GE,
  GX_TC_EQ,
  GX_TC_LE,
  GX_MAX_TEVCLAMPMODE
} GXTevClampMode;
typedef enum _GXTevScale
{
  GX_CS_SCALE_1,
  GX_CS_SCALE_2,
  GX_CS_SCALE_4,
  GX_CS_DIVIDE_2,
  GX_MAX_TEVSCALE
} GXTevScale;
typedef enum _GXTevKColorSel
{
  GX_TEV_KCSEL_1 = 0x00,
  GX_TEV_KCSEL_7_8 = 0x01,
  GX_TEV_KCSEL_3_4 = 0x02,
  GX_TEV_KCSEL_5_8 = 0x03,
  GX_TEV_KCSEL_1_2 = 0x04,
  GX_TEV_KCSEL_3_8 = 0x05,
  GX_TEV_KCSEL_1_4 = 0x06,
  GX_TEV_KCSEL_1_8 = 0x07,
  GX_TEV_KCSEL_K0 = 0x0C,
  GX_TEV_KCSEL_K1 = 0x0D,
  GX_TEV_KCSEL_K2 = 0x0E,
  GX_TEV_KCSEL_K3 = 0x0F,
  GX_TEV_KCSEL_K0_R = 0x10,
  GX_TEV_KCSEL_K1_R = 0x11,
  GX_TEV_KCSEL_K2_R = 0x12,
  GX_TEV_KCSEL_K3_R = 0x13,
  GX_TEV_KCSEL_K0_G = 0x14,
  GX_TEV_KCSEL_K1_G = 0x15,
  GX_TEV_KCSEL_K2_G = 0x16,
  GX_TEV_KCSEL_K3_G = 0x17,
  GX_TEV_KCSEL_K0_B = 0x18,
  GX_TEV_KCSEL_K1_B = 0x19,
  GX_TEV_KCSEL_K2_B = 0x1A,
  GX_TEV_KCSEL_K3_B = 0x1B,
  GX_TEV_KCSEL_K0_A = 0x1C,
  GX_TEV_KCSEL_K1_A = 0x1D,
  GX_TEV_KCSEL_K2_A = 0x1E,
  GX_TEV_KCSEL_K3_A = 0x1F
} GXTevKColorSel;
typedef enum _GXTevKAlphaSel
{
  GX_TEV_KASEL_1 = 0x00,
  GX_TEV_KASEL_7_8 = 0x01,
  GX_TEV_KASEL_3_4 = 0x02,
  GX_TEV_KASEL_5_8 = 0x03,
  GX_TEV_KASEL_1_2 = 0x04,
  GX_TEV_KASEL_3_8 = 0x05,
  GX_TEV_KASEL_1_4 = 0x06,
  GX_TEV_KASEL_1_8 = 0x07,
  GX_TEV_KASEL_K0_R = 0x10,
  GX_TEV_KASEL_K1_R = 0x11,
  GX_TEV_KASEL_K2_R = 0x12,
  GX_TEV_KASEL_K3_R = 0x13,
  GX_TEV_KASEL_K0_G = 0x14,
  GX_TEV_KASEL_K1_G = 0x15,
  GX_TEV_KASEL_K2_G = 0x16,
  GX_TEV_KASEL_K3_G = 0x17,
  GX_TEV_KASEL_K0_B = 0x18,
  GX_TEV_KASEL_K1_B = 0x19,
  GX_TEV_KASEL_K2_B = 0x1A,
  GX_TEV_KASEL_K3_B = 0x1B,
  GX_TEV_KASEL_K0_A = 0x1C,
  GX_TEV_KASEL_K1_A = 0x1D,
  GX_TEV_KASEL_K2_A = 0x1E,
  GX_TEV_KASEL_K3_A = 0x1F
} GXTevKAlphaSel;
typedef enum _GXTevKColorID
{
  GX_KCOLOR0 = 0,
  GX_KCOLOR1,
  GX_KCOLOR2,
  GX_KCOLOR3,
  GX_MAX_KCOLOR
} GXTevKColorID;
typedef enum _GXZTexOp
{
  GX_ZT_DISABLE,
  GX_ZT_ADD,
  GX_ZT_REPLACE,
  GX_MAX_ZTEXOP
} GXZTexOp;
typedef enum _GXIndTexFormat
{
  GX_ITF_8,
  GX_ITF_5,
  GX_ITF_4,
  GX_ITF_3,
  GX_MAX_ITFORMAT
} GXIndTexFormat;
typedef enum _GXIndTexBiasSel
{
  GX_ITB_NONE,
  GX_ITB_S,
  GX_ITB_T,
  GX_ITB_ST,
  GX_ITB_U,
  GX_ITB_SU,
  GX_ITB_TU,
  GX_ITB_STU,
  GX_MAX_ITBIAS
} GXIndTexBiasSel;
typedef enum _GXIndTexAlphaSel
{
  GX_ITBA_OFF,
  GX_ITBA_S,
  GX_ITBA_T,
  GX_ITBA_U,
  GX_MAX_ITBALPHA
} GXIndTexAlphaSel;
typedef enum _GXIndTexMtxID
{
  GX_ITM_OFF,
  GX_ITM_0,
  GX_ITM_1,
  GX_ITM_2,
  GX_ITM_S0 = 5,
  GX_ITM_S1,
  GX_ITM_S2,
  GX_ITM_T0 = 9,
  GX_ITM_T1,
  GX_ITM_T2
} GXIndTexMtxID;
typedef enum _GXIndTexWrap
{
  GX_ITW_OFF,
  GX_ITW_256,
  GX_ITW_128,
  GX_ITW_64,
  GX_ITW_32,
  GX_ITW_16,
  GX_ITW_0,
  GX_MAX_ITWRAP
} GXIndTexWrap;
typedef enum _GXIndTexStageID
{
  GX_INDTEXSTAGE0,
  GX_INDTEXSTAGE1,
  GX_INDTEXSTAGE2,
  GX_INDTEXSTAGE3,
  GX_MAX_INDTEXSTAGE
} GXIndTexStageID;
typedef enum _GXIndTexScale
{
  GX_ITS_1,
  GX_ITS_2,
  GX_ITS_4,
  GX_ITS_8,
  GX_ITS_16,
  GX_ITS_32,
  GX_ITS_64,
  GX_ITS_128,
  GX_ITS_256,
  GX_MAX_ITSCALE
} GXIndTexScale;
typedef enum _GXPerf0
{
  GX_PERF0_VERTICES,
  GX_PERF0_CLIP_VTX,
  GX_PERF0_CLIP_CLKS,
  GX_PERF0_XF_WAIT_IN,
  GX_PERF0_XF_WAIT_OUT,
  GX_PERF0_XF_XFRM_CLKS,
  GX_PERF0_XF_LIT_CLKS,
  GX_PERF0_XF_BOT_CLKS,
  GX_PERF0_XF_REGLD_CLKS,
  GX_PERF0_XF_REGRD_CLKS,
  GX_PERF0_CLIP_RATIO,
  GX_PERF0_TRIANGLES,
  GX_PERF0_TRIANGLES_CULLED,
  GX_PERF0_TRIANGLES_PASSED,
  GX_PERF0_TRIANGLES_SCISSORED,
  GX_PERF0_TRIANGLES_0TEX,
  GX_PERF0_TRIANGLES_1TEX,
  GX_PERF0_TRIANGLES_2TEX,
  GX_PERF0_TRIANGLES_3TEX,
  GX_PERF0_TRIANGLES_4TEX,
  GX_PERF0_TRIANGLES_5TEX,
  GX_PERF0_TRIANGLES_6TEX,
  GX_PERF0_TRIANGLES_7TEX,
  GX_PERF0_TRIANGLES_8TEX,
  GX_PERF0_TRIANGLES_0CLR,
  GX_PERF0_TRIANGLES_1CLR,
  GX_PERF0_TRIANGLES_2CLR,
  GX_PERF0_QUAD_0CVG,
  GX_PERF0_QUAD_NON0CVG,
  GX_PERF0_QUAD_1CVG,
  GX_PERF0_QUAD_2CVG,
  GX_PERF0_QUAD_3CVG,
  GX_PERF0_QUAD_4CVG,
  GX_PERF0_AVG_QUAD_CNT,
  GX_PERF0_CLOCKS,
  GX_PERF0_NONE
} GXPerf0;
typedef enum _GXPerf1
{
  GX_PERF1_TEXELS,
  GX_PERF1_TX_IDLE,
  GX_PERF1_TX_REGS,
  GX_PERF1_TX_MEMSTALL,
  GX_PERF1_TC_CHECK1_2,
  GX_PERF1_TC_CHECK3_4,
  GX_PERF1_TC_CHECK5_6,
  GX_PERF1_TC_CHECK7_8,
  GX_PERF1_TC_MISS,
  GX_PERF1_VC_ELEMQ_FULL,
  GX_PERF1_VC_MISSQ_FULL,
  GX_PERF1_VC_MEMREQ_FULL,
  GX_PERF1_VC_STATUS7,
  GX_PERF1_VC_MISSREP_FULL,
  GX_PERF1_VC_STREAMBUF_LOW,
  GX_PERF1_VC_ALL_STALLS,
  GX_PERF1_VERTICES,
  GX_PERF1_FIFO_REQ,
  GX_PERF1_CALL_REQ,
  GX_PERF1_VC_MISS_REQ,
  GX_PERF1_CP_ALL_REQ,
  GX_PERF1_CLOCKS,
  GX_PERF1_NONE
} GXPerf1;
typedef enum _GXVCachePerf
{
  GX_VC_POS = 0,
  GX_VC_NRM = 1,
  GX_VC_CLR0 = 2,
  GX_VC_CLR1 = 3,
  GX_VC_TEX0 = 4,
  GX_VC_TEX1 = 5,
  GX_VC_TEX2 = 6,
  GX_VC_TEX3 = 7,
  GX_VC_TEX4 = 8,
  GX_VC_TEX5 = 9,
  GX_VC_TEX6 = 10,
  GX_VC_TEX7 = 11,
  GX_VC_ALL = 15
} GXVCachePerf;
typedef enum _GXClipMode
{
  GX_CLIP_ENABLE = 0,
  GX_CLIP_DISABLE = 1
} GXClipMode;
typedef enum _GXFBClamp
{
  GX_CLAMP_NONE = 0,
  GX_CLAMP_TOP = 1,
  GX_CLAMP_BOTTOM = 2
} GXFBClamp;
typedef enum _GXCopyMode
{
  GX_COPY_PROGRESSIVE = 0,
  GX_COPY_INTLC_EVEN = 2,
  GX_COPY_INTLC_ODD = 3
} GXCopyMode;
typedef enum _GXAlphaReadMode
{
  GX_READ_00,
  GX_READ_FF,
  GX_READ_NONE
} GXAlphaReadMode;
typedef enum _GXTexCacheSize
{
  GX_TEXCACHE_32K,
  GX_TEXCACHE_128K,
  GX_TEXCACHE_512K,
  GX_TEXCACHE_NONE
} GXTexCacheSize;
typedef enum _GXTlut
{
  GX_TLUT0,
  GX_TLUT1,
  GX_TLUT2,
  GX_TLUT3,
  GX_TLUT4,
  GX_TLUT5,
  GX_TLUT6,
  GX_TLUT7,
  GX_TLUT8,
  GX_TLUT9,
  GX_TLUT10,
  GX_TLUT11,
  GX_TLUT12,
  GX_TLUT13,
  GX_TLUT14,
  GX_TLUT15,
  GX_BIGTLUT0,
  GX_BIGTLUT1,
  GX_BIGTLUT2,
  GX_BIGTLUT3
} GXTlut;
typedef enum _GXTlutFmt
{
  GX_TL_IA8,
  GX_TL_RGB565,
  GX_TL_RGB5A3,
  GX_MAX_TLUTFMT
} GXTlutFmt;
typedef enum _GXTlutSize
{
  GX_TLUT_16 = 1,
  GX_TLUT_32 = 2,
  GX_TLUT_64 = 4,
  GX_TLUT_128 = 8,
  GX_TLUT_256 = 16,
  GX_TLUT_512 = 32,
  GX_TLUT_1K = 64,
  GX_TLUT_2K = 128,
  GX_TLUT_4K = 256,
  GX_TLUT_8K = 512,
  GX_TLUT_16K = 1024
} GXTlutSize;
typedef enum _GXMiscToken
{
  GX_MT_XF_FLUSH = 1,
  GX_MT_DL_SAVE_CONTEXT = 2,
  GX_MT_NULL = 0
} GXMiscToken;
void GXSetTevIndirect(GXTevStageID tev_stage, GXIndTexStageID ind_stage, GXIndTexFormat format, GXIndTexBiasSel bias_sel, GXIndTexMtxID matrix_sel, GXIndTexWrap wrap_s, GXIndTexWrap wrap_t, GXBool add_prev, GXBool utc_lod, GXIndTexAlphaSel alpha_sel);
void GXSetIndTexMtx(GXIndTexMtxID mtx_id, f32 offset[2][3], s8 scale_exp);
void GXSetIndTexCoordScale(GXIndTexStageID ind_state, GXIndTexScale scale_s, GXIndTexScale scale_t);
void GXSetIndTexOrder(GXIndTexStageID ind_stage, GXTexCoordID tex_coord, GXTexMapID tex_map);
void GXSetNumIndStages(u8 nIndStages);
void GXSetTevDirect(GXTevStageID tev_stage);
void GXSetTevIndWarp(GXTevStageID tev_stage, GXIndTexStageID ind_stage, u8 signed_offset, u8 replace_mode, GXIndTexMtxID matrix_sel);
void GXSetTevIndTile(GXTevStageID tev_stage, GXIndTexStageID ind_stage, u16 tilesize_s, u16 tilesize_t, u16 tilespacing_s, u16 tilespacing_t, GXIndTexFormat format, GXIndTexMtxID matrix_sel, GXIndTexBiasSel bias_sel, GXIndTexAlphaSel alpha_sel);
void GXSetTevIndBumpST(GXTevStageID tev_stage, GXIndTexStageID ind_stage, GXIndTexMtxID matrix_sel);
void GXSetTevIndBumpXYZ(GXTevStageID tev_stage, GXIndTexStageID ind_stage, GXIndTexMtxID matrix_sel);
void GXSetTevIndRepeat(GXTevStageID tev_stage);
extern u8 GXTexMode0Ids[8];
extern u8 GXTexMode1Ids[8];
extern u8 GXTexImage0Ids[8];
extern u8 GXTexImage1Ids[8];
extern u8 GXTexImage2Ids[8];
extern u8 GXTexImage3Ids[8];
extern u8 GXTexTlutIds[8];
void GXPokeAlphaMode(GXCompare func, u8 threshold);
void GXPokeAlphaRead(GXAlphaReadMode mode);
void GXPokeAlphaUpdate(GXBool update_enable);
void GXPokeBlendMode(GXBlendMode type, GXBlendFactor src_factor, GXBlendFactor dst_factor, GXLogicOp op);
void GXPokeColorUpdate(GXBool update_enable);
void GXPokeDstAlpha(GXBool enable, u8 alpha);
void GXPokeDither(GXBool dither);
void GXPokeZMode(GXBool compare_enable, GXCompare func, GXBool update_enable);
void GXPeekARGB(u16 x, u16 y, u32 *color);
void GXPokeARGB(u16 x, u16 y, u32 color);
void GXPeekZ(u16 x, u16 y, u32 *z);
void GXPokeZ(u16 x, u16 y, u32 z);
u32 GXCompressZ16(u32 z24, GXZFmt16 zfmt);
u32 GXDecompressZ16(u32 z16, GXZFmt16 zfmt);
void GXSetScissor(u32 left, u32 top, u32 wd, u32 ht);
void GXSetCullMode(GXCullMode mode);
void GXSetCoPlanar(GXBool enable);
void GXBeginDisplayList(void *list, u32 size);
u32 GXEndDisplayList(void);
void GXCallDisplayList(void *list, u32 nbytes);
void GXDrawCylinder(u8 numEdges);
void GXDrawTorus(f32 rc, u8 numc, u8 numt);
void GXDrawSphere(u8 numMajor, u8 numMinor);
void GXDrawCube(void);
void GXDrawDodeca(void);
void GXDrawOctahedron(void);
void GXDrawIcosahedron(void);
void GXDrawSphere1(u8 depth);
u32 GXGenNormalTable(u8 depth, f32 *table);
typedef struct 
{
  u8 pad[128];
} GXFifoObj;
typedef void (*GXBreakPtCallback)(void);
void GXInitFifoBase(GXFifoObj *fifo, void *base, u32 size);
void GXInitFifoPtrs(GXFifoObj *fifo, void *readPtr, void *writePtr);
void GXInitFifoLimits(GXFifoObj *fifo, u32 hiWatermark, u32 loWatermark);
void GXSetCPUFifo(GXFifoObj *fifo);
void GXSetGPFifo(GXFifoObj *fifo);
void GXSaveCPUFifo(GXFifoObj *fifo);
void GXSaveGPFifo(GXFifoObj *fifo);
void GXGetGPStatus(GXBool *overhi, GXBool *underlow, GXBool *readIdle, GXBool *cmdIdle, GXBool *brkpt);
void GXGetFifoStatus(GXFifoObj *fifo, GXBool *overhi, GXBool *underflow, u32 *fifoCount, GXBool *cpuWrite, GXBool *gpRead, GXBool *fifowrap);
void GXGetFifoPtrs(GXFifoObj *fifo, void **readPtr, void **writePtr);
void *GXGetFifoBase(GXFifoObj *fifo);
u32 GXGetFifoSize(GXFifoObj *fifo);
void GXGetFifoLimits(GXFifoObj *fifo, u32 *hi, u32 *lo);
GXBreakPtCallback GXSetBreakPtCallback(GXBreakPtCallback cb);
void GXEnableBreakPt(void *break_pt);
void GXDisableBreakPt(void);
OSThread *GXSetCurrentGXThread(void);
OSThread *GXGetCurrentGXThread(void);
GXFifoObj *GXGetCPUFifo(void);
GXFifoObj *GXGetGPFifo(void);
u32 GXGetOverflowCount(void);
u32 GXResetOverflowCount(void);
volatile void *GXRedirectWriteGatherPipe(void *ptr);
void GXRestoreWriteGatherPipe(void);
typedef enum 
{
  VI_TVMODE_NTSC_INT = (0 << 2) + 0,
  VI_TVMODE_NTSC_DS = (0 << 2) + 1,
  VI_TVMODE_NTSC_PROG = (0 << 2) + 2,
  VI_TVMODE_PAL_INT = (1 << 2) + 0,
  VI_TVMODE_PAL_DS = (1 << 2) + 1,
  VI_TVMODE_EURGB60_INT = (5 << 2) + 0,
  VI_TVMODE_EURGB60_DS = (5 << 2) + 1,
  VI_TVMODE_MPAL_INT = (2 << 2) + 0,
  VI_TVMODE_MPAL_DS = (2 << 2) + 1,
  VI_TVMODE_DEBUG_INT = (3 << 2) + 0,
  VI_TVMODE_DEBUG_PAL_INT = (4 << 2) + 0,
  VI_TVMODE_DEBUG_PAL_DS = (4 << 2) + 1,
  VI_TVMODE_3 = 3
} VITVMode;
typedef enum 
{
  VI_XFBMODE_SF = 0,
  VI_XFBMODE_DF
} VIXFBMode;
typedef void (*VIRetraceCallback)(u32 retraceCount);
typedef struct _GXRenderModeObj
{
  VITVMode viTVmode;
  u16 fbWidth;
  u16 efbHeight;
  u16 xfbHeight;
  u16 viXOrigin;
  u16 viYOrigin;
  u16 viWidth;
  u16 viHeight;
  VIXFBMode xFBmode;
  u8 field_rendering;
  u8 aa;
  u8 sample_pattern[12][2];
  u8 vfilter[7];
} GXRenderModeObj;
typedef struct _GXColor
{
  u8 r;
  u8 g;
  u8 b;
  u8 a;
} GXColor;
typedef struct _GXColorS10
{
  s16 r;
  s16 g;
  s16 b;
  s16 a;
} GXColorS10;
typedef struct _GXTexObj
{
  u32 dummy[8];
} GXTexObj;
typedef struct _GXLightObj
{
  u32 dummy[16];
} GXLightObj;
typedef struct _GXTexRegion
{
  u32 dummy[4];
} GXTexRegion;
typedef struct _GXTlutObj
{
  u32 dummy[3];
} GXTlutObj;
typedef struct _GXTlutRegion
{
  u32 dummy[4];
} GXTlutRegion;
typedef struct _GXFogAdjTable
{
  u16 r[10];
} GXFogAdjTable;
typedef struct _GXVtxDescList
{
  GXAttr attr;
  GXAttrType type;
} GXVtxDescList;
typedef struct _GXVtxAttrFmtList
{
  GXAttr attr;
  GXCompCnt cnt;
  GXCompType type;
  u8 frac;
} GXVtxAttrFmtList;
extern GXRenderModeObj GXNtsc240Ds;
extern GXRenderModeObj GXNtsc240DsAa;
extern GXRenderModeObj GXNtsc240Int;
extern GXRenderModeObj GXNtsc240IntAa;
extern GXRenderModeObj GXNtsc480IntDf;
extern GXRenderModeObj GXNtsc480Int;
extern GXRenderModeObj GXNtsc480IntAa;
extern GXRenderModeObj GXNtsc480Prog;
extern GXRenderModeObj GXNtsc480ProgAa;
extern GXRenderModeObj GXMpal240Ds;
extern GXRenderModeObj GXMpal240DsAa;
extern GXRenderModeObj GXMpal240Int;
extern GXRenderModeObj GXMpal240IntAa;
extern GXRenderModeObj GXMpal480IntDf;
extern GXRenderModeObj GXMpal480Int;
extern GXRenderModeObj GXMpal480IntAa;
extern GXRenderModeObj GXPal264Ds;
extern GXRenderModeObj GXPal264DsAa;
extern GXRenderModeObj GXPal264Int;
extern GXRenderModeObj GXPal264IntAa;
extern GXRenderModeObj GXPal528IntDf;
extern GXRenderModeObj GXPal528Int;
extern GXRenderModeObj GXPal528IntAa;
void GXAdjustForOverscan(GXRenderModeObj *rmin, GXRenderModeObj *rmout, u16 hor, u16 ver);
void GXSetDispCopySrc(u16 left, u16 top, u16 wd, u16 ht);
void GXSetTexCopySrc(u16 left, u16 top, u16 wd, u16 ht);
void GXSetDispCopyDst(u16 wd, u16 ht);
void GXSetTexCopyDst(u16 wd, u16 ht, GXTexFmt fmt, GXBool mipmap);
void GXSetDispCopyFrame2Field(GXCopyMode mode);
void GXSetCopyClamp(GXFBClamp clamp);
u32 GXSetDispCopyYScale(f32 vscale);
void GXSetCopyClear(GXColor clear_clr, u32 clear_z);
void GXSetCopyFilter(GXBool aa, const u8 sample_pattern[12][2], GXBool vf, const u8 vfilter[7]);
void GXSetDispCopyGamma(GXGamma gamma);
void GXCopyDisp(void *dest, GXBool clear);
void GXCopyTex(void *dest, GXBool clear);
void GXClearBoundingBox(void);
void GXReadBoundingBox(u16 *left, u16 *top, u16 *right, u16 *bottom);
void GXSetVtxDesc(GXAttr attr, GXAttrType type);
void GXSetVtxDescv(const GXVtxDescList *attrPtr);
void GXClearVtxDesc(void);
void GXSetVtxAttrFmt(GXVtxFmt vtxfmt, GXAttr attr, GXCompCnt cnt, GXCompType type, u8 frac);
void GXSetVtxAttrFmtv(GXVtxFmt vtxfmt, const GXVtxAttrFmtList *list);
void GXSetArray(GXAttr attr, const void *base_ptr, u8 stride);
void GXInvalidateVtxCache(void);
void GXSetTexCoordGen2(GXTexCoordID dst_coord, GXTexGenType func, GXTexGenSrc src_param, u32 mtx, GXBool normalize, u32 pt_texmtx);
void GXSetNumTexGens(u8 nTexGens);
inline static void GXSetTexCoordGen(GXTexCoordID dst_coord, GXTexGenType func, GXTexGenSrc src_param, u32 mtx)
{
  GXSetTexCoordGen2(dst_coord, func, src_param, mtx, (GXBool) 0, GX_PTIDENTITY);
}

void GXBegin(GXPrimitive type, GXVtxFmt vtxfmt, u16 nverts);
inline static void GXEnd(void)
{
}

void GXSetLineWidth(u8 width, GXTexOffset texOffsets);
void GXSetPointSize(u8 pointSize, GXTexOffset texOffsets);
void GXEnableTexOffsets(GXTexCoordID coord, u8 line_enable, u8 point_enable);
void GXGetVtxDesc(GXAttr attr, GXAttrType *type);
void GXGetVtxDescv(GXVtxDescList *vcd);
void GXGetVtxAttrFmt(GXVtxFmt fmt, GXAttr attr, GXCompCnt *cnt, GXCompType *type, u8 *frac);
void GXGetVtxAttrFmtv(GXVtxFmt fmt, GXVtxAttrFmtList *vat);
void GXGetLineWidth(u8 *width, GXTexOffset *texOffsets);
void GXGetPointSize(u8 *pointSize, GXTexOffset *texOffsets);
void GXGetCullMode(GXCullMode *mode);
void GXGetLightAttnA(GXLightObj *lt_obj, f32 *a0, f32 *a1, f32 *a2);
void GXGetLightAttnK(GXLightObj *lt_obj, f32 *k0, f32 *k1, f32 *k2);
void GXGetLightPos(GXLightObj *lt_obj, f32 *x, f32 *y, f32 *z);
void GXGetLightDir(GXLightObj *lt_obj, f32 *nx, f32 *ny, f32 *nz);
void GXGetLightColor(GXLightObj *lt_obj, GXColor *color);
GXBool GXGetTexObjMipMap(const GXTexObj *to);
GXTexFmt GXGetTexObjFmt(const GXTexObj *to);
u16 GXGetTexObjWidth(const GXTexObj *to);
u16 GXGetTexObjHeight(const GXTexObj *to);
GXTexWrapMode GXGetTexObjWrapS(const GXTexObj *to);
GXTexWrapMode GXGetTexObjWrapT(const GXTexObj *to);
void *GXGetTexObjData(const GXTexObj *to);
void GXGetTexObjAll(const GXTexObj *obj, void **image_ptr, u16 *width, u16 *height, GXTexFmt *format, GXTexWrapMode *wrap_s, GXTexWrapMode *wrap_t, u8 *mipmap);
void GXGetTexObjLODAll(const GXTexObj *tex_obj, GXTexFilter *min_filt, GXTexFilter *mag_filt, f32 *min_lod, f32 *max_lod, f32 *lod_bias, u8 *bias_clamp, u8 *do_edge_lod, GXAnisotropy *max_aniso);
GXTexFilter GXGetTexObjMinFilt(const GXTexObj *tex_obj);
GXTexFilter GXGetTexObjMagFilt(const GXTexObj *tex_obj);
f32 GXGetTexObjMinLOD(const GXTexObj *tex_obj);
f32 GXGetTexObjMaxLOD(const GXTexObj *tex_obj);
f32 GXGetTexObjLODBias(const GXTexObj *tex_obj);
GXBool GXGetTexObjBiasClamp(const GXTexObj *tex_obj);
GXBool GXGetTexObjEdgeLOD(const GXTexObj *tex_obj);
GXAnisotropy GXGetTexObjMaxAniso(const GXTexObj *tex_obj);
u32 GXGetTexObjTlut(const GXTexObj *tex_obj);
void GXGetTlutObjAll(const GXTlutObj *tlut_obj, void **data, GXTlutFmt *format, u16 *numEntries);
void *GXGetTlutObjData(const GXTlutObj *tlut_obj);
GXTlutFmt GXGetTlutObjFmt(const GXTlutObj *tlut_obj);
u16 GXGetTlutObjNumEntries(const GXTlutObj *tlut_obj);
void GXGetTexRegionAll(const GXTexRegion *region, u8 *is_cached, u8 *is_32b_mipmap, u32 *tmem_even, u32 *size_even, u32 *tmem_odd, u32 *size_odd);
void GXGetTlutRegionAll(const GXTlutRegion *region, u32 *tmem_addr, GXTlutSize *tlut_size);
void GXGetProjectionv(f32 *ptr);
void GXGetViewportv(f32 *vp);
void GXGetScissor(u32 *left, u32 *top, u32 *wd, u32 *ht);
void GXInitLightAttn(GXLightObj *lt_obj, f32 a0, f32 a1, f32 a2, f32 k0, f32 k1, f32 k2);
void GXInitLightAttnA(GXLightObj *lt_obj, f32 a0, f32 a1, f32 a2);
void GXInitLightAttnK(GXLightObj *lt_obj, f32 k0, f32 k1, f32 k2);
void GXInitLightSpot(GXLightObj *lt_obj, f32 cutoff, GXSpotFn spot_func);
void GXInitLightDistAttn(GXLightObj *lt_obj, f32 ref_dist, f32 ref_br, GXDistAttnFn dist_func);
void GXInitLightPos(GXLightObj *lt_obj, f32 x, f32 y, f32 z);
void GXInitLightDir(GXLightObj *lt_obj, f32 nx, f32 ny, f32 nz);
void GXInitSpecularDir(GXLightObj *lt_obj, f32 nx, f32 ny, f32 nz);
void GXInitSpecularDirHA(GXLightObj *lt_obj, f32 nx, f32 ny, f32 nz, f32 hx, f32 hy, f32 hz);
void GXInitLightColor(GXLightObj *lt_obj, GXColor color);
void GXLoadLightObjImm(GXLightObj *lt_obj, GXLightID light);
void GXLoadLightObjIndx(u32 lt_obj_indx, GXLightID light);
void GXSetChanAmbColor(GXChannelID chan, GXColor amb_color);
void GXSetChanMatColor(GXChannelID chan, GXColor mat_color);
void GXSetNumChans(u8 nChans);
void GXSetChanCtrl(GXChannelID chan, GXBool enable, GXColorSrc amb_src, GXColorSrc mat_src, u32 light_mask, GXDiffuseFn diff_fn, GXAttnFn attn_fn);
typedef void (*GXDrawSyncCallback)(u16 token);
typedef void (*GXDrawDoneCallback)(void);
BOOL IsWriteGatherBufferEmpty(void);
GXFifoObj *GXInit(void *base, u32 size);
void GXSetMisc(GXMiscToken token, u32 val);
void GXFlush(void);
void GXResetWriteGatherPipe(void);
void GXAbortFrame(void);
void GXSetDrawSync(u16 token);
u16 GXReadDrawSync(void);
void GXSetDrawDone(void);
void GXWaitDrawDone(void);
void GXDrawDone(void);
void GXPixModeSync(void);
void GXTexModeSync(void);
GXDrawSyncCallback GXSetDrawSyncCallback(GXDrawSyncCallback cb);
GXDrawDoneCallback GXSetDrawDoneCallback(GXDrawDoneCallback cb);
void GXSetGPMetric(GXPerf0 perf0, GXPerf1 perf1);
void GXReadGPMetric(u32 *cnt0, u32 *cnt1);
void GXClearGPMetric(void);
u32 GXReadGP0Metric(void);
u32 GXReadGP1Metric(void);
void GXReadMemMetric(u32 *cp_req, u32 *tc_req, u32 *cpu_rd_req, u32 *cpu_wr_req, u32 *dsp_req, u32 *io_req, u32 *vi_req, u32 *pe_req, u32 *rf_req, u32 *fi_req);
void GXClearMemMetric(void);
void GXReadPixMetric(u32 *top_pixels_in, u32 *top_pixels_out, u32 *bot_pixels_in, u32 *bot_pixels_out, u32 *clr_pixels_in, u32 *copy_clks);
void GXClearPixMetric(void);
void GXSetVCacheMetric(GXVCachePerf attr);
void GXReadVCacheMetric(u32 *check, u32 *miss, u32 *stall);
void GXClearVCacheMetric(void);
void GXInitXfRasMetric(void);
void GXReadXfRasMetric(u32 *xf_wait_in, u32 *xf_wait_out, u32 *ras_busy, u32 *clocks);
u32 GXReadClksPerVtx(void);
void GXSetFog(GXFogType type, f32 startz, f32 endz, f32 nearz, f32 farz, GXColor color);
void GXInitFogAdjTable(GXFogAdjTable *table, u16 width, f32 projmtx[4][4]);
void GXSetFogRangeAdj(GXBool enable, u16 center, GXFogAdjTable *table);
void GXSetBlendMode(GXBlendMode type, GXBlendFactor src_factor, GXBlendFactor dst_factor, GXLogicOp op);
void GXSetColorUpdate(GXBool update_enable);
void GXSetAlphaUpdate(GXBool update_enable);
void GXSetZMode(GXBool compare_enable, GXCompare func, GXBool update_enable);
void GXSetZCompLoc(GXBool before_tex);
void GXSetPixelFmt(GXPixelFmt pix_fmt, GXZFmt16 z_fmt);
void GXSetDither(GXBool dither);
void GXSetDstAlpha(GXBool enable, u8 alpha);
void GXSetFieldMask(GXBool odd_mask, GXBool even_mask);
void GXSetFieldMode(GXBool field_mode, GXBool half_aspect_ratio);
void GXSetTevOp(GXTevStageID id, GXTevMode mode);
void GXSetTevColorIn(GXTevStageID stage, GXTevColorArg a, GXTevColorArg b, GXTevColorArg c, GXTevColorArg d);
void GXSetTevAlphaIn(GXTevStageID stage, GXTevAlphaArg a, GXTevAlphaArg b, GXTevAlphaArg c, GXTevAlphaArg d);
void GXSetTevColorOp(GXTevStageID stage, GXTevOp op, GXTevBias bias, GXTevScale scale, GXBool clamp, GXTevRegID out_reg);
void GXSetTevAlphaOp(GXTevStageID stage, GXTevOp op, GXTevBias bias, GXTevScale scale, GXBool clamp, GXTevRegID out_reg);
void GXSetTevColor(GXTevRegID id, GXColor color);
void GXSetTevColorS10(GXTevRegID id, GXColorS10 color);
void GXSetTevKColor(GXTevKColorID id, GXColor color);
void GXSetTevKColorSel(GXTevStageID stage, GXTevKColorSel sel);
void GXSetTevKAlphaSel(GXTevStageID stage, GXTevKAlphaSel sel);
void GXSetTevSwapMode(GXTevStageID stage, GXTevSwapSel ras_sel, GXTevSwapSel tex_sel);
void GXSetTevSwapModeTable(GXTevSwapSel table, GXTevColorChan red, GXTevColorChan green, GXTevColorChan blue, GXTevColorChan alpha);
void GXSetTevClampMode(int, int);
void GXSetAlphaCompare(GXCompare comp0, u8 ref0, GXAlphaOp op, GXCompare comp1, u8 ref1);
void GXSetZTexture(GXZTexOp op, GXTexFmt fmt, u32 bias);
void GXSetTevOrder(GXTevStageID stage, GXTexCoordID coord, GXTexMapID map, GXChannelID color);
void GXSetNumTevStages(u8 nStages);
typedef GXTexRegion *(*GXTexRegionCallback)(GXTexObj *t_obj, GXTexMapID id);
typedef GXTlutRegion *(*GXTlutRegionCallback)(u32 idx);
u32 GXGetTexBufferSize(u16 width, u16 height, u32 format, u8 mipmap, u8 max_lod);
void GXInitTexObj(GXTexObj *obj, void *image_ptr, u16 width, u16 height, GXTexFmt format, GXTexWrapMode wrap_s, GXTexWrapMode wrap_t, u8 mipmap);
void GXInitTexObjCI(GXTexObj *obj, void *image_ptr, u16 width, u16 height, GXCITexFmt format, GXTexWrapMode wrap_s, GXTexWrapMode wrap_t, u8 mipmap, u32 tlut_name);
void GXInitTexObjLOD(GXTexObj *obj, GXTexFilter min_filt, GXTexFilter mag_filt, f32 min_lod, f32 max_lod, f32 lod_bias, GXBool bias_clamp, GXBool do_edge_lod, GXAnisotropy max_aniso);
void GXInitTexObjData(GXTexObj *obj, void *image_ptr);
void GXInitTexObjWrapMode(GXTexObj *obj, GXTexWrapMode s, GXTexWrapMode t);
void GXInitTexObjTlut(GXTexObj *obj, u32 tlut_name);
void GXInitTexObjUserData(GXTexObj *obj, void *user_data);
void *GXGetTexObjUserData(const GXTexObj *obj);
void GXLoadTexObjPreLoaded(GXTexObj *obj, GXTexRegion *region, GXTexMapID id);
void GXLoadTexObj(GXTexObj *obj, GXTexMapID id);
void GXInitTlutObj(GXTlutObj *tlut_obj, void *lut, GXTlutFmt fmt, u16 n_entries);
void GXLoadTlut(GXTlutObj *tlut_obj, u32 tlut_name);
void GXInitTexCacheRegion(GXTexRegion *region, u8 is_32b_mipmap, u32 tmem_even, GXTexCacheSize size_even, u32 tmem_odd, GXTexCacheSize size_odd);
void GXInitTexPreLoadRegion(GXTexRegion *region, u32 tmem_even, u32 size_even, u32 tmem_odd, u32 size_odd);
void GXInitTlutRegion(GXTlutRegion *region, u32 tmem_addr, GXTlutSize tlut_size);
void GXInvalidateTexRegion(GXTexRegion *region);
void GXInvalidateTexAll(void);
GXTexRegionCallback GXSetTexRegionCallback(GXTexRegionCallback f);
GXTlutRegionCallback GXSetTlutRegionCallback(GXTlutRegionCallback f);
void GXPreLoadEntireTexture(GXTexObj *tex_obj, GXTexRegion *region);
void GXSetTexCoordScaleManually(GXTexCoordID coord, u8 enable, u16 ss, u16 ts);
void GXSetTexCoordCylWrap(GXTexCoordID coord, u8 s_enable, u8 t_enable);
void GXSetTexCoordBias(GXTexCoordID coord, u8 s_enable, u8 t_enable);
void GXProject(f32 x, f32 y, f32 z, f32 mtx[3][4], f32 *pm, f32 *vp, f32 *sx, f32 *sy, f32 *sz);
void GXSetProjection(f32 mtx[4][4], GXProjectionType type);
void GXSetProjectionv(f32 *ptr);
void GXLoadPosMtxImm(f32 mtx[3][4], u32 id);
void GXLoadPosMtxIndx(u16 mtx_indx, u32 id);
void GXLoadNrmMtxImm(f32 mtx[3][4], u32 id);
void GXLoadNrmMtxImm3x3(f32 mtx[3][3], u32 id);
void GXLoadNrmMtxIndx3x3(u16 mtx_indx, u32 id);
void GXSetCurrentMtx(u32 id);
void GXLoadTexMtxImm(f32 mtx[][4], u32 id, GXTexMtxType type);
void GXLoadTexMtxIndx(u16 mtx_indx, u32 id, GXTexMtxType type);
void GXSetViewportJitter(f32 left, f32 top, f32 wd, f32 ht, f32 nearz, f32 farz, u32 field);
void GXSetViewport(f32 left, f32 top, f32 wd, f32 ht, f32 nearz, f32 farz);
void GXSetScissorBoxOffset(s32 x_off, s32 y_off);
void GXSetClipMode(GXClipMode mode);
typedef enum 
{
  GX_WARN_NONE,
  GX_WARN_SEVERE,
  GX_WARN_MEDIUM,
  GX_WARN_ALL
} GXWarningLevel;
typedef void (*GXVerifyCallback)(GXWarningLevel level, u32 id, char *msg);
void GXSetVerifyLevel(GXWarningLevel level);
GXVerifyCallback GXSetVerifyCallback(GXVerifyCallback cb);
typedef union 
{
  u8 u8;
  u16 u16;
  u32 u32;
  u64 u64;
  s8 s8;
  s16 s16;
  s32 s32;
  s64 s64;
  f32 f32;
  f64 f64;
} PPCWGPipe;
inline static void GXCmd1u8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

inline static void GXCmd1u16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXCmd1u32(u32 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u32 = x;
}

inline static void GXParam1u8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

inline static void GXParam1u16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXParam1u32(u32 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u32 = x;
}

inline static void GXParam1s8(s8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = x;
}

inline static void GXParam1s16(s16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = x;
}

inline static void GXParam1s32(s32 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s32 = x;
}

inline static void GXParam1f32(f32 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
}

inline static void GXParam3f32(f32 x, f32 y, f32 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = z;
}

inline static void GXParam4f32(f32 x, f32 y, f32 z, f32 w)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = z;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = w;
}

inline static void GXPosition3f32(f32 x, f32 y, f32 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = z;
}

inline static void GXPosition3u8(u8 x, u8 y, u8 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = z;
}

inline static void GXPosition3s8(s8 x, s8 y, s8 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = z;
}

inline static void GXPosition3u16(u16 x, u16 y, u16 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = z;
}

inline static void GXPosition3s16(s16 x, s16 y, s16 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = z;
}

inline static void GXPosition2f32(f32 x, f32 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = y;
}

inline static void GXPosition2u8(u8 x, u8 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = y;
}

inline static void GXPosition2s8(s8 x, s8 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = y;
}

inline static void GXPosition2u16(u16 x, u16 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = y;
}

inline static void GXPosition2s16(s16 x, s16 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = y;
}

inline static void GXPosition1x16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXPosition1x8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

inline static void GXNormal3f32(f32 x, f32 y, f32 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = z;
}

inline static void GXNormal3s16(s16 x, s16 y, s16 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = z;
}

inline static void GXNormal3s8(s8 x, s8 y, s8 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = z;
}

inline static void GXNormal1x16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXNormal1x8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

inline static void GXColor4u8(u8 x, u8 y, u8 z, u8 w)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = z;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = w;
}

inline static void GXColor1u32(u32 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u32 = x;
}

inline static void GXColor3u8(u8 x, u8 y, u8 z)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = y;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = z;
}

inline static void GXColor1u16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXColor1x16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXColor1x8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

inline static void GXTexCoord2f32(f32 x, f32 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = y;
}

inline static void GXTexCoord2s16(s16 x, s16 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = y;
}

inline static void GXTexCoord2u16(u16 x, u16 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = y;
}

inline static void GXTexCoord2s8(s8 x, s8 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = y;
}

inline static void GXTexCoord2u8(u8 x, u8 y)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = y;
}

inline static void GXTexCoord1f32(f32 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).f32 = x;
}

inline static void GXTexCoord1s16(s16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s16 = x;
}

inline static void GXTexCoord1u16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXTexCoord1s8(s8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).s8 = x;
}

inline static void GXTexCoord1u8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

inline static void GXTexCoord1x16(u16 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u16 = x;
}

inline static void GXTexCoord1x8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

inline static void GXMatrixIndex1u8(u8 x)
{
  (*((volatile PPCWGPipe *) 0xCC008000)).u8 = x;
}

void (*GXSetDrawSyncCallback(void (*cb)(unsigned short)))(unsigned short);
void GXSetDrawSync(unsigned short token);
typedef u32 HSD_Pad;
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
typedef enum GroundOrAir
{
  GA_Ground,
  GA_Air
} GroundOrAir;
extern char db_build_timestamp[];
extern int g_debugLevel;
extern u16 db_gameLaunchButtonState;
extern char **db_bonus_names;
extern char **db_motionstate_names;
extern char **db_submotion_names;
extern bool db_804D6B20;
extern int db_MiscVisualEffectsStatus;
void db_GetGameLaunchButtonState(void);
void db_Setup(void);
HSD_Pad db_ButtonsDown(int player);
HSD_Pad db_ButtonsPressed(int player);
HSD_Pad db_ButtonsRepeat(int player);
void db_PrintEntityCounts(void);
void db_PrintThreadInfo(void);
void db_RunEveryFrame(void);
void fn_SetupItemAndPokemonMenu(void);
void fn_80225A54(int arg0);
u32 db_ShowEnemyStompRange(void);
u32 db_ShowItemPickupRange(void);
u32 db_ShowCoinPickupRange(void);
void fn_EnableShowCoinPickupRange(void);
void fn_DisableShowCoinPickupRange(void);
void fn_EnableShowEnemyStompRange(void);
void fn_DisableShowEnemyStompRange(void);
void fn_EnableShowItemPickupRange(void);
void fn_DisableShowItemPickupRange(void);
s32 db_GetCurrentlySelectedPokemon(void);
void db_DisableItemSpawns(void);
void db_EnableItemSpawns(void);
s32 db_AreItemSpawnsEnabled(void);
void db_80225D64(Item_GObj *item, Fighter_GObj *owner);
void fn_ToggleItemCollisionBubbles(void);
void db_80225DD8(Item_GObj *item, Fighter_GObj *owner);
void fn_80225E6C(Fighter_GObj *owner, Fighter *);
void db_HandleItemPokemonMenuInput(int player);
void fn_ShowOrCreateItemAndPokemonMenu(int player);
void fn_UpdateItemAndPokemonMenu(int player);
void db_CheckAndSpawnItem(int player);
void fn_CheckItemAndPokemonMenu(int player);
void fn_SetupCpuHandicapInfo(void);
void fn_UpdateCpuHandicapInfo(void);
void fn_CheckCpuHandicapInfo(int arg0);
void fn_SetupAnimationInfo(void);
void fn_ToggleMiscFighterVisuals(void);
u8 fn_8022697C(Fighter_GObj *owner);
void fn_UpdateAnimationInfo(void);
void fn_CheckAnimationInfo(int player);
void fn_SetupMiscStageVisuals(void);
void fn_CheckMiscStageEffects(int arg0);
void fn_802270C4(int arg0);
void fn_8022713C(int arg0);
void fn_SetupCameraInfo(void);
void fn_80227188(void);
void fn_CheckCameraInfo(int player, int buttons_down, int buttons_pressed, f32 cstick_x, f32 cstick_y);
void fn_802277E8(HSD_GObj *, int);
void fn_80227904(HSD_GObj *camera, int port);
void fn_802279E8(HSD_GObj *camera, Vec3 *camera_pos, Vec3 *camera_interest, float cstick_x, float cstick_y);
void fn_80227B64(HSD_GObj *camera, float x, float y);
void fn_80227BA8(HSD_GObj *camera, Vec3 *, float, float);
void fn_80227CAC(HSD_GObj *camera, float cstick_y);
void fn_80227D38(HSD_GObj *camera, Vec3 *, float);
void fn_80227EB0(HSD_GObj *camera, Vec3 *, Vec3 *, float, float);
void fn_80227FE0(HSD_GObj *camera, float x, float y);
void fn_80228124(HSD_GObj *camera, Vec3 *, float, float);
void fn_SetupSoundInfo(void);
void fn_UpdateSoundInfo(void);
void fn_CheckSoundInfo(int player);
void fn_CheckMiscVisualEffects(int player);
void fn_Setup5xSpeed(void);
void fn_Check5xSpeed(int player);
void fn_Toggle5xSpeed(void);
void db_InitScreenshot(void);
void db_CheckScreenshot(void);
void db_TakeScreenshotIfPending(void);
int fn_802289F8(char *arg0, int arg1, int arg2);
void db_ClearFPUExceptions(void);
void fn_HSDPanicHandler(OSContext *ctx);
void fn_OSErrorHandler(u16 error, OSContext *ctx, ...);
void db_SetupCrashHandler(void);
void fn_SetupBonusInfo(void);
void fn_80228D18(void);
void fn_80228D38(void);
void fn_80228E54(int arg0, int arg1, int arg2);
void fn_8022900C(int arg0);
void fn_CheckBonusInfo(int arg0);
void fn_SetupObjAllocLimiter(void);
void fn_UpdateObjAllocLimiter(int arg0);
typedef enum CameraType
{
  CAMERA_STANDARD = 0,
  CAMERA_PAUSE = 1,
  CAMERA_TRAINING_MENU = 2,
  CAMERA_CLEAR = 3,
  CAMERA_FIXED = 4,
  CAMERA_FREE = 5,
  CAMERA_BOSS_INTRO = 6,
  CAMERA_DEBUG_FOLLOW = 7,
  CAMERA_DEBUG_FREE = 8
} CameraType;
typedef struct Camera Camera;
typedef struct CameraBounds CameraBounds;
typedef struct CameraQuake CameraQuake;
typedef struct CmSubject CmSubject;
typedef struct CameraTransformState CameraTransformState;
typedef struct CameraUnkGlobals CameraUnkGlobals;
typedef struct CameraDebugMode CameraDebugMode;
typedef struct CameraModeCallbacks CameraModeCallbacks;
typedef struct CameraInputs CameraInputs;
struct CmSubject
{
  CmSubject *next;
  CmSubject *prev;
  bool x8;
  u8 xC_b0 : 1;
  u8 xC_b1 : 1;
  u8 xC_b2 : 1;
  s16 xE;
  Vec3 x10;
  Vec3 x1C;
  float x28;
  Vec2 x2C;
  Vec3 x34;
  Vec2 x40;
  Vec3 x48;
  Vec3 x54;
  Vec3 x60;
};
struct CameraTransformState
{
  Vec3 interest;
  Vec3 target_interest;
  Vec3 position;
  Vec3 target_position;
  float fov;
  float target_fov;
};
struct CameraBounds
{
  float x_min;
  float y_min;
  float x_max;
  float y_max;
  int total_subjects;
  float z_pos;
};
struct CameraQuake
{
  Vec3 x0;
  int type;
};
struct CameraDebugMode
{
  CameraType last_mode;
  int ply_slot;
  Vec3 follow_int_offset;
  Vec3 follow_eye_offset;
  Vec3 follow_eye_pos;
  Vec3 follow_int_pos;
  float follow_fov;
  Vec3 free_int_pos;
  Vec3 free_eye_pos;
  float free_fov;
  u8 _4C[8];
};
struct Camera
{
  HSD_GObj *gobj;
  CameraType mode;
  u8 background_r;
  u8 background_g;
  u8 background_b;
  s8 xB;
  f32 nearz;
  f32 farz;
  CameraTransformState transform;
  CameraTransformState transform_copy;
  Vec2 translation;
  s32 _8C[5];
  HSD_GObj *xA0;
  f32 xA4;
  f32 xA8;
  f32 xAC;
  struct CameraQuake _B0[2][8];
  struct CameraQuake _1B0[2][8];
  float x2B0;
  float x2B4;
  s16 x2B8;
  s16 x2BA;
  f32 x2BC;
  f32 x2C0;
  s8 x2C4;
  s8 x2C5;
  char pad_2C6[0x2C8 - 0x2C6];
  float pitch_offset;
  float yaw_offset;
  f32 x2D0;
  f32 x2D4;
  f32 x2D8;
  f32 x2DC;
  f32 x2E0;
  f32 x2E4;
  f32 x2E8;
  f32 x2EC;
  f32 x2F0;
  f32 x2F4;
  f32 min_distance;
  f32 max_distance;
  s32 x300;
  s8 x304;
  s8 x305;
  s8 x306;
  s8 x307;
  Vec3 x308;
  Vec3 x314;
  Vec3 pause_eye_offset;
  f32 x32C;
  f32 pause_eye_distance;
  Vec3 pause_up;
  u8 x340;
  u8 x341_b0 : 1;
  u8 x341_b1_b2 : 2;
  u8 x341_b3_b4 : 2;
  u8 x341_b5_b6 : 2;
  u8 x341_b7 : 1;
  char x342_pad[2];
  union 
  {
    s32 s32;
    Vec3 vec;
    s32 (*cb)(Vec3 *);
  } x344;
  Vec3 x350;
  union 
  {
    Vec3 vec;
    s32 (*cb)(Vec3 *);
    struct 
    {
      u8 b0 : 1;
      u8 b1 : 1;
      u8 b2 : 1;
      u8 pad;
      s16 x2;
    } bits;
  } x35C;
  Vec3 x368;
  f32 x374;
  union 
  {
    f32 f32;
    s32 s32;
  } x378;
  s32 x37C;
  u8 x380[0x18];
  u8 x398_b0 : 1;
  u8 x398_b1 : 1;
  u8 x398_b2 : 1;
  u8 x398_b3 : 1;
  u8 x398_b4 : 1;
  u8 x398_b5 : 1;
  u8 x398_b6_b7 : 2;
  u8 x399_b0_b1 : 2;
  u8 x399_b2 : 1;
  u8 x399_b3 : 1;
  u8 x399_b4 : 1;
  u8 x399_b5 : 1;
  u8 x399_b6 : 1;
  u8 x399_b7 : 1;
  u8 x39A_b0 : 1;
  u8 x39A_b1 : 1;
  u8 x39A_b2 : 1;
  u8 x39A_b3 : 1;
  u8 x39A_b4 : 1;
  u8 x39A_b5 : 1;
  u8 x39A_b6 : 1;
  u8 x39A_b7 : 1;
  char pad_39B;
};
struct CameraUnkGlobals
{
  float x0;
  float x4;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  float x1C;
  float x20;
  float x24;
  float x28;
  float x2C;
  float x30;
  float x34;
  float x38;
  float x3C;
  float x40;
  float x44;
  float x48;
  float x4C;
  float x50;
  float x54;
  float x58;
  float x5C;
  float x60;
  float x64;
  float x68;
  float x6C;
  float x70;
  float x74;
  float x78;
  float x7C;
  float x80;
  float x84;
  float x88;
  float x8C;
  float x90;
  float x94;
  float x98;
  float x9C;
  float xA0;
  float xA4;
  float xA8;
  float xAC;
  float xB0;
  float xB4;
  float xB8;
  float xBC;
  float xC0;
  float xC4;
  float xC8;
  float xCC;
  float xD0;
  float xD4;
  float xD8;
  float xDC;
  float xE0;
  float xE4;
  float xE8;
  float xEC;
};
struct CameraModeCallbacks
{
  void (*callback[9])(void *);
};
struct CameraInputs
{
  f32 stick_x;
  f32 stick_y;
  f32 substick_x;
  f32 substick_y;
  union 
  {
    u32 _u32[2];
    u64 _u64;
  } x10;
  union 
  {
    u32 _u32[2];
    u64 _u64;
  } x18;
};
typedef struct WaitStruct
{
  union 
  {
    struct 
    {
      int *x;
      int *y;
    } p;
    struct 
    {
      int x;
      int y;
    } i;
  } u;
} WaitStruct;
bool ftCo_8008A698(Fighter *fp);
void ftCo_8008A6D8(Fighter_GObj *gobj, s32 anim_id);
void ftCo_8008A7A8(Fighter_GObj *gobj, WaitStruct *arg1);
extern char ftWaitAnim_803C54A8[];
extern char ftWaitAnim_803C54C4[];
typedef struct ftCaptain_DatAttrs ftCaptain_DatAttrs;
typedef union ftCaptain_MotionVars ftCaptain_MotionVars;
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
typedef enum ftCaptain_MotionState
{
  ftCa_MS_SwordSwing4 = ftCo_MS_Count,
  ftCa_MS_BatSwing4,
  ftCa_MS_ParasolSwing4,
  ftCa_MS_HarisenSwing4,
  ftCa_MS_StarRodSwing4,
  ftCa_MS_LipstickSwing4,
  ftCa_MS_SpecialN,
  ftCa_MS_SpecialAirN,
  ftCa_MS_SpecialSStart,
  ftCa_MS_SpecialS,
  ftCa_MS_SpecialAirSStart,
  ftCa_MS_SpecialAirS,
  ftCa_MS_SpecialHi,
  ftCa_MS_SpecialAirHi,
  ftCa_MS_SpecialHiCatch,
  ftCa_MS_SpecialHiThrow,
  ftCa_MS_SpecialLw,
  ftCa_MS_SpecialLwEnd,
  ftCa_MS_SpecialAirLw,
  ftCa_MS_SpecialAirLwEnd,
  ftCa_MS_SpecialAirLwEndAir,
  ftCa_MS_SpecialLwEndAir,
  ftCa_MS_SpecialHiThrow1,
  ftCa_MS_Count,
  ftCa_MS_SelfCount = ftCa_MS_Count - ftCo_MS_Count
} ftCaptain_MotionState;
typedef enum ftCa_Submotion
{
  ftCa_SM_SwordSwing4 = ftCo_SM_Count,
  ftCa_SM_BatSwing4,
  ftCa_SM_ParasolSwing4,
  ftCa_SM_HarisenSwing4,
  ftCa_SM_StarRodSwing4,
  ftCa_SM_LipstickSwing4,
  ftCa_SM_SpecialN,
  ftCa_SM_SpecialAirN,
  ftCa_SM_SpecialSStart,
  ftCa_SM_SpecialS,
  ftCa_SM_SpecialAirSStart,
  ftCa_SM_SpecialAirS,
  ftCa_SM_SpecialHi,
  ftCa_SM_SpecialAirHi,
  ftCa_SM_SpecialHiCatch,
  ftCa_SM_SpecialHiThrow0,
  ftCa_SM_SpecialLw,
  ftCa_SM_SpecialLwEnd,
  ftCa_SM_SpecialAirLw,
  ftCa_SM_SpecialAirLwEnd,
  ftCa_SM_SpecialLwEndAir,
  ftCa_SM_SpecialAirLwEndAir,
  ftCa_SM_SpecialHiThrow1,
  ftCa_SM_Count,
  ftCa_SM_SelfCount = ftCa_SM_Count - ftCo_SM_Count
} ftCa_Submotion;
struct ftCaptain_FighterVars
{
  u32 during_specials_start;
  u32 during_specials;
  u8 _[0xF8 - 8];
};
struct ftCaptain_DatAttrs
{
  float specialn_stick_range_y_neg;
  float specialn_stick_range_y_pos;
  float specialn_angle_diff;
  float specialn_vel_x;
  float specialn_vel_mul;
  float specials_gr_vel_x;
  float specials_grav;
  float specials_terminal_vel;
  float specials_unk0;
  float specials_unk1;
  float specials_unk2;
  float specials_unk3;
  float specials_unk4;
  float specials_unk5;
  float specials_miss_landing_lag;
  float specials_hit_landing_lag;
  float specialhi_air_friction_mul;
  float specialhi_horz_vel;
  float specialhi_freefall_air_spd_mul;
  float specialhi_landing_lag;
  float specialhi_unk0;
  float specialhi_unk1;
  float specialhi_input_var;
  float specialhi_unk2;
  float specialhi_catch_grav;
  s32 specialhi_air_var;
  float x68;
  u32 speciallw_unk1;
  float speciallw_flame_particle_angle;
  float speciallw_on_hit_spd_modifier;
  s32 speciallw_unk2;
  float speciallw_ground_lag_mul;
  float speciallw_landing_lag_mul;
  float speciallw_ground_traction;
  float speciallw_air_landing_traction;
};
union ftCaptain_MotionVars
{
  struct ftCaptainSpecialSVars
  {
    float grav;
  } specials;
  struct ftCaptainSpecialHiVars
  {
    u16 x0;
    u8 x2_b0 : 1;
    u8 x2_b1 : 1;
    u8 x2_b2 : 1;
    u8 x2_b3 : 1;
    u8 x2_b4 : 1;
    u8 x2_b5 : 1;
    u8 x2_b6 : 1;
    u8 x2_b7 : 1;
    u8 x3;
    Vec2 vel;
  } specialhi;
  struct ftCaptainSpecialLwVars
  {
    u16 x0;
    u16 x2;
    float friction;
  } speciallw;
};
typedef struct Fighter ftKb_Fighter;
typedef struct ftKb_DatAttrs ftKb_DatAttrs;
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
typedef enum ftKirby_MotionState
{
  ftKb_MS_JumpAerialF1 = ftCo_MS_Count,
  ftKb_MS_JumpAerialF2,
  ftKb_MS_JumpAerialF3,
  ftKb_MS_JumpAerialF4,
  ftKb_MS_JumpAerialF5,
  ftKb_MS_JumpAerialF1Met,
  ftKb_MS_JumpAerialF2Met,
  ftKb_MS_JumpAerialF3Met,
  ftKb_MS_JumpAerialF4Met,
  ftKb_MS_JumpAerialF5Met,
  ftKb_MS_AttackDash,
  ftKb_MS_AttackDashAir,
  ftKb_MS_SpecialN,
  ftKb_MS_SpecialNLoop,
  ftKb_MS_SpecialNEnd,
  ftKb_MS_SpecialNCapture0,
  ftKb_MS_SpecialNCapture1,
  ftKb_MS_Eat,
  ftKb_MS_EatWait,
  ftKb_MS_EatWalkSlow,
  ftKb_MS_EatWalkMiddle,
  ftKb_MS_EatWalkFast,
  ftKb_MS_EatTurn,
  ftKb_MS_EatJump1,
  ftKb_MS_EatJump2,
  ftKb_MS_EatLanding,
  ftKb_MS_SpecialNDrink0,
  ftKb_MS_SpecialNDrink1,
  ftKb_MS_SpecialNSpit0,
  ftKb_MS_SpecialNSpit1,
  ftKb_MS_SpecialAirN,
  ftKb_MS_SpecialAirNLoop,
  ftKb_MS_SpecialAirNEnd,
  ftKb_MS_SpecialAirNCapture0,
  ftKb_MS_SpecialAirNCapture1,
  ftKb_MS_EatAir,
  ftKb_MS_EatFall,
  ftKb_MS_SpecialAirNDrink0,
  ftKb_MS_SpecialAirNDrink1,
  ftKb_MS_SpecialAirNSpit0,
  ftKb_MS_SpecialAirNSpit1,
  ftKb_MS_EatTurnAir,
  ftKb_MS_SpecialS,
  ftKb_MS_SpecialAirS,
  ftKb_MS_SpecialHi1,
  ftKb_MS_SpecialHi2,
  ftKb_MS_SpecialHi3,
  ftKb_MS_SpecialHi4,
  ftKb_MS_SpecialAirHi1,
  ftKb_MS_SpecialAirHi2,
  ftKb_MS_SpecialAirHi3,
  ftKb_MS_SpecialAirHi4,
  ftKb_MS_SpecialLw1,
  ftKb_MS_SpecialLw,
  ftKb_MS_SpecialLwEnd,
  ftKb_MS_SpecialAirLwStart,
  ftKb_MS_SpecialAirLw,
  ftKb_MS_SpecialAirLwEnd,
  ftKb_MS_MrSpecialN,
  ftKb_MS_MrSpecialAirN,
  ftKb_MS_LkSpecialNStart,
  ftKb_MS_LkSpecialNLoop,
  ftKb_MS_LkSpecialNEnd,
  ftKb_MS_LkSpecialAirNStart,
  ftKb_MS_LkSpecialAirNLoop,
  ftKb_MS_LkSpecialAirNEnd,
  ftKb_MS_SsSpecialNStart,
  ftKb_MS_SsSpecialNHold,
  ftKb_MS_SsSpecialNCancel,
  ftKb_MS_SsSpecialN,
  ftKb_MS_SsSpecialAirNStart,
  ftKb_MS_SsSpecialAirN,
  ftKb_MS_YsSpecialN1,
  ftKb_MS_YsSpecialNCapture1_0,
  ftKb_MS_YsSpecialNCapture1_1,
  ftKb_MS_YsSpecialNCapture2_0,
  ftKb_MS_YsSpecialNCapture2_1,
  ftKb_MS_YsSpecialAirNCapture2,
  ftKb_MS_YsSpecialAirNCapture1_0,
  ftKb_MS_YsSpecialAirNCapture1_1,
  ftKb_MS_YsSpecialAirN2_0,
  ftKb_MS_YsSpecialAirN2_1,
  ftKb_MS_FxSpecialNStart,
  ftKb_MS_FxSpecialNLoop,
  ftKb_MS_FxSpecialNEnd,
  ftKb_MS_FxSpecialAirNStart,
  ftKb_MS_FxSpecialAirNLoop,
  ftKb_MS_FxSpecialAirNEnd,
  ftKb_MS_PkSpecialN,
  ftKb_MS_PkSpecialAirN,
  ftKb_MS_LgSpecialN,
  ftKb_MS_LgSpecialAirN,
  ftKb_MS_CaSpecialN,
  ftKb_MS_CaSpecialAirN,
  ftKb_MS_NsSpecialNStart,
  ftKb_MS_NsSpecialNHold0,
  ftKb_MS_NsSpecialNHold1,
  ftKb_MS_NsSpecialNEnd,
  ftKb_MS_NsSpecialAirNStart,
  ftKb_MS_NsSpecialAirNHold0,
  ftKb_MS_NsSpecialAirNHold1,
  ftKb_MS_NsSpecialAirNEnd,
  ftKb_MS_KpSpecialNStart,
  ftKb_MS_KpSpecialN,
  ftKb_MS_KpSpecialNEnd,
  ftKb_MS_KpSpecialAirNStart,
  ftKb_MS_KpSpecialAirN,
  ftKb_MS_KpSpecialAirNEnd,
  ftKb_MS_PeSpecialLw,
  ftKb_MS_PeSpecialLwHit,
  ftKb_MS_PeSpecialAirLw,
  ftKb_MS_PeSpecialAirLwHit,
  ftKb_MS_PpSpecialN,
  ftKb_MS_PpSpecialAirN,
  ftKb_MS_DkSpecialNStart,
  ftKb_MS_DkSpecialNLoop,
  ftKb_MS_DkSpecialNCancel,
  ftKb_MS_DkSpecialN,
  ftKb_MS_DkSpecialNFull,
  ftKb_MS_DkSpecialAirNStart,
  ftKb_MS_DkSpecialAirNLoop,
  ftKb_MS_DkSpecialAirNCancel,
  ftKb_MS_DkSpecialAirN,
  ftKb_MS_DkSpecialAirNFull,
  ftKb_MS_ZdSpecialN,
  ftKb_MS_ZdSpecialAirN,
  ftKb_MS_SkSpecialNStart,
  ftKb_MS_SkSpecialNLoop,
  ftKb_MS_SkSpecialNCancel,
  ftKb_MS_SkSpecialNEnd,
  ftKb_MS_SkSpecialAirNStart,
  ftKb_MS_SkSpecialAirNLoop,
  ftKb_MS_SkSpecialAirNCancel,
  ftKb_MS_SkSpecialAirNEnd,
  ftKb_MS_PrSpecialNStartR,
  ftKb_MS_PrSpecialNStartL,
  ftKb_MS_PrSpecialNLoop,
  ftKb_MS_PrSpecialNFull,
  ftKb_MS_PrSpecialN1,
  ftKb_MS_PrSpecialNTurn,
  ftKb_MS_PrSpecialNEndR,
  ftKb_MS_PrSpecialNEndL,
  ftKb_MS_PrSpecialAirNStartR,
  ftKb_MS_PrSpecialAirNStartL,
  ftKb_MS_PrSpecialAirNLoop,
  ftKb_MS_PrSpecialAirNFull,
  ftKb_MS_PrSpecialAirN,
  ftKb_MS_PrSpecialN0,
  ftKb_MS_PrSpecialAirNEndR0,
  ftKb_MS_PrSpecialAirNEndR1,
  ftKb_MS_PrSpecialNHit,
  ftKb_MS_MsSpecialNStart,
  ftKb_MS_MsSpecialNLoop,
  ftKb_MS_MsSpecialNEnd0,
  ftKb_MS_MsSpecialNEnd1,
  ftKb_MS_MsSpecialAirNStart,
  ftKb_MS_MsSpecialAirNLoop,
  ftKb_MS_MsSpecialAirNEnd0,
  ftKb_MS_MsSpecialAirNEnd1,
  ftKb_MS_MtSpecialNStart,
  ftKb_MS_MtSpecialNLoop,
  ftKb_MS_MtSpecialNLoopFull,
  ftKb_MS_MtSpecialNCancel,
  ftKb_MS_MtSpecialNEnd,
  ftKb_MS_MtSpecialAirNStart,
  ftKb_MS_MtSpecialAirNLoop,
  ftKb_MS_MtSpecialAirNLoopFull,
  ftKb_MS_MtSpecialAirNCancel,
  ftKb_MS_MtSpecialAirNEnd,
  ftKb_MS_GwSpecialN,
  ftKb_MS_GwSpecialAirN,
  ftKb_MS_DrSpecialN,
  ftKb_MS_DrSpecialAirN,
  ftKb_MS_ClSpecialNStart,
  ftKb_MS_ClSpecialNLoop,
  ftKb_MS_ClSpecialNEnd,
  ftKb_MS_ClSpecialAirNStart,
  ftKb_MS_ClSpecialAirNLoop,
  ftKb_MS_ClSpecialAirNEnd,
  ftKb_MS_FcSpecialNStart,
  ftKb_MS_FcSpecialNLoop,
  ftKb_MS_FcSpecialNEnd,
  ftKb_MS_FcSpecialAirNStart,
  ftKb_MS_FcSpecialAirNLoop,
  ftKb_MS_FcSpecialAirNEnd,
  ftKb_MS_PcSpecialN,
  ftKb_MS_PcSpecialAirN,
  ftKb_MS_GnSpecialN,
  ftKb_MS_GnSpecialAirN,
  ftKb_MS_FeSpecialNStart,
  ftKb_MS_FeSpecialNLoop,
  ftKb_MS_FeSpecialNEnd0,
  ftKb_MS_FeSpecialNEnd1,
  ftKb_MS_FeSpecialAirNStart,
  ftKb_MS_FeSpecialAirNLoop,
  ftKb_MS_FeSpecialAirNEnd0,
  ftKb_MS_FeSpecialAirNEnd1,
  ftKb_MS_GkSpecialNStart,
  ftKb_MS_GkSpecialN,
  ftKb_MS_GkSpecialNEnd,
  ftKb_MS_GkSpecialAirNStart,
  ftKb_MS_GkSpecialAirN,
  ftKb_MS_GkSpecialAirNEnd,
  ftKb_MS_Count,
  ftKb_MS_SelfCount = ftKb_MS_Count - ftCo_MS_Count
} ftKirby_MotionState;
typedef enum ftKb_Submotion
{
  ftKb_SM_JumpAerialF1 = ftCo_SM_Count,
  ftKb_SM_JumpAerialF2,
  ftKb_SM_JumpAerialF3,
  ftKb_SM_JumpAerialF4,
  ftKb_SM_JumpAerialF5,
  ftKb_SM_JumpAerialF1Met,
  ftKb_SM_JumpAerialF2Met,
  ftKb_SM_JumpAerialF3Met,
  ftKb_SM_JumpAerialF4Met,
  ftKb_SM_JumpAerialF5Met,
  ftKb_SM_SpecialN,
  ftKb_SM_SpecialNLoop,
  ftKb_SM_SpecialNEnd,
  ftKb_SM_SpecialNCapture,
  ftKb_SM_Eat,
  ftKb_SM_EatWait,
  ftKb_SM_EatWalkSlow,
  ftKb_SM_EatWalkMiddle,
  ftKb_SM_EatWalkFast,
  ftKb_SM_EatJump1,
  ftKb_SM_EatJump2,
  ftKb_SM_EatLanding,
  ftKb_SM_EatTurn,
  ftKb_SM_SpecialNDrink,
  ftKb_SM_SpecialNSpit,
  ftKb_SM_SpecialAirN,
  ftKb_SM_SpecialAirNLoop,
  ftKb_SM_SpecialS,
  ftKb_SM_SpecialAirS,
  ftKb_SM_SpecialHi1,
  ftKb_SM_SpecialHi2,
  ftKb_SM_SpecialHi3,
  ftKb_SM_SpecialHi4,
  ftKb_SM_SpecialAirHi1,
  ftKb_SM_SpecialAirHi2,
  ftKb_SM_SpecialAirHi3,
  ftKb_SM_SpecialAirHiEnd,
  ftKb_SM_SpecialLw1,
  ftKb_SM_SpecialLw,
  ftKb_SM_SpecialLwEnd,
  ftKb_SM_SpecialAirLwStart,
  ftKb_SM_SpecialAirLw,
  ftKb_SM_SpecialAirLwEnd,
  ftKb_SM_MrSpecialN,
  ftKb_SM_MrSpecialAirN,
  ftKb_SM_LkSpecialNStart,
  ftKb_SM_LkSpecialNLoop,
  ftKb_SM_LkSpecialNEnd,
  ftKb_SM_LkSpecialAirNStart,
  ftKb_SM_LkSpecialAirNLoop,
  ftKb_SM_LkSpecialAirNEnd,
  ftKb_SM_SsSpecialNStart,
  ftKb_SM_SsSpecialNHold,
  ftKb_SM_SsSpecialNCancel,
  ftKb_SM_SsSpecialN,
  ftKb_SM_SsSpecialAirNStart,
  ftKb_SM_SsSpecialAirN,
  ftKb_SM_YsSpecialN1,
  ftKb_SM_YsSpecialNCapture1,
  ftKb_SM_YsSpecialNCapture2,
  ftKb_SM_YsSpecialAirNCapture2,
  ftKb_SM_YsSpecialAirCapture1,
  ftKb_SM_YsSpecialAirN2,
  ftKb_SM_FxSpecialNStart,
  ftKb_SM_FxSpecialNLoop,
  ftKb_SM_FxSpecialNEnd,
  ftKb_SM_FxSpecialAirNStart,
  ftKb_SM_FxSpecialAirNLoop,
  ftKb_SM_FxSpecialAirNEnd,
  ftKb_SM_PkSpecialN,
  ftKb_SM_PkSpecialAirN,
  ftKb_SM_LgSpecialN,
  ftKb_SM_LgSpecialAirN,
  ftKb_SM_CaSpecialN,
  ftKb_SM_CaSpecialAirN,
  ftKb_SM_NsSpecialNStart,
  ftKb_SM_NsSpecialNHold0,
  ftKb_SM_NsSpecialNHold1,
  ftKb_SM_NsSpecialNEnd,
  ftKb_SM_NsSpecialAirNStart,
  ftKb_SM_NsSpecialAirNHold0,
  ftKb_SM_NsSpecialAirNHold1,
  ftKb_SM_NsSpecialAirNEnd,
  ftKb_SM_KpSpecialNStart,
  ftKb_SM_KpSpecialN,
  ftKb_SM_KpSpecialNEnd,
  ftKb_SM_KpSpecialAirNStart,
  ftKb_SM_KpSpecialAirN,
  ftKb_SM_KpSpecialAirNEnd,
  ftKb_SM_PeSpecialLw,
  ftKb_SM_PeSpecialLwHit,
  ftKb_SM_PeSpecialAirLw,
  ftKb_SM_PeSpecialAirLwHit,
  ftKb_SM_PpSpecialN,
  ftKb_SM_PpSpecialAirN,
  ftKb_SM_DkSpecialNStart,
  ftKb_SM_DkSpecialNLoop,
  ftKb_SM_DkSpecialNCancel,
  ftKb_SM_DkSpecialN,
  ftKb_SM_DkSpecialNFull,
  ftKb_SM_DkSpecialAirNStart,
  ftKb_SM_DkSpecialAirNLoop,
  ftKb_SM_DkSpecialAirNCancel,
  ftKb_SM_DkSpecialAirN,
  ftKb_SM_DkSpecialAirNFull,
  ftKb_SM_ZdSpecialN,
  ftKb_SM_ZdSpecialAirN,
  ftKb_SM_SkSpecialNStart,
  ftKb_SM_SkSpecialNLoop,
  ftKb_SM_SkSpecialNCancel,
  ftKb_SM_SkSpecialNEnd,
  ftKb_SM_SkSpecialAirNStart,
  ftKb_SM_SkSpecialAirNLoop,
  ftKb_SM_SkSpecialAirNCancel,
  ftKb_SM_SkSpecialAirNEnd,
  ftKb_SM_PrSpecialNStartR,
  ftKb_SM_PrSpecialNStartL,
  ftKb_SM_PrSpecialNLoop,
  ftKb_SM_PrSpecialNFull,
  ftKb_SM_PrSpecialN1,
  ftKb_SM_PrSpecialNTurn,
  ftKb_SM_PrSpecialNEndR,
  ftKb_SM_PrSpecialNEndL,
  ftKb_SM_PrSpecialAirNStartR,
  ftKb_SM_PrSpecialAirNStartL,
  ftKb_SM_PrSpecialAirNLoop,
  ftKb_SM_PrSpecialAirNFull,
  ftKb_SM_PrSpecialAirN,
  ftKb_SM_PrSpecialN0,
  ftKb_SM_PrSpecialAirNEndR0,
  ftKb_SM_PrSpecialAirNEndR1,
  ftKb_SM_PrSpecialNHit,
  ftKb_SM_MsSpecialNStart,
  ftKb_SM_MsSpecialNLoop,
  ftKb_SM_MsSpecialNEnd0,
  ftKb_SM_MsSpecialNEnd1,
  ftKb_SM_MsSpecialAirNStart,
  ftKb_SM_MsSpecialAirNLoop,
  ftKb_SM_MsSpecialAirNEnd0,
  ftKb_SM_MsSpecialAirNEnd1,
  ftKb_SM_MtSpecialNStart,
  ftKb_SM_MtSpecialNLoop,
  ftKb_SM_MtSpecialNLoopFull,
  ftKb_SM_MtSpecialNCancel,
  ftKb_SM_MtSpecialNEnd,
  ftKb_SM_MtSpecialAirNStart,
  ftKb_SM_MtSpecialAirNLoop,
  ftKb_SM_MtSpecialAirNLoopFull,
  ftKb_SM_MtSpecialAirNCancel,
  ftKb_SM_MtSpecialAirNEnd,
  ftKb_SM_GwSpecialN,
  ftKb_SM_GwSpecialAirN,
  ftKb_SM_DrSpecialN,
  ftKb_SM_DrSpecialAirN,
  ftKb_SM_ClSpecialNStart,
  ftKb_SM_ClSpecialNLoop,
  ftKb_SM_ClSpecialNEnd,
  ftKb_SM_ClSpecialAirNStart,
  ftKb_SM_ClSpecialAirNLoop,
  ftKb_SM_ClSpecialAirNEnd,
  ftKb_SM_FcSpecialNStart,
  ftKb_SM_FcSpecialNLoop,
  ftKb_SM_FcSpecialNEnd,
  ftKb_SM_FcSpecialAirNStart,
  ftKb_SM_FcSpecialAirNLoop,
  ftKb_SM_FcSpecialAirNEnd,
  ftKb_SM_PcSpecialN,
  ftKb_SM_PcSpecialAirN,
  ftKb_SM_GnSpecialN,
  ftKb_SM_GnSpecialAirN,
  ftKb_SM_FeSpecialNStart,
  ftKb_SM_FeSpecialNLoop,
  ftKb_SM_FeSpecialNEnd0,
  ftKb_SM_FeSpecialNEnd1,
  ftKb_SM_FeSpecialAirNStart,
  ftKb_SM_FeSpecialAirNLoop,
  ftKb_SM_FeSpecialAirNEnd0,
  ftKb_SM_FeSpecialAirNEnd1,
  ftKb_SM_GkSpecialNStart,
  ftKb_SM_GkSpecialN,
  ftKb_SM_GkSpecialNEnd,
  ftKb_SM_GkSpecialAirNStart,
  ftKb_SM_GkSpecialAirN,
  ftKb_SM_GkSpecialAirNEnd,
  ftKb_SM_Count,
  ftKb_SM_SelfCount = ftKb_SM_Count - ftCo_SM_Count
} ftKb_Submotion;
struct ftCollisionBox
{
  float top;
  float bottom;
  Vec2 left;
  Vec2 right;
};
struct ftHurtboxInit
{
  Fighter_Part bone_idx;
  HurtHeight height;
  u32 is_grabbable;
  Vec3 a_offset;
  Vec3 b_offset;
  float scale;
};
union ftCommon_MotionVars
{
  struct 
  {
    int x0;
    f32 x4;
    void *x8;
    void *xC;
    void *x10;
    float x14;
    float x18;
    float x1C;
    float x20;
    float x24;
    Vec3 x28;
    Vec3 x34;
    Vec3 x40;
    Vec3 x4C;
    Vec3 x58;
  } common;
  struct 
  {
    float x0;
    FtMotionId msid;
    float slow_anim_frame;
    float middle_anim_frame;
    float fast_anim_frame;
    float slow_anim_rate;
    float middle_anim_rate;
    float fast_anim_rate;
    float accel_mul;
  } walk;
  struct 
  {
    bool has_turned;
    float facing_after;
    float x8;
    u8 pad_xC[4];
    float frames_to_turn;
    u8 pad_x14[4];
    bool just_turned;
    HSD_Pad x1C;
  } turn;
  struct 
  {
    u8 pad_x0[12];
    float accel_mul;
    u8 pad_x10[4];
    int x14;
  } turnrun;
  struct 
  {
    float x0;
    int x4;
  } dash;
  struct 
  {
    float x0;
    float x4;
  } run;
  struct 
  {
    bool x0;
    float frames;
  } runbrake;
  struct 
  {
    int is_short_hop;
    ftCo_JumpInput jump_input;
  } kneebend;
  struct 
  {
    int x0;
    bool x4;
    float jump_mul;
  } jump;
  struct 
  {
    int x0;
    float init_h_vel;
  } jumpaerial;
  struct 
  {
    FtMotionId smid;
    float x4;
  } fall;
  struct 
  {
    FtMotionId smid;
    float x4;
  } fallaerial;
  struct 
  {
    int x0;
    float x4;
  } squat;
  struct 
  {
    bool allow_interrupt;
  } landing;
  struct 
  {
    bool x0;
  } attack1;
  struct 
  {
    bool x0;
    bool x4;
  } attack100;
  struct 
  {
    int x0;
  } attackdash;
  struct 
  {
    bool x0;
  } attacklw3;
  struct 
  {
    float x0;
    int x4;
    int x8;
    void *xC;
    void *x10;
    float x14;
    u8 x18;
    u8 x19;
    u8 x1A;
    u8 x1B;
  } damage;
  struct 
  {
    u8 wall_hit_dir;
    float rot_speed;
    ftCollisionBox ice_coll;
  } damageice;
  struct 
  {
    float escape_timer;
  } damageicejump;
  struct 
  {
    float x0;
    float x4;
    float x8;
    bool xC;
    float x10;
    float x14;
    float x18;
    int x1C;
    int x20;
    int x24;
    void *x28;
    float x2C;
  } guard;
  struct 
  {
    bool x0;
  } itemget;
  struct 
  {
    void *x0;
    int x4;
    float x8;
    HSD_GObj *victim;
    float self_vel_y;
    float self_vel_x;
  } fighterthrow;
  struct 
  {
    float facing_dir;
    float x4;
    int x8;
    int xC;
    float x10;
    int x14;
    void *x18;
    void *x1C;
    int x20;
  } itemthrow;
  struct 
  {
    int unk_timer;
    float anim_spd;
    Vec3 x8;
  } itemthrow4;
  struct 
  {
    int x0;
    float x4;
    float mobility;
    int xC;
    bool x10;
    float landing_lag;
    bool allow_interrupt;
  } fallspecial;
  struct 
  {
    bool x0;
    float x4;
    bool x8;
  } lift;
  struct 
  {
    float x0;
  } downwait;
  struct 
  {
    u8 pad_x0[4];
    u8 x4;
  } downspot;
  struct 
  {
    float x0;
  } catch;
  struct 
  {
    bool x0;
    bool x4;
  } escape;
  struct 
  {
    int timer;
    Vec3 self_vel;
  } escapeair;
  struct 
  {
    float x0;
    float anim_start;
  } rebound;
  struct 
  {
    bool x0;
    float x4;
  } pass;
  struct 
  {
    int ledge_id;
    float x4;
    bool x8;
  } cliff;
  struct 
  {
    bool x0;
  } cliffjump;
  struct 
  {
    bool x0;
  } cargoturn;
  struct 
  {
    int x0;
    int x4;
    float x8;
  } cargokneebend;
  struct 
  {
    float x0;
    int x4;
  } shouldered;
  struct 
  {
    float x0;
  } downdamage;
  struct 
  {
    Fighter_GObj *x0;
    bool x4;
    float x8;
    float xC;
    float x10;
    float x14;
    Vec3 x18;
    Vec3 scale;
  } yoshiegg;
  struct 
  {
    bool x0;
    void *x4;
    float x8;
    float xC;
    float x10;
  } capturekoopa;
  struct 
  {
    Vec2 pos_offset;
    Vec2 x8;
    Vec2 x10;
    bool x18;
    void *x1C;
    void *x20;
    void *x24;
    void *x28;
    Vec3 scale;
  } capturekirby;
  struct 
  {
    Fighter_GObj *thrower_gobj;
    float x4;
    float x8;
    float xC;
    float x10;
    bool x14;
    union 
    {
      u8 x18;
      struct 
      {
        u8 x18_b0 : 1;
        u8 x18_b1 : 1;
        u8 x18_b2 : 1;
        u8 x18_b3 : 1;
        u8 x18_b4 : 1;
        u8 x18_b5 : 1;
        u8 x18_b6 : 1;
        u8 x18_b7 : 1;
      };
    };
    Vec3 scale;
    ftCollisionBox coll_box;
  } thrownkirby;
  struct 
  {
    int x0;
    ftCollisionBox coll_box;
    float x1C;
    enum_t x20;
    Vec3 translate;
  } bury;
  struct 
  {
    float x0;
  } buryjump;
  struct 
  {
    int timer;
    int x4;
    bool x8;
    int vel_y_exponent;
  } passivewall;
  struct 
  {
    int x0;
    float x4;
  } aircatchhit;
  struct 
  {
    float x0;
  } aircatch;
  struct 
  {
    Vec3 cur_pos;
    Vec3 self_vel;
    float facing_dir;
    int x1C;
    ftCollisionBox ecb;
  } warpstar;
  struct 
  {
    int x0;
    int x4;
    float x8;
  } hammerkneebend;
  struct 
  {
    void *x0;
    float x4;
  } hammerlanding;
  struct 
  {
    Item_GObj *x0;
  } captureleadead;
  struct 
  {
    int x0;
    float x4;
    u8 pad_x8[0x18 - 0x8];
    HSD_JObj *x18;
  } capturedamage;
  struct 
  {
    bool timer;
    float x4;
    Vec3 x8;
    Vec3 x14;
    float x20;
    float x24;
    float x28;
    ftCollisionBox x2C;
  } entry;
  struct 
  {
    Item_GObj *x0;
  } capturelikelike;
  struct 
  {
    HSD_GObjEvent x0;
    HSD_GObjEvent x4;
    int x8;
  } mushroom;
  struct 
  {
    int x0;
    int x4;
    Item_GObj *x8;
  } barrel;
  struct 
  {
    HSD_GObjEvent x0;
  } unk_800D2890;
  struct 
  {
    u8 pad_x0[0x6c - 0x40];
    int x6C;
    int x70;
  } unk_800D331C;
  struct 
  {
    u8 pad_x0[0x6c - 0x40];
    int x6C;
    int x70;
  } unk_800D34E0;
  struct 
  {
    void *x40;
    u8 pad_x44[0x6c - 0x44];
    int x6C;
    int x70;
    void *x74;
  } unk_800D3680;
  struct 
  {
    int x40;
  } unk_deadleft;
  struct 
  {
    int x40;
    int x44;
    u8 pad_x48[0x68 - 0x48];
    int x68;
  } unk_deadup;
  struct 
  {
    bool unk_bool;
    float anim_timer;
    void *x8;
    u8 xC;
  } thrown;
  struct 
  {
    FtMotionId prev_msid;
  } parasol_open;
  struct 
  {
    int x0;
    int x4;
    float x8;
  } swing;
  struct 
  {
    int x0;
    int x4;
    int x8;
    Vec xC;
  } throw;
};
struct SmallerHitCapsule
{
  HitCapsuleState state;
  u32 x4;
  u32 unk_count;
  float damage;
  Vec3 b_offset;
  float scale;
  int kb_angle;
  u32 x24;
  u32 x28;
  u32 x2C;
  u32 element;
  char pad_34[0xFC];
};
struct TetherAttributes
{
  char pad_0[0x38];
  float pos_x_0;
  float x3C;
  float pos_x_1;
};
struct ftDonkey_FighterVars
{
  s32 x222C;
  s32 x2230;
};
union ftDonkey_MotionVars
{
  struct ftDonkey_SpecialNVars
  {
    s32 x0;
    s32 x4;
    s32 x8;
    s32 xC;
    s32 x10;
    s32 x14;
  } specialn;
  struct ftDonkey_SpecialLwVars
  {
    s32 x0;
  } speciallw;
  struct ftDonkey_State5Vars
  {
    bool x0;
    s32 x4;
    float x8;
  } unk5;
  struct ftDonkey_State7Vars
  {
    s32 x0;
    s32 x4;
    float x8;
  } unk7;
  struct ftDonkey_State8Vars
  {
    s32 x0;
    float x4;
  } unk8;
};
typedef struct _ftDonkeyAttributes
{
  s32 motion_state;
  s32 x4_motion_state;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  float x1C;
  struct 
  {
    float x20_TURN_SPEED;
    float x24_JUMP_STARTUP_LAG;
    float x28_LANDING_LAG;
  } cargo_hold;
  struct 
  {
    s32 x2C_MAX_ARM_SWINGS;
    s32 x30_DAMAGE_PER_SWING;
    float x34_PUNCH_HORIZONTAL_VEL;
    float x38_LANDING_LAG;
  } SpecialN;
  struct 
  {
    float x3C_MIN_STICK_X_MOMENTUM;
    float x40_MOMENTUM_TRANSITION_MODIFIER;
    float x44_AERIAL_GRAVITY;
  } SpecialS;
  float x48_UNKNOWN;
  struct 
  {
    float x4C_AERIAL_VERTICAL_VELOCITY;
    float x50_AERIAL_GRAVITY;
    float x54_GROUNDED_HORIZONTAL_VELOCITY;
    float x58_AERIAL_HORIZONTAL_VELOCITY;
    float x5C_GROUNDED_MOBILITY;
    float x60_AERIAL_MOBILITY;
    float x64_LANDING_LAG;
  } SpecialHi;
  struct 
  {
    float x68;
    float x6C;
    float x70;
  } SpecialLw;
} ftDonkeyAttributes;
typedef struct ftFox_DatAttrs ftFox_DatAttrs;
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
typedef enum ftFox_MotionState
{
  ftFx_MS_SpecialNStart = ftCo_MS_Count,
  ftFx_MS_SpecialNLoop,
  ftFx_MS_SpecialNEnd,
  ftFx_MS_SpecialAirNStart,
  ftFx_MS_SpecialAirNLoop,
  ftFx_MS_SpecialAirNEnd,
  ftFx_MS_SpecialSStart,
  ftFx_MS_SpecialS,
  ftFx_MS_SpecialSEnd,
  ftFx_MS_SpecialAirSStart,
  ftFx_MS_SpecialAirS,
  ftFx_MS_SpecialAirSEnd,
  ftFx_MS_SpecialHiHold,
  ftFx_MS_SpecialHiHoldAir,
  ftFx_MS_SpecialHi,
  ftFx_MS_SpecialAirHi,
  ftFx_MS_SpecialHiLanding,
  ftFx_MS_SpecialHiFall,
  ftFx_MS_SpecialHiBound,
  ftFx_MS_SpecialLwStart,
  ftFx_MS_SpecialLwLoop,
  ftFx_MS_SpecialLwHit,
  ftFx_MS_SpecialLwEnd,
  ftFx_MS_SpecialLwTurn,
  ftFx_MS_SpecialAirLwStart,
  ftFx_MS_SpecialAirLwLoop,
  ftFx_MS_SpecialAirLwHit,
  ftFx_MS_SpecialAirLwEnd,
  ftFx_MS_SpecialAirLwTurn,
  ftFx_MS_AppealSStartR,
  ftFx_MS_AppealSStartL,
  ftFx_MS_AppealSR,
  ftFx_MS_AppealSL,
  ftFx_MS_AppealSEndR,
  ftFx_MS_AppealSEndL,
  ftFx_MS_Count,
  ftFx_MS_SelfCount = ftFx_MS_Count - ftCo_MS_Count
} ftFox_MotionState;
typedef enum ftFx_Submotion
{
  ftFx_SM_SpecialNStart = ftCo_SM_Count,
  ftFx_SM_SpecialNLoop,
  ftFx_SM_SpecialNEnd,
  ftFx_SM_SpecialAirNStart,
  ftFx_SM_SpecialAirNLoop,
  ftFx_SM_SpecialAirNEnd,
  ftFx_SM_SpecialSStart,
  ftFx_SM_SpecialS,
  ftFx_SM_SpecialSEnd,
  ftFx_SM_SpecialAirSStart,
  ftFx_SM_SpecialAirS,
  ftFx_SM_SpecialAirSEnd,
  ftFx_SM_SpecialHiHold,
  ftFx_SM_SpecialHiHoldAir,
  ftFx_SM_SpecialHi,
  ftFx_SM_SpecialHiLanding,
  ftFx_SM_SpecialHiFall,
  ftFx_SM_SpecialHiBound,
  ftFx_SM_SpecialLwStart,
  ftFx_SM_SpecialLwLoop,
  ftFx_SM_SpecialLwHit,
  ftFx_SM_SpecialLwEnd,
  ftFx_SM_SpecialAirLwStart,
  ftFx_SM_SpecialAirLwLoop,
  ftFx_SM_SpecialAirLwHit,
  ftFx_SM_SpecialAirLwEnd,
  ftFx_SM_AppealSStartR,
  ftFx_SM_AppealSStartL,
  ftFx_SM_AppealSR,
  ftFx_SM_AppealSL,
  ftFx_SM_AppealSEndR,
  ftFx_SM_AppealSEndL,
  ftFx_SM_Count,
  ftFx_SM_SelfCount = ftFx_SM_Count - ftCo_SM_Count
} ftFx_Submotion;
typedef enum ftFx_SpecialNIndex
{
  ftFx_SpecialNIndex_Start,
  ftFx_SpecialNIndex_Loop,
  ftFx_SpecialNIndex_End,
  ftFx_SpecialNIndex_AirStart,
  ftFx_SpecialNIndex_AirLoop,
  ftFx_SpecialNIndex_AirEnd,
  ftFx_SpecialNIndex_ThrowB,
  ftFx_SpecialNIndex_ThrowHi,
  ftFx_SpecialNIndex_ThrowLw
} ftFx_SpecialNIndex;
typedef void (*DSPCallback)(void *task);
typedef struct STRUCT_DSP_TASK
{
  volatile u32 state;
  volatile u32 priority;
  volatile u32 flags;
  u16 *iram_mmem_addr;
  u32 iram_length;
  u32 iram_addr;
  u16 *dram_mmem_addr;
  u32 dram_length;
  u32 dram_addr;
  u16 dsp_init_vector;
  u16 dsp_resume_vector;
  DSPCallback init_cb;
  DSPCallback res_cb;
  DSPCallback done_cb;
  DSPCallback req_cb;
  struct STRUCT_DSP_TASK *next;
  struct STRUCT_DSP_TASK *prev;
  OSTime t_context;
  OSTime t_task;
} DSPTaskInfo;
u32 DSPCheckMailToDSP(void);
u32 DSPCheckMailFromDSP(void);
u32 DSPReadCPUToDSPMbox(void);
u32 DSPReadMailFromDSP(void);
void DSPSendMailToDSP(u32 mail);
void DSPAssertInt(void);
void DSPInit(void);
BOOL DSPCheckInit(void);
void DSPReset(void);
void DSPHalt(void);
void DSPUnhalt(void);
u32 DSPGetDMAStatus(void);
DSPTaskInfo *DSPAddTask(DSPTaskInfo *task);
DSPTaskInfo *DSPCancelTask(DSPTaskInfo *task);
DSPTaskInfo *DSPAssertTask(DSPTaskInfo *task);
DSPTaskInfo *__DSPGetCurrentTask(void);
typedef void (*CARDCallback)(s32 chan, s32 result);
typedef struct CARDFileInfo
{
  s32 chan;
  s32 fileNo;
  s32 offset;
  s32 length;
  u16 iBlock;
} CARDFileInfo;
typedef struct CARDDir
{
  u8 gameName[4];
  u8 company[2];
  u8 _padding0;
  u8 bannerFormat;
  u8 fileName[32];
  u32 time;
  u32 iconAddr;
  u16 iconFormat;
  u16 iconSpeed;
  u8 permission;
  u8 copyTimes;
  u16 startBlock;
  u16 length;
  u8 _padding1[2];
  u32 commentAddr;
} CARDDir;
typedef struct CARDControl
{
  BOOL attached;
  s32 result;
  u16 size;
  u16 pageSize;
  s32 sectorSize;
  u16 cBlock;
  u16 vendorID;
  s32 latency;
  u8 id[12];
  int mountStep;
  u32 scramble;
  int formatStep;
  DSPTaskInfo task;
  void *workArea;
  CARDDir *currentDir;
  u16 *currentFat;
  OSThreadQueue threadQueue;
  u8 cmd[9];
  s32 cmdlen;
  volatile u32 mode;
  int retry;
  int repeat;
  u32 addr;
  void *buffer;
  s32 xferred;
  u16 freeNo;
  u16 startBlock;
  CARDFileInfo *fileInfo;
  CARDCallback extCallback;
  CARDCallback txCallback;
  CARDCallback exiCallback;
  CARDCallback apiCallback;
  CARDCallback xferCallback;
  CARDCallback eraseCallback;
  CARDCallback unlockCallback;
  OSAlarm alarm;
  int cid;
  const DVDDiskID *diskID;
} CARDControl;
typedef struct CARDDecParam
{
  u8 *inputAddr;
  u32 inputLength;
  u32 aramAddr;
  u8 *outputAddr;
} CARDDecParam;
typedef struct CARDID
{
  u8 serial[32];
  u16 deviceID;
  u16 size;
  u16 encode;
  u8 padding[470];
  u16 checkSum;
  u16 checkSumInv;
} CARDID;
void CARDInit(void);
s32 CARDGetResultCode(s32 chan);
s32 CARDFreeBlocks(s32 chan, s32 *byteNotUsed, s32 *filesNotUsed);
long CARDGetEncoding(long chan, unsigned short *encode);
long CARDGetMemSize(long chan, unsigned short *size);
s32 CARDGetSectorSize(s32 chan, u32 *size);
s32 CARDCheckAsync(s32 chan, CARDCallback callback);
long CARDCheck(long chan);
s32 CARDCreateAsync(s32 chan, const char *fileName, u32 size, CARDFileInfo *fileInfo, CARDCallback callback);
long CARDCreate(long chan, char *fileName, unsigned long size, struct CARDFileInfo *fileInfo);
s32 CARDFastDeleteAsync(s32 chan, s32 fileNo, CARDCallback callback);
long CARDFastDelete(long chan, long fileNo);
s32 CARDDeleteAsync(s32 chan, char *fileName, CARDCallback callback);
s32 CARDDelete(s32 chan, char *fileName);
typedef struct CARDDirCheck
{
  u8 padding0[56];
  u16 padding1;
  s16 checkCode;
  u16 checkSum;
  u16 checkSumInv;
} CARDDirCheck;
long CARDFormat(long chan);
int CARDProbe(long chan);
s32 CARDProbeEx(s32 chan, s32 *memSize, s32 *sectorSize);
s32 CARDMountAsync(s32 chan, void *workArea, CARDCallback detachCallback, CARDCallback attachCallback);
s32 CARDMount(s32 chan, void *workArea, CARDCallback detachCallback);
s32 CARDUnmount(s32 chan);
s32 CARDFastOpen(s32 chan, s32 fileNo, CARDFileInfo *fileInfo);
s32 CARDOpen(s32 chan, char *fileName, CARDFileInfo *fileInfo);
s32 CARDClose(CARDFileInfo *fileInfo);
long CARDGetXferredBytes(long chan);
s32 CARDReadAsync(CARDFileInfo *fileInfo, void *buf, s32 length, s32 offset, CARDCallback callback);
long CARDRead(struct CARDFileInfo *fileInfo, void *buf, long length, long offset);
s32 CARDCancel(CARDFileInfo *fileInfo);
s32 CARDRename(s32 chan, char *oldName, char *newName);
typedef struct CARDStat
{
  char fileName[32];
  u32 length;
  u32 time;
  u8 gameName[4];
  u8 company[2];
  u8 bannerFormat;
  u32 iconAddr;
  u16 iconFormat;
  u16 iconSpeed;
  u32 commentAddr;
  u32 offsetBanner;
  u32 offsetBannerTlut;
  u32 offsetIcon[8];
  u32 offsetIconTlut;
  u32 offsetData;
} CARDStat;
s32 CARDGetStatus(s32 chan, s32 fileNo, CARDStat *stat);
s32 CARDSetStatusAsync(s32 chan, s32 fileNo, CARDStat *stat, CARDCallback callback);
long CARDSetStatus(long chan, long fileNo, struct CARDStat *stat);
long CARDWriteAsync(struct CARDFileInfo *fileInfo, void *buf, long length, long offset, void (*callback)(long, long));
long CARDWrite(struct CARDFileInfo *fileInfo, void *buf, long length, long offset);
void CARDInit(void);
s32 CARDGetResultCode(s32 chan);
s32 CARDCheckAsync(s32 chan, CARDCallback callback);
s32 CARDFreeBlocks(s32 chan, s32 *byteNotUsed, s32 *filesNotUsed);
s32 CARDRenameAsync(s32 chan, const char *oldName, const char *newName, CARDCallback callback);
s32 CARDFormatAsync(s32 chan, CARDCallback callback);
struct HitResult
{
  HSD_JObj *bone;
  u8 skip_update_pos : 1;
  Vec3 pos;
  Vec3 offset;
  float size;
};
struct HitVictim
{
  void *victim;
  u32 x4;
};
struct HitCapsule
{
  HitCapsuleState state;
  u32 x4;
  u32 unk_count;
  float damage;
  Vec3 b_offset;
  float scale;
  int kb_angle;
  u32 x24;
  u32 x28;
  u32 x2C;
  u32 element;
  int x34;
  int sfx_severity;
  enum_t sfx_kind;
  u16 x40_b0 : 1;
  u16 x40_b1 : 1;
  u16 x40_b2 : 1;
  u16 x40_b3 : 1;
  u16 x40_b4 : 8;
  u16 x41_b4 : 1;
  u16 x41_b5 : 1;
  u16 x41_b6 : 1;
  u16 x41_b7 : 1;
  u8 x42_b0 : 1;
  u8 x42_b1 : 1;
  u8 x42_b2 : 1;
  u8 x42_b3 : 1;
  u8 x42_b4 : 1;
  u8 x42_b5 : 1;
  u8 x42_b6 : 1;
  u8 x42_b7 : 1;
  u8 x43_b0 : 1;
  u8 x43_b1 : 1;
  u8 x43_b2 : 1;
  u8 x43_b3 : 1;
  u8 x43_b4 : 1;
  u8 x43_b5 : 1;
  u8 x43_b6 : 1;
  u8 x43_b7 : 1;
  u8 x44;
  u8 x45;
  u8 x46[0x48 - 0x46];
  HSD_JObj *jobj;
  Vec3 x4C;
  Vec3 x58;
  Vec3 hurt_coll_pos;
  float coll_distance;
  HitVictim victims_1[12];
  HitVictim victims_2[12];
  union 
  {
    HSD_GObj *owner;
    u8 hit_grabbed_victim_only : 1;
  };
};
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
struct FighterHurtCapsule
{
  HurtCapsule capsule;
  HurtHeight height;
  bool is_grabbable;
};
struct ReflectDesc
{
  u32 x0_bone_id;
  s32 x4_max_damage;
  Vec3 x8_offset;
  float x14_size;
  float x18_damage_mul;
  float x1C_speed_mul;
  u8 x20_behavior;
};
struct AbsorbDesc
{
  int x0_bone_id;
  Vec3 x4_offset;
  float x10_size;
};
struct ShieldDesc
{
  int bone;
  Vec3 pos;
  float radius;
  float dmg_mul;
  float vel_mul;
  u8 flags : 8;
};
struct lbRefract_CallbackData
{
  s32 buffer;
  s32 format;
  s32 width;
  s32 height;
  s32 row_stride;
  s32 buffer_size;
  void *callback0;
  void *callback1;
};
typedef struct _ECBFlagStruct
{
  u8 b0 : 1;
  u8 b1234 : 4;
  u8 b5 : 1;
  u8 b6 : 1;
  u8 b7 : 1;
} ECBFlagStruct;
typedef struct SurfaceData
{
  int index;
  u32 flags;
  Vec3 normal;
} SurfaceData;
typedef struct _itECB
{
  f32 top;
  f32 bottom;
  f32 right;
  f32 left;
} itECB;
typedef struct _ftECB
{
  Vec2 top;
  Vec2 bottom;
  Vec2 right;
  Vec2 left;
} ftECB;
typedef struct ECBSource
{
  ECBSourceKind kind;
  union 
  {
    struct 
    {
      HSD_JObj *x108_joint;
      HSD_JObj *x10C_joint[6];
    };
    struct 
    {
      float up;
      float down;
      float front;
      float back;
      float angle;
    };
  };
  float x124;
  float x128;
  float x12C;
} ECBSource;
struct CollData
{
  HSD_GObj *x0_gobj;
  Vec3 cur_pos;
  Vec3 prev_pos;
  Vec3 last_pos;
  Vec3 x28_vec;
  ECBFlagStruct x34_flags;
  ECBFlagStruct x35_flags;
  s16 facing_dir;
  int x38;
  int floor_skip;
  int ledge_id_right;
  int ledge_id_left;
  int joint_id_skip;
  int joint_id_only;
  float x50;
  float ledge_snap_x;
  float ledge_snap_y;
  float ledge_snap_height;
  float lstick_x;
  ftECB x64_ecb;
  ftECB desired_ecb;
  ftECB ecb;
  ftECB prev_ecb;
  ftECB xE4_ecb;
  ECBSource ecb_source;
  u32 x130_flags;
  s32 env_flags;
  s32 prev_env_flags;
  s32 x13C;
  Vec3 contact;
  SurfaceData floor;
  SurfaceData left_facing_wall;
  SurfaceData right_facing_wall;
  SurfaceData ceiling;
};
struct HSD_AllocEntry
{
  struct HSD_AllocEntry *next;
  u32 *addr;
  size_t size;
};
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
struct lb_800138D8_t
{
  char pad_0[0x11];
  s8 x11;
  s8 x12;
  char pad_13[0x18 - 0x13];
  int x18;
};
struct lb_80432A68_38_t
{
  s32 unk_0;
  s32 unk_4;
};
struct lb_80432A68_t
{
  void *work_area;
  void *lib_area;
  int chan;
  void *unk_C;
  const char *unk_10;
  const char *unk_14;
  s32 unk_18;
  s32 unk_1C;
  void *unk_20;
  int *unk_24;
  int *unk_28;
  char x2C[2];
  char x2E;
  char x2F[4];
  s32 unk_34;
  struct lb_80432A68_38_t unk_38[9];
  s32 unk_80;
  s32 memsize;
  s32 sectorsize;
  s32 unused_bytes;
  s32 unused_files;
  CARDFileInfo file_info;
  s32 unk_A8;
  u8 pad_AC[0xD0 - 0xAC];
  int xD0[9];
  volatile int xF4[9];
  u8 pad_500[(0x50C - 0xF4) - (9 * 4)];
  void (*x50C)(int);
  struct CardTask
  {
    int x0;
    int x4;
    void *x8;
    char *xC;
    char x10[0x20];
    u8 x18;
    char x19[7];
    u8 unk20[0x1C];
  } task_array[11];
  int x8AC;
};
struct ColorOverlay_UnkInner
{
  int x0;
  u8 x4[0x7B - 0x4];
  u8 x7B;
};
union ColorOverlay_x8_t
{
  GXColor light_color;
  struct 
  {
    s32 unk : 6;
    s32 x : 13;
    s32 yz : 13;
  } light_rot1;
  struct 
  {
    u32 x0_0 : 1;
    u32 x0_1 : 1;
    u32 x0_2 : 1;
    u32 x0_3 : 1;
    u32 x0_4 : 1;
    u32 x0_5 : 1;
    u32 light_enable : 1;
    u32 x0_7 : 1;
    s32 x : 12;
    s32 yz : 12;
  } light_rot2;
  struct 
  {
    u32 unk : 6;
    u32 timer : 26;
  } unk;
};
struct ColorOverlay
{
  s32 x0_timer;
  s32 x4_pri;
  union ColorOverlay_x8_t *x8_ptr1;
  s32 xC_loop;
  s32 *x10_ptr2;
  s32 x14;
  s32 *x18_alloc;
  s32 x1c;
  s32 x20;
  s32 x24;
  union 
  {
    enum_t i;
    struct ColorOverlay_UnkInner *ptr;
  } x28_colanim;
  GXColor x2C_hex;
  f32 x30_color_red;
  f32 x34_color_green;
  f32 x38_color_blue;
  f32 x3C_color_alpha;
  f32 x40_colorblend_red;
  f32 x44_colorblend_green;
  f32 x48_colorblend_blue;
  f32 x4C_colorblend_alpha;
  GXColor x50_light_color;
  f32 x54_light_red;
  f32 x58_light_green;
  f32 x5C_light_blue;
  f32 x60_light_alpha;
  f32 x64_lightblend_red;
  f32 x68_lightblend_green;
  f32 x6C_lightblend_blue;
  f32 x70_lightblend_alpha;
  f32 x74_light_rot_x;
  f32 x78_light_rot_yz;
  u8 x7C_color_enable : 1;
  u8 x7C_flag2 : 1;
  u8 x7C_light_enable : 1;
  u8 x7C_flag4 : 1;
  u8 x7C_flag5 : 1;
  u8 x7C_flag6 : 1;
  u8 x7C_flag7 : 1;
  u8 x7C_flag8 : 1;
};
struct lb_80011A50_t
{
  u8 x0;
  u8 x1;
  s8 x2;
  s8 x3;
  Vec3 x4;
  f32 x10;
  f32 x14;
  f32 x18;
  f32 x1C;
  f32 unk_scale;
  f32 x24;
  int unk_count0;
  f32 unk_angle_float;
  int unk_angle_int;
  struct lb_80011A50_t *next;
};
struct lb_80014638_arg0_t
{
  Vec3 x0;
  Vec3 xC;
};
struct lb_80014638_arg1_t
{
  float unk_x;
  float unk_y;
  Vec3 x8;
};
struct Fighter_804D653C_t
{
  void *unk;
  u8 unk4;
  u8 unk5;
};
struct lb_00F9_UnkDesc1Inner
{
  f32 unk_0;
  f32 unk_4;
  s32 unk_8;
  s32 unk_C;
  s32 unk_10;
  s32 unk_14;
  f32 unk_18;
  s32 unk_1C;
  s32 unk_20;
  f32 unk_24;
  s32 unk_28;
  s32 unk_2C;
  s32 unk_30;
  f32 unk_34;
  f32 unk_38;
};
struct lb_00F9_UnkDesc1
{
  struct lb_00F9_UnkDesc1Inner array[2];
};
struct lb_00F9_UnkDesc0
{
  f32 unk_0;
  f32 unk_4;
  s32 unk_8;
  f32 unk_C;
  f32 unk_10;
  f32 unk_14;
  f32 unk_18;
  s32 unk_1C;
  s32 unk_20;
  s32 unk_24;
  s32 unk_28;
  f32 unk_2C;
  s32 unk_30;
  s32 unk_34;
  f32 unk_38;
  char pad_3C[0x78 - 0x3C];
  int unk_78;
  int unk_7C;
  int unk_80;
  f32 unk_84;
  f32 unk_88;
  f32 unk_8C;
};
struct ftDynamics_UnkDesc
{
  HSD_JObj *jobj;
};
union PolymorphicDesc
{
  u8 _[0x90];
  struct lb_00F9_UnkDesc0 lb_unk0;
  struct lb_00F9_UnkDesc1 lb_unk1;
  struct ftDynamics_UnkDesc ft_unk;
  struct AbsorbDesc absorb;
  struct HurtCapsule hurt;
};
struct DynamicsData
{
  union PolymorphicDesc desc;
  struct DynamicsData *next;
};
struct DynamicsDesc
{
  struct DynamicsData *data;
  unsigned int count;
  Vec3 pos;
};
struct BoneDynamicsDesc
{
  enum_t bone_id;
  DynamicsDesc dyn_desc;
};
struct lb_8000FD18_t
{
  char pad_0[0x94];
};
struct lb_804D63A0_t
{
  char pad_0[0xBE00];
};
struct lb_804D63A8_t
{
  char pad_0[0x1C0];
};
struct lbColl_8000A10C_arg0_t
{
  float x0;
  float x4;
  Vec3 x8;
  Vec3 x14;
};
struct Command_00
{
  u32 code : 6;
  u32 value : 26;
};
struct Command_02
{
  u32 code : 6;
  u32 value : 26;
};
struct Command_03
{
  u32 code : 6;
  u32 value : 26;
};
struct Command_04
{
  u32 x;
};
struct Command_05
{
  union CmdUnion *ptr;
};
struct Command_07
{
  union CmdUnion *ptr;
};
struct Command_09
{
  u32 id : 6;
  u32 param_1 : 8;
  u32 param_2 : 18;
};
struct unk0
{
  u32 opcode : 6;
  u32 unk1 : 8;
  u32 unk2 : 18;
};
struct unk1
{
  u32 opcode : 6;
  u32 unk0 : 2;
  u32 unk1 : 4;
  u32 unk2 : 1;
};
struct set_throw_flags
{
  u32 opcode : 6;
  u32 hit_idx : 26;
};
struct unk3
{
  s32 unk0 : 7;
  s32 unk1 : 25;
};
struct unk4
{
  u16 opcode : 6;
  u16 unk1 : 8;
};
struct unk5
{
  s32 unk0 : 14;
  s32 unk1 : 18;
};
struct unk6
{
  u8 opcode : 6;
  u8 unk1 : 1;
};
struct set_airborne_state
{
  u32 opcode : 6;
  u32 state : 26;
};
struct unk8
{
  int unk0;
};
struct part_anim
{
  s32 opcode : 6;
  s32 unk1 : 7;
  s32 unk2 : 7;
  u32 unk3 : 12;
};
struct unk9
{
  s32 unk0 : 6;
  u32 unk1 : 13;
  u32 unk2 : 13;
};
struct unk10
{
  s32 unk0 : 6;
  u32 unk1 : 1;
  u32 unk2 : 12;
  u32 unk3 : 13;
};
struct unk11
{
  s32 unk0 : 6;
  u32 unk1 : 26;
};
struct unk12
{
  u32 unk0 : 6;
  u32 unk1 : 2;
  u32 unk2 : 10;
  u32 unk3 : 14;
};
struct unk13
{
  u32 unk0 : 6;
  u32 unk1 : 8;
  u32 unk2 : 18;
};
struct unk14
{
  u32 unk0 : 6;
  u32 unk1 : 8;
};
struct unk15
{
  u32 unk0 : 6;
  u32 unk1 : 26;
};
struct unk16
{
  u32 unk0 : 6;
  s32 unk3 : 1;
  s32 unk4 : 25;
};
struct unk17
{
  u32 unk0 : 6;
  s32 unk1 : 26;
};
struct unk18
{
  u32 unk0 : 6;
  s32 damage_amount : 26;
};
struct unk19
{
  u32 unk0 : 6;
  u32 unk1 : 26;
};
struct unk20
{
  u32 unk0 : 6;
  u32 unk1 : 26;
};
struct unk21
{
  u32 unk0 : 6;
  u32 unk1 : 1;
  u32 unk2 : 8;
};
struct set_hitbox_damage
{
  u32 opcdoe : 6;
  u32 idx : 3;
  u32 value : 23;
};
struct set_hitbox_scale
{
  u32 opcode : 6;
  u32 idx : 3;
  u32 value : 23;
};
struct set_hitbox_x42_b57
{
  u32 opcode : 6;
  u32 idx : 24;
  u32 type : 1;
  u32 value : 1;
};
struct set_cmd_var
{
  u32 opcode : 6;
  u32 idx : 2;
  u32 value : 24;
};
struct set_hurt_state
{
  u32 opcode : 6;
  u32 bone_idx : 8;
  u32 state : 18;
};
struct set_jab_combo
{
  u32 opcode : 6;
  u32 disabled : 26;
};
struct set_jab_rapid
{
  u32 opcode : 6;
  u32 state : 26;
};
struct set_dobj_flags
{
  u32 opcode : 6;
  s32 idx : 7;
  s32 value : 19;
};
struct set_throw_hitbox_0
{
  u32 opcode : 6;
  u32 idx : 3;
  u32 damage : 23;
};
struct set_throw_hitbox_1
{
  u32 unk0 : 9;
  u32 hit_x24 : 9;
  u32 hit_x28 : 9;
};
struct set_throw_hitbox_2
{
  u32 hit_x2C : 9;
  u32 element : 4;
  u32 sfx_severity : 3;
  u32 sfx_kind : 4;
};
struct unk27
{
  u32 opcode : 6;
  u32 value : 26;
};
struct set_article_vis
{
  u32 opcode : 6;
  u32 value : 26;
};
struct set_fighter_vis
{
  u32 opcode : 6;
  u32 value : 26;
};
struct set_tex_anim
{
  u32 opcode : 6;
  u32 b : 1;
  s32 idx : 7;
  s32 idx2 : 7;
  s32 frame : 11;
};
struct unk31
{
  u32 opcode : 6;
  u32 unk0 : 10;
  u32 unk1 : 16;
};
struct unk32
{
  u32 opcode : 6;
  u32 unk0 : 13;
  u32 unk1 : 13;
};
struct unk33
{
  u32 opcode : 6;
  u32 unk0 : 13;
  u32 unk1 : 13;
};
struct spawn_gfx_0
{
  u32 opcode : 6;
  u32 boneId : 8;
  u32 useCommonBoneIDs : 1;
  u32 destroyOnStateChange : 1;
  u32 useUnkBone : 1;
  u32 unk1 : 15;
};
struct spawn_gfx_1
{
  u32 gfxID : 16;
  u32 unkFloat : 16;
};
struct spawn_gfx_2
{
  s16 offsetZ : 16;
  s16 offsetY : 16;
};
struct spawn_gfx_3
{
  s16 offsetX : 16;
  u16 rangeZ : 16;
};
struct spawn_gfx_4
{
  u16 rangeY : 16;
  u16 rangeX : 16;
};
struct spawn_hitbox_0
{
  u32 opcode : 6;
  u32 id : 3;
  u32 hit_group : 3;
  u32 only_hit_grabbed : 1;
  u32 bone : 8;
  u32 use_common_bone_ids : 1;
  u32 damage : 10;
};
struct spawn_hitbox_1
{
  u32 size : 16;
  s32 z_offset : 16;
};
struct spawn_hitbox_2
{
  s32 y_offset : 16;
  s32 x_offset : 16;
};
struct spawn_hitbox_3
{
  u32 angle : 9;
  u32 knockback_growth : 9;
  u32 weight_set_knockback : 9;
  u32 item_hit_interaction : 1;
  u32 ignore_thrown_fighters : 1;
  u32 ignore_fighter_scale : 1;
  u32 clank : 1;
  u32 rebound : 1;
};
struct spawn_hitbox_4
{
  u32 base_knockback : 9;
  u32 element : 5;
  s32 shield_damage : 8;
  u32 hit_sfx_severity : 3;
  u32 hit_sfx_kind : 5;
  u32 hit_grounded : 1;
  u32 hit_aerial : 1;
};
struct spawn_hitbox_5
{
  u32 x0 : 8;
  u32 x1_b0 : 1;
  u32 x1_b1 : 1;
  u32 x1_b2 : 1;
  u32 x1_b3 : 1;
  u32 x1_b4 : 1;
  u32 x1_b5 : 1;
  u32 x1_b6 : 1;
  u32 x1_b7 : 1;
};
struct spawn_hitbox_skip
{
  u8 _0[0xF];
  u32 xF_b0 : 1;
  u32 xF_b1 : 1;
  u32 xF_b2 : 1;
  u32 xF_b3 : 1;
  u32 xF_b4 : 1;
};
struct sound_effect_0
{
  u32 opcode : 6;
  u32 behavior : 8;
  u32 unknown : 18;
};
struct sound_effect_1
{
  u32 sfx_id;
};
struct sound_effect_2
{
  u32 padding : 16;
  u32 volume : 8;
  u32 panning : 8;
};
struct pseudo_random_sfx_0
{
  u32 opcode : 6;
  u32 volume : 8;
  u32 panning : 8;
  u32 behavior : 4;
  u32 random_range : 6;
};
struct pseudo_random_sfx_1
{
  u32 sfx_id;
};
struct stage_sfx_0
{
  u32 opcode : 6;
  u32 sfx_base : 10;
  u32 x2_b0_7 : 8;
  u32 pitch_select : 8;
};
struct stage_sfx_1
{
  u32 sfx_id;
};
struct stage_sfx_2
{
  u32 x0_b0_15 : 16;
  u32 x2_b0_15 : 16;
};
struct stage_sfx_3
{
  u32 x0_b0_15 : 16;
  u32 x2_b0_7 : 8;
  u32 x3_b0_7 : 8;
};
struct footstep_fx_0
{
  u32 opcode : 6;
  u32 x0_b6_7 : 2;
  u32 use_alt_bone : 1;
  u32 x1_b1_7 : 7;
  u32 x2_b0_7 : 8;
  u32 x3_b0_7 : 8;
};
struct unk_fx_0
{
  u32 opcode : 6;
  u32 x0_b6_7 : 2;
  u32 x1_b0_7 : 8;
  u32 x2_b0_7 : 8;
  u32 x3_b0_7 : 8;
};
struct smash_charge_0
{
  u32 opcode : 6;
  u32 charge_frames : 10;
  u32 charge_rate : 16;
};
struct smash_charge_1
{
  u32 color_anim : 8;
  u32 x1_b0_23 : 24;
};
struct wind_fx_0
{
  u32 opcode : 6;
  u32 x0_b6_17 : 18;
  u32 bone : 8;
};
struct wind_fx_1
{
  s16 timer : 16;
  s16 x : 16;
};
struct wind_fx_2
{
  s16 y : 16;
  s16 mag : 16;
};
struct wind_fx_3
{
  s16 angle : 16;
  s16 decay : 16;
};
struct CommandInfo
{
  f32 timer;
  f32 frame_count;
  union 
  {
    u32 *ptr[1];
    union CmdUnion
    {
      struct Command_00 Command_00;
      struct Command_02 Command_02;
      struct Command_03 Command_03;
      struct Command_04 Command_04;
      struct Command_05 Command_05;
      struct Command_07 Command_07;
      struct Command_09 Command_09;
      struct unk0 unk0;
      struct unk1 unk1;
      struct set_throw_flags set_throw_flags;
      struct unk3 unk3;
      struct unk4 unk4;
      struct unk5 unk5;
      struct unk6 unk6;
      struct set_airborne_state set_airborne_state;
      struct unk8 unk8;
      struct part_anim part_anim;
      struct unk9 unk9;
      struct unk10 unk10;
      struct unk11 unk11;
      struct unk12 unk12;
      struct unk13 unk13;
      struct unk14 unk14;
      struct unk15 unk15;
      struct unk16 unk16;
      struct unk17 unk17;
      struct unk18 unk18;
      struct unk19 unk19;
      struct unk20 unk20;
      struct unk21 unk21;
      struct set_hitbox_damage set_hitbox_damage;
      struct set_hitbox_scale set_hitbox_scale;
      struct set_hitbox_x42_b57 set_hitbox_x42_b57;
      struct set_cmd_var set_cmd_var;
      struct set_hurt_state set_hurt_state;
      struct set_jab_combo set_jab_combo;
      struct set_jab_rapid set_jab_rapid;
      struct set_dobj_flags set_dobj_flags;
      struct set_throw_hitbox_0 set_throw_hitbox_0;
      struct set_throw_hitbox_1 set_throw_hitbox_1;
      struct set_throw_hitbox_2 set_throw_hitbox_2;
      struct unk27 unk27;
      struct set_article_vis set_article_vis;
      struct set_fighter_vis set_fighter_vis;
      struct set_tex_anim set_tex_anim;
      struct unk31 unk31;
      struct unk32 unk32;
      struct unk33 unk33;
      struct spawn_gfx_0 spawn_gfx_0;
      struct spawn_gfx_1 spawn_gfx_1;
      struct spawn_gfx_2 spawn_gfx_2;
      struct spawn_gfx_3 spawn_gfx_3;
      struct spawn_gfx_4 spawn_gfx_4;
      struct spawn_hitbox_0 create_hitbox_0;
      struct spawn_hitbox_1 create_hitbox_1;
      struct spawn_hitbox_2 create_hitbox_2;
      struct spawn_hitbox_3 create_hitbox_3;
      struct spawn_hitbox_4 create_hitbox_4;
      struct spawn_hitbox_5 create_hitbox_5;
      struct sound_effect_0 sound_effect_0;
      struct sound_effect_1 sound_effect_1;
      struct sound_effect_2 sound_effect_2;
      struct pseudo_random_sfx_0 pseudo_random_sfx_0;
      struct pseudo_random_sfx_1 pseudo_random_sfx_1;
      struct stage_sfx_0 stage_sfx_0;
      struct stage_sfx_1 stage_sfx_1;
      struct stage_sfx_2 stage_sfx_2;
      struct stage_sfx_3 stage_sfx_3;
      struct footstep_fx_0 footstep_fx_0;
      struct unk_fx_0 unk_fx_0;
      struct smash_charge_0 smash_charge_0;
      struct smash_charge_1 smash_charge_1;
      struct wind_fx_0 wind_fx_0;
      struct wind_fx_1 wind_fx_1;
      struct wind_fx_2 wind_fx_2;
      struct wind_fx_3 wind_fx_3;
    } *u;
  };
  u32 loop_count;
  union CmdUnion *event_return[3];
  u32 loop_count_dup;
  u32 unk_x18;
};
struct LbShadow
{
  u8 x0_b0 : 1;
  u8 x0_b1 : 1;
  u8 x0_b2 : 1;
  u8 x0_b3 : 1;
  u8 x0_b4 : 1;
  u8 x0_b5 : 1;
  u8 x0_b6 : 1;
  u8 x0_b7 : 1;
  HSD_Shadow *shadow;
};
struct ftFox_FighterVars
{
  HSD_GObj *x222C_blasterGObj;
};
typedef struct ftFoxSpecialN
{
  bool isBlasterLoop;
} ftFoxSpecialN;
typedef struct ftFoxSpecialS
{
  s32 gravityDelay;
  Vec3 ghostEffectPos[4];
  float blendFrames[4];
  HSD_GObj *ghostGObj;
} ftFoxSpecialS;
typedef struct ftFoxSpecialHi
{
  s32 gravityDelay;
  float rotateModel;
  s32 travelFrames;
  s32 unk;
  s32 unk2;
} ftFoxSpecialHi;
typedef struct ftFoxSpecialLw
{
  s32 releaseLag;
  s32 turnFrames;
  bool isRelease;
  s32 gravityDelay;
} ftFoxSpecialLw;
typedef struct ftFoxAppealS
{
  bool facingDir;
  s32 animCount;
} ftFoxAppealS;
typedef union ftFox_MotionVars
{
  ftFoxSpecialN SpecialN;
  ftFoxSpecialS SpecialS;
  ftFoxSpecialHi SpecialHi;
  ftFoxSpecialLw SpecialLw;
  ftFoxAppealS AppealS;
} ftFox_MotionVars;
struct ftFox_DatAttrs
{
  float x0_FOX_BLASTER_UNK1;
  float x4_FOX_BLASTER_UNK2;
  float x8_FOX_BLASTER_UNK3;
  float xC_FOX_BLASTER_UNK4;
  float x10_FOX_BLASTER_ANGLE;
  float x14_FOX_BLASTER_VEL;
  float x18_FOX_BLASTER_LANDING_LAG;
  ItemKind x1C_FOX_BLASTER_SHOT_ITKIND;
  ItemKind x20_FOX_BLASTER_GUN_ITKIND;
  float x24_FOX_ILLUSION_GRAVITY_DELAY;
  float x28_FOX_ILLUSION_GROUND_VEL_X;
  float x2C_FOX_ILLUSION_UNK1;
  float x30_FOX_ILLUSION_UNK2;
  float x34_FOX_ILLUSION_GROUND_END_VEL_X;
  float x38_FOX_ILLUSION_GROUND_FRICTION;
  float x3C_FOX_ILLUSION_AIR_END_VEL_X;
  float x40_FOX_ILLUSION_AIR_MUL_X;
  float x44_FOX_ILLUSION_FALL_ACCEL;
  float x48_FOX_ILLUSION_TERMINAL_VELOCITY;
  float x4C_FOX_ILLUSION_FREEFALL_MOBILITY;
  float x50_FOX_ILLUSION_LANDING_LAG;
  float x54_FOX_FIREFOX_GRAVITY_DELAY;
  float x58_FOX_FIREFOX_VEL_X;
  float x5C_FOX_FIREFOX_AIR_MOMENTUM_PRESERVE_X;
  float x60_FOX_FIREFOX_FALL_ACCEL;
  float x64_FOX_FIREFOX_DIRECTION_STICK_RANGE_MIN;
  float x68_FOX_FIREFOX_DURATION;
  s32 x6C_FOX_FIREFOX_BOUNCE_VAR;
  float x70_FOX_FIREFOX_DURATION_END;
  float x74_FOX_FIREFOX_SPEED;
  float x78_FOX_FIREFOX_REVERSE_ACCEL;
  float x7C_FOX_FIREFOX_GROUND_MOMENTUM_END;
  float x80_FOX_FIREFOX_UNK2;
  float x84_FOX_FIREFOX_BOUND_VEL_X;
  float x88_FOX_FIREFOX_FACING_STICK_RANGE_MIN;
  float x8C_FOX_FIREFOX_FREEFALL_MOBILITY;
  float x90_FOX_FIREFOX_LANDING_LAG;
  float x94_FOX_FIREFOX_BOUND_ANGLE;
  float x98_FOX_REFLECTOR_RELEASE_LAG;
  float x9C_FOX_REFLECTOR_TURN_FRAMES;
  float xA0_FOX_REFLECTOR_UNK1;
  s32 xA4_FOX_REFLECTOR_GRAVITY_DELAY;
  float xA8_FOX_REFLECTOR_MOMENTUM_PRESERVE_X;
  float xAC_FOX_REFLECTOR_FALL_ACCEL;
  ReflectDesc xB0_FOX_REFLECTOR_REFLECTION;
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
typedef enum ftGameWatch_MotionState
{
  ftGw_MS_Attack11 = ftCo_MS_Count,
  ftGw_MS_Attack100Start,
  ftGw_MS_Attack100Loop,
  ftGw_MS_Attack100End,
  ftGw_MS_AttackLw3,
  ftGw_MS_AttackS4,
  ftGw_MS_AttackAirN,
  ftGw_MS_AttackAirB,
  ftGw_MS_AttackAirHi,
  ftGw_MS_LandingAirN,
  ftGw_MS_LandingAirB,
  ftGw_MS_LandingAirHi,
  ftGw_MS_SpecialN,
  ftGw_MS_SpecialAirN,
  ftGw_MS_SpecialS1,
  ftGw_MS_SpecialS2,
  ftGw_MS_SpecialS3,
  ftGw_MS_SpecialS4,
  ftGw_MS_SpecialS5,
  ftGw_MS_SpecialS6,
  ftGw_MS_SpecialS7,
  ftGw_MS_SpecialS8,
  ftGw_MS_SpecialS9,
  ftGw_MS_SpecialAirS1,
  ftGw_MS_SpecialAirS2,
  ftGw_MS_SpecialAirS3,
  ftGw_MS_SpecialAirS4,
  ftGw_MS_SpecialAirS5,
  ftGw_MS_SpecialAirS6,
  ftGw_MS_SpecialAirS7,
  ftGw_MS_SpecialAirS8,
  ftGw_MS_SpecialAirS9,
  ftGw_MS_SpecialHi,
  ftGw_MS_SpecialAirHi,
  ftGw_MS_SpecialLw,
  ftGw_MS_SpecialLwCatch,
  ftGw_MS_SpecialLwShoot,
  ftGw_MS_SpecialAirLw,
  ftGw_MS_SpecialAirLwCatch,
  ftGw_MS_SpecialAirLwShoot,
  ftGw_MS_Count,
  ftGw_MS_SelfCount = ftGw_MS_Count - ftCo_MS_Count
} ftGameWatch_MotionState;
typedef enum ftGw_Submotion
{
  ftGw_SM_SpecialN = ftCo_SM_Count,
  ftGw_SM_SpecialAirN,
  ftGw_SM_SpecialS1,
  ftGw_SM_SpecialS2,
  ftGw_SM_SpecialS3,
  ftGw_SM_SpecialS4,
  ftGw_SM_SpecialS5,
  ftGw_SM_SpecialS6,
  ftGw_SM_SpecialS7,
  ftGw_SM_SpecialS8,
  ftGw_SM_SpecialS9,
  ftGw_SM_SpecialAirS1,
  ftGw_SM_SpecialAirS2,
  ftGw_SM_SpecialAirS3,
  ftGw_SM_SpecialAirS4,
  ftGw_SM_SpecialAirS5,
  ftGw_SM_SpecialAirS6,
  ftGw_SM_SpecialAirS7,
  ftGw_SM_SpecialAirS8,
  ftGw_SM_SpecialAirS9,
  ftGw_SM_SpecialHi,
  ftGw_SM_SpecialAirHi,
  ftGw_SM_SpecialLw,
  ftGw_SM_SpecialLwCatch,
  ftGw_SM_SpecialLwShoot,
  ftGw_SM_SpecialAirLw,
  ftGw_SM_SpecialAirLwCatch,
  ftGw_SM_SpecialAirLwShoot,
  ftGw_SM_Count,
  ftGw_SM_SelfCount = ftGw_SM_Count - ftCo_SM_Count
} ftGw_Submotion;
typedef enum ftGameWatch_PanicLevel
{
  ftGw_Panic_Empty,
  ftGw_Panic_Low,
  ftGw_Panic_Mid,
  ftGw_Panic_Full
} ftGameWatch_PanicLevel;
struct ftGameWatch_FighterVars
{
  s32 x222C_judgeVar1;
  s32 x2230_judgeVar2;
  u32 x2234;
  s32 x2238_panicCharge;
  s32 x223C_panicDamage;
  s32 x2240_chefVar1;
  s32 x2244_chefVar2;
  HSD_GObj *x2248_manholeGObj;
  HSD_GObj *x224C_greenhouseGObj;
  HSD_GObj *x2250_manholeGObj2;
  HSD_GObj *x2254_fireGObj;
  HSD_GObj *x2258_parachuteGObj;
  HSD_GObj *x225C_turtleGObj;
  HSD_GObj *x2260_sparkyGObj;
  HSD_GObj *x2264_judgementGObj;
  HSD_GObj *x2268_panicGObj;
  HSD_GObj *x226C_rescueGObj;
};
typedef struct ftGameWatchChef
{
  int sausageCount[6];
} ftGameWatchChef;
typedef struct ftGameWatchJudge
{
  s32 rollVar[9];
} ftGameWatchJudge;
typedef struct _ftGameWatchAttributes
{
  float x0_GAMEWATCH_WIDTH;
  GXColor x4_GAMEWATCH_COLOR[4];
  GXColor x14_GAMEWATCH_OUTLINE;
  float x18_GAMEWATCH_CHEF_LOOPFRAME;
  float x1C_GAMEWATCH_CHEF_MAX;
  float x20_GAMEWATCH_JUDGE_MOMENTUM_PRESERVE;
  float x24_GAMEWATCH_JUDGE_MOMENTUM_MUL;
  float x28_GAMEWATCH_JUDGE_VEL_Y;
  float x2C_GAMEWATCH_JUDGE_FRICTION1;
  float x30_GAMEWATCH_JUDGE_FRICTION2;
  s32 x34_GAMEWATCH_JUDGE_ROLL[9];
  float x58_GAMEWATCH_RESCUE_STICK_RANGE;
  float x5C_GAMEWATCH_RESCUE_ANGLE_UNK;
  float x60_GAMEWATCH_RESCUE_LANDING;
  float x64_GAMEWATCH_PANIC_MOMENTUM_PRESERVE;
  float x68_GAMEWATCH_PANIC_MOMENTUM_MUL;
  float x6C_GAMEWATCH_PANIC_FALL_ACCEL;
  float x70_GAMEWATCH_PANIC_VEL_Y_MAX;
  float x74_GAMEWATCH_PANIC_DAMAGE_ADD;
  float x78_GAMEWATCH_PANIC_DAMAGE_MUL;
  float x7C_GAMEWATCH_PANIC_TURN_FRAMES;
  AbsorbDesc x80_GAMEWATCH_PANIC_ABSORPTION;
} ftGameWatchAttributes;
typedef union ftGameWatch_MotionVars
{
  struct ftGameWatch_Attack11Vars
  {
    bool unk;
  } Attack11;
  struct ftGameWatch_SpecialNVars
  {
    bool isChefLoopDisable;
    s32 maxSausage;
  } SpecialN;
  struct ftGameWatch_SpecialLwVars
  {
    bool isRelease;
    s32 turnFrames;
  } SpecialLw;
} ftGameWatch_MotionVars;
struct DObjList
{
  u32 count;
  HSD_DObj **data;
};
struct ftMars_FighterVars
{
  u32 x222C;
  u8 _[0xF8 - 4];
};
struct SwordAttrs
{
  u8 pad_x0[0x14];
  int x14;
  float x18;
  float x1C;
};
typedef struct _MarsAttributes
{
  int x0;
  int x4;
  int x8;
  float specialn_friction;
  float specialn_start_friction;
  float x14;
  float x18;
  float x1C;
  float x20;
  float x24;
  float x28;
  float x2C;
  float x30;
  float x34;
  float x38;
  float x3C;
  float x40;
  float x44;
  float x48;
  float x4C;
  float x50;
  float x54;
  float x58;
  float x5C;
  float x60;
  AbsorbDesc x64;
  struct SwordAttrs x78;
} MarsAttributes;
union ftMars_MotionVars
{
  struct ftMars_Unk0MotionVars
  {
    bool x0;
  } unk0;
  struct ftMars_SpecialNVars
  {
    int cur_frame;
  } specialn;
  struct ftMars_SpecialSVars
  {
    int x0;
  } specials;
  struct ftMars_SpecialLwVars
  {
    int x0;
  } speciallw;
};
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
typedef enum ftNess_MotionState
{
  ftNs_MS_AttackS4 = ftCo_MS_Count,
  ftNs_MS_AttackHi4,
  ftNs_MS_AttackHi4Charge,
  ftNs_MS_AttackHi4Release,
  ftNs_MS_AttackLw4,
  ftNs_MS_AttackLw4Charge,
  ftNs_MS_AttackLw4Release,
  ftNs_MS_SpecialNStart,
  ftNs_MS_SpecialNHold,
  ftNs_MS_SpecialNRelease,
  ftNs_MS_SpecialNEnd,
  ftNs_MS_SpecialAirNStart,
  ftNs_MS_SpecialAirNHold,
  ftNs_MS_SpecialAirNRelease,
  ftNs_MS_SpecialAirNEnd,
  ftNs_MS_SpecialS,
  ftNs_MS_SpecialAirS,
  ftNs_MS_SpecialHiStart,
  ftNs_MS_SpecialHiHold,
  ftNs_MS_SpecialHiEnd,
  ftNs_MS_SpecialHi,
  ftNs_MS_SpecialAirHiStart,
  ftNs_MS_SpecialAirHiHold,
  ftNs_MS_SpecialAirHiEnd,
  ftNs_MS_SpecialAirHi,
  ftNs_MS_SpecialAirHiRebound,
  ftNs_MS_SpecialLwStart,
  ftNs_MS_SpecialLwHold,
  ftNs_MS_SpecialLwHit,
  ftNs_MS_SpecialLwEnd,
  ftNs_MS_SpecialLwTurn,
  ftNs_MS_SpecialAirLwStart,
  ftNs_MS_SpecialAirLwHold,
  ftNs_MS_SpecialAirLwHit,
  ftNs_MS_SpecialAirLwEnd,
  ftNs_MS_SpecialAirLwTurn,
  ftNs_MS_Count,
  ftNs_MS_SelfCount = ftNs_MS_Count - ftCo_MS_Count
} ftNess_MotionState;
typedef enum ftNs_Submotion
{
  ftNs_SM_AttackHi4Charge = ftCo_SM_Count,
  ftNs_SM_AttackHi4Release,
  ftNs_SM_AttackLw4Charge,
  ftNs_SM_AttackLw4Release,
  ftNs_SM_SpecialNStart,
  ftNs_SM_SpecialNHold0,
  ftNs_SM_SpecialNHold1,
  ftNs_SM_SpecialNEnd,
  ftNs_SM_SpecialAirNStart,
  ftNs_SM_SpecialAirNHold0,
  ftNs_SM_SpecialAirNHold1,
  ftNs_SM_SpecialAirNEnd,
  ftNs_SM_SpecialS,
  ftNs_SM_SpecialAirS,
  ftNs_SM_SpecialHiStart,
  ftNs_SM_SpecialHiHold,
  ftNs_SM_SpecialHiEnd,
  ftNs_SM_SpecialHi,
  ftNs_SM_SpecialAirHiStart,
  ftNs_SM_SpecialAirHiHold,
  ftNs_SM_SpecialAirHiEnd,
  ftNs_SM_SpecialAirHi,
  ftNs_SM_SpecialAirHiRebound,
  ftNs_SM_SpecialLwStart,
  ftNs_SM_SpecialLwHold,
  ftNs_SM_SpecialLwHit,
  ftNs_SM_SpecialLwEnd,
  ftNs_SM_SpecialAirLwStart,
  ftNs_SM_SpecialAirLwHold,
  ftNs_SM_SpecialAirLwHit,
  ftNs_SM_SpecialAirLwEnd,
  ftNs_SM_Count,
  ftNs_SM_SelfCount = ftNs_SM_Count - ftCo_SM_Count
} ftNs_Submotion;
struct ftNess_FighterVars
{
  HSD_GObj *yoyo_gobj;
  Vec3 yoyo_hitbox_pos;
  float x223C;
  HSD_GObj *pkflash_gobj;
  HSD_GObj *pkthunder_gobj;
  HSD_GObj *bat_gobj;
  u32 pkthunder_gfx;
};
struct ftNess_YoyoVars
{
  s32 yoyoCurrentFrame;
  s32 yoyoRehitTimer;
  bool isChargeDisable;
  bool isPosUpdateMod;
};
union ftNess_MotionVars
{
  struct ftNess_YoyoVars attackhi4;
  struct ftNess_YoyoVars attacklw4;
  struct ftNess_SpecialNVars
  {
    int frames_to_loop_charge_ground;
    int frames_to_loop_charge_air;
    int falling_acceleration_delay;
    int charge_release_delay;
  } specialn;
  struct ftNess_SpecialHiVars
  {
    s32 thunderColl;
    s32 thunderTimerLoop1;
    s32 thunderTimerLoop2;
    s32 gravityDelay;
    Vec3 collPos1;
    Vec3 collPos2;
    float aerialVel;
    float unkVar;
    float facingDir;
    Vec3 unkVector1;
    s32 jibakuGFX;
    float fallAccel;
    float unkVar3;
    float unkVar4;
  } specialhi;
  struct ftNess_SpecialLwVars
  {
    s32 releaseLag;
    s32 turnFrames;
    bool isRelease;
    s32 gravityDelay;
    s32 x10;
  } speciallw;
};
typedef struct ftNessAttributes
{
  s32 x0_PKFLASH_TIMER1_LOOPFRAMES;
  s32 x4_PKFLASH_TIMER2_LOOPFRAMES;
  s32 x8_PKFLASH_GRAVITY_DELAY;
  s32 xC_PKFLASH_MINCHARGEFRAMES;
  float x10_PKFLASH_UNK1;
  float x14_PKFLASH_FALL_ACCEL;
  float x18_PKFLASH_UNK2;
  float x1C_PKFLASH_LANDING_LAG;
  float x20_PKFIRE_AERIAL_LAUNCH_TRAJECTORY;
  float x24_PKFIRE_AERIAL_VELOCITY;
  float x28_PKFIRE_GROUNDED_LAUNCH_TRAJECTORY;
  float x2C_PKFIRE_GROUNDED_VELOCITY;
  float x30_PKFIRE_SPAWN_X;
  float x34_PKFIRE_SPAWN_Y;
  float x38_PKFIRE_LANDING_LAG;
  float x3C_PK_THUNDER_UNK1;
  u32 x40_PK_THUNDER_LOOP1;
  u32 x44_PK_THUNDER_LOOP2;
  u32 x48_PK_THUNDER_GRAVITY_DELAY;
  float x4C_PK_THUNDER_UNK2;
  float x50_PK_THUNDER_FALL_ACCEL;
  float x54_PK_THUNDER_2_MOMENTUM;
  float x58_PK_THUNDER_2_UNK1;
  float x5C_PK_THUNDER_2_DECELERATION_RATE;
  float x60_PK_THUNDER_2_KNOCKDOWN_ANGLE;
  float x64_PK_THUNDER_2_WALLHUG_ANGLE;
  float x68_PK_THUNDER_2_UNK2;
  float x6C_PK_THUNDER_2_FREEFALL_ANIM_BLEND;
  float x70_PK_THUNDER_2_LANDING_LAG;
  float x74_PSI_MAGNET_RELEASE_LAG;
  float x78_PSI_MAGNET_UNK1;
  float x7C_PSI_MAGNET_UNK2;
  float x80_PSI_MAGNET_UNK3;
  s32 x84_PSI_MAGNET_FRAMES_BEFORE_GRAVITY;
  float x88_PSI_MAGNET_MOMENTUM_PRESERVATION;
  float x8C_PSI_MAGNET_FALL_ACCEL;
  float x90_PSI_MAGNET_UNK4;
  float x94_PSI_MAGNET_HEAL_MUL;
  AbsorbDesc x98_PSI_MAGNET_ABSORPTION;
  float xAC_YOYO_CHARGE_DURATION;
  float xB0_YOYO_DAMAGE_MUL;
  float xB4_YOYO_REHIT_RATE;
  ReflectDesc xB8_BASEBALL_BAT;
} ftNessAttributes;
struct ftKb_FighterVars
{
  struct ftKb_Hat
  {
    void *x0;
    s32 x4;
    u8 x8_b0 : 1;
    u8 x9[3];
    FighterKind kind;
    HSD_JObj *jobj;
    DObjList x14;
    u32 x1C;
    void *x20;
    u32 x24;
  } hat;
  HSD_DObj **x28;
  u8 _2C[0x44 - 0x2C];
  struct KirbyFV_x44_t
  {
    int x0;
  } x44;
  u8 _48[0x60 - 0x48];
  void *x60;
  bool x64;
  u8 _68[0x74 - 0x68];
  u32 x74;
  u32 x78;
  Item_GObj *ns_flash_gobj;
  u8 x80[0x9C - 0x80];
  int x9C;
  void *xA0;
  void *xA4;
  int xA8;
  void *xAC;
  u32 xB0;
  int xB4;
  u32 xB8;
  int xBC;
  Item_GObj *xC0;
  bool xC4;
  void *xC8;
  bool xCC;
  Item_GObj *xD0;
  int xD4;
  int xD8;
  Item_GObj *xDC;
  int xE0;
  short xE4;
  float xE8;
  float xEC;
  float xF0;
  u8 xF4_b0 : 1;
};
struct ftKb_SpecialNMs_DatAttrs
{
  u32 charge_iterations;
  u32 base_damage;
  u32 additional_damage_per_iteration;
  float air_horizontal_momentum_preservation;
  float air_horizontal_deceleration_rate;
};
struct ftKb_DatAttrs
{
  u32 jumpaerial_turn_duration;
  float jumpaerial_horizontal_momentum_backwards;
  float jumpaerial_horizontal_momentum_forwards;
  float jumpaerial_momentum_from_turning;
  float jumpaerial_horizontal_momentum;
  float jumpaerial_jump1_vertical_momentum;
  float jumpaerial_jump2_vertical_momentum;
  float jumpaerial_jump3_vertical_momentum;
  float jumpaerial_jump4_vertical_momentum;
  float jumpaerial_jump5_vertical_momentum;
  u32 jumpaerial_number_of_jumps;
  u32 jumpaerial_first_jump_action_state;
  u32 jumpaerial_final_jump_action_state;
  s16 jumpaerial_unk;
  float specialn_x_offset_inhaled;
  float specialn_y_offset_inhaled;
  float specialn_z_offset_inhaled;
  float specialn_gravity_of_inhaled;
  float specialn_velocity_outer_grab_box;
  float specialn_velocity_inner_grab_box;
  float specialn_inhale_velocity;
  float specialn_inhale_resistance;
  float specialn_duration_divisor;
  float specialn_base_duration;
  float specialn_star_deceleration_rate;
  float specialn_star_duration_divisor;
  float specialn_star_base_duration;
  float specialn_frames_in_swallow_star;
  float specialn_spit_spin;
  float specialn_x_axis_range_walk;
  float specialn_y_axis_range_jump;
  float specialn_walk_speed;
  float specialn_jump_height;
  float specialn_stop_momentum;
  float specialn_ground_spit_initial_horizontal_velocity;
  float specialn_spit_deceleration_rate;
  float specialn_spit_out_release_angle;
  float specialn_swallow_star_vertical_velocity;
  float specialn_swallow_star_gravity;
  float specialn_opponent_horizontal_velocity;
  float specialn_opponent_vertical_velocity;
  float specialn_ability_loss_star_x;
  float specialn_ability_loss_star_y;
  float specialn_ability_loss_star_z;
  float specialn_odds_lose_ability_on_hit;
  float specialn_unk1;
  float specialn_swallow_star_y_release;
  float specialn_unk2;
  float specialn_unk3;
  float specialn_unk4;
  float specialn_unk5;
  float specials_aerial_vertical_momentum;
  float specials_landing_lag;
  float specialhi_vertical_momentum;
  float specialhi_horizontal_momentum;
  float specialhi_projectile_spawn_x;
  float specialhi_projectile_spawn_y;
  float specialhi_reverse_upb_stick_range;
  float specialhi_unk;
  u32 speciallw_max_time_in_stone;
  u32 speciallw_min_time_in_stone;
  float speciallw_min_slant_angle_slide;
  float speciallw_max_slant_angle_slide;
  float speciallw_slide_acceleration;
  float speciallw_slide_max_speed;
  float speciallw_gravity;
  s32 speciallw_hp;
  u32 speciallw_resistance;
  u32 speciallw_unk;
  float speciallw_freefall_toggle;
  u32 specialn_kp_b_button_check_frequency;
  float specialn_kp_fuel_recharge_rate;
  float specialn_kp_flame_size_recharge_rate;
  float specialn_kp_max_fuel;
  float specialn_kp_spew_flame_velocity;
  float specialn_kp_flame_scale;
  float specialn_kp_lowest_charge_graphic_size;
  u32 specialn_kp_screen_shake_frequency;
  float specialn_kp_breath_x_offset;
  float specialn_kp_breath_y_offset;
  u32 specialn_gk_b_button_check_frequency;
  float specialn_gk_fuel_recharge_rate;
  float specialn_gk_flame_size_recharge_rate;
  float specialn_gk_max_fuel;
  float specialn_gk_spew_flame_velocity;
  float specialn_gk_flame_scale;
  float specialn_gk_lowest_charge_graphic_size;
  u32 specialn_gk_screen_shake_frequency;
  float specialn_gk_breath_x_offset;
  float specialn_gk_breath_y_offset;
  float specialn_ss_charge_time;
  float specialn_ss_aerial_shot_recoil;
  u32 specialn_ss_frames_per_charge_level;
  float specialn_ss_freefall_toggle;
  float specialn_pe_friction;
  float specialn_pe_air_horizontal_momentum_preservation;
  float specialn_pe_air_initial_vertical_momentum;
  float specialn_pe_fall_acceleration;
  float specialn_pe_unk2;
  float specialn_pe_unk3;
  int specialn_dk_swings_to_full_charge;
  u32 specialn_dk_damage_increase_per_swing;
  float specialn_dk_grounded_punch_horizontal_velocity;
  float specialn_dk_freefall_toggle;
  int specialn_ns_frames_to_loop_charge_ground;
  int specialn_ns_frames_to_loop_charge_air;
  int specialn_ns_falling_acceleration_delay;
  int specialn_ns_charge_release_delay;
  float specialn_ns_unk1;
  float specialn_ns_gravity;
  float specialn_ns_unk2;
  float specialn_ns_freefall_toggle;
  float specialn_pk_ground_spawn_offset_x;
  float specialn_pk_ground_spawn_offset_y;
  float specialn_pk_air_spawn_offset_x;
  float specialn_pk_air_spawn_offset_y;
  float specialn_pk_freefall_toggle;
  u32 specialn_pk_grounded_item_id;
  u32 specialn_pk_air_item_id;
  float specialn_pc_ground_spawn_offset_x;
  float specialn_pc_ground_spawn_offset_y;
  float specialn_pc_air_spawn_offset_x;
  float specialn_pc_air_spawn_offset_y;
  float specialn_pc_freefall_toggle;
  u32 specialn_pc_grounded_item_id;
  u32 specialn_pc_air_item_id;
  float specialn_ca_x_axis_range;
  float specialn_ca_y_axis_range;
  float specialn_ca_angle_difference;
  float specialn_ca_forward_momentum;
  float specialn_ca_additional_vertical_momentum;
  float specialn_gn_x_axis_range;
  float specialn_gn_y_axis_range;
  float specialn_gn_angle_difference;
  float specialn_gn_forward_momentum;
  float specialn_gn_additional_vertical_momentum;
  float specialn_fx_unk1;
  float specialn_fx_unk2;
  float specialn_fx_unk3;
  float specialn_fx_unk4;
  float specialn_fx_launch_angle;
  float specialn_fx_launch_speed;
  float specialn_fx_freefall_toggle;
  u32 specialn_fx_blaster_projectile_id;
  u32 specialn_fx_blaster_item_id;
  float specialn_fc_unk1;
  float specialn_fc_unk2;
  float specialn_fc_unk3;
  float specialn_fc_unk4;
  float specialn_fc_launch_angle;
  float specialn_fc_launch_speed;
  float specialn_fc_freefall_toggle;
  u32 specialn_fc_blaster_projectile_id;
  u32 specialn_fc_blaster_item_id;
  float specialn_lk_max_charge;
  float specialn_lk_arrow_charge_speed;
  float specialn_lk_freefall_toggle;
  u32 specialn_lk_bow_item_loader_id;
  u32 specialn_lk_bow_item_id;
  float specialn_cl_max_charge;
  float specialn_cl_arrow_charge_speed;
  float specialn_cl_freefall_toggle;
  u32 specialn_cl_bow_item_loader_id;
  u32 specialn_cl_bow_item_id;
  float specialn_sk_graphic_x_offset_ground;
  float specialn_sk_graphic_y_offset_ground;
  float specialn_sk_graphic_x_offset_air;
  float specialn_sk_graphic_y_offset_air;
  float specialn_sk_freefall_toggle;
  float specialn_zd_unk1;
  u32 specialn_zd_frames_before_gravity;
  float specialn_zd_horizontal_momentum_preservation;
  float specialn_zd_fall_acceleration;
  u32 specialn_pr_duration;
  u32 specialn_pr_unk;
  float specialn_pr_air_height_offset_at_start;
  float specialn_pr_bounciness;
  float specialn_pr_unk1;
  float specialn_pr_gravity_during_roll;
  float specialn_pr_base_speed;
  float specialn_pr_max_speed;
  float specialn_pr_unk2;
  float specialn_pr_air_x_axis_momentum;
  float specialn_pr_air_y_axis_momentum;
  float specialn_pr_air_initial_momentum;
  float specialn_pr_max_momentum;
  float specialn_pr_spinning_speed;
  float specialn_pr_spinning_speed_turn;
  u32 specialn_pr_delay_per_smoke;
  float specialn_pr_unk3;
  float specialn_pr_bounce1;
  float specialn_pr_bounce2;
  float specialn_pr_base_damage;
  float specialn_pr_damage_multiplier;
  float specialn_pr_horizontal_bounce_momentum_on_hit;
  float specialn_pr_vertical_bounce_momentum_on_hit;
  float specialn_pr_forward_momentum_from_stick;
  float specialn_pr_unk4;
  float specialn_pr_unk5;
  u32 specialn_pr_unk6;
  float specialn_pr_charge_rate1;
  float specialn_pr_charge_time;
  float specialn_pr_charge_rate2;
  float specialn_pr_charge_spin_animation;
  float specialn_pr_unk7;
  float specialn_pr_unk8;
  float specialn_pr_some_speed_var;
  float specialn_pr_spin_anim_speed_after_collision;
  float specialn_pr_air_speed;
  float specialn_pr_turn_rate_related;
  float specialn_pr_unk9;
  float specialn_pr_unk10;
  float specialn_pr_unk11;
  float specialn_pr_unk12;
  float specialn_pr_freefall_toggle;
  struct ftKb_SpecialNMs_DatAttrs ms;
  struct ftKb_SpecialNMs_DatAttrs fe;
  float specialn_mt_charge_time;
  float specialn_mt_ground_horizontal_momentum;
  float specialn_mt_air_horizontal_momentum;
  u32 specialn_mt_loops_to_full_charge;
  float specialn_mt_frames_to_transition;
  float specialn_mt_freefall_toggle;
  float specialn_pp_air_vertical_momentum;
  float specialn_pp_landing_lag;
  float specialn_pp_x_spawn;
  float specialn_pp_y_spawn;
  float specialn_ys_initial_horizontal_momentum;
  float specialn_ys_initial_vertical_momentum;
  float specialn_ys_damage_multiplier;
  float specialn_ys_unk;
  float specialn_ys_growth_time;
  float specialn_ys_base_duration;
  float specialn_ys_egg_breakout_resistance;
  float specialn_ys_frames_reduced_per_input;
  float specialn_ys_unk1;
  float specialn_ys_unk2;
  u32 specialn_ys_iframes_on_release;
  float specialn_ys_horizontal_velocity_on_breakout;
  float specialn_ys_vertical_velocity_on_breakout;
  float specialn_ys_unk3;
  float specialn_gw_frame_on_repeat;
  float specialn_gw_max_sausages_per_use;
  AbsorbDesc specialn_pe_absorbdesc;
  ReflectDesc specialn_zd_reflectdesc;
};
union ftKb_MotionVars
{
  struct ftGameWatch_SpecialNVars specialn_gw;
  struct ftMars_SpecialNVars specialn_ms;
  struct ftNess_SpecialNVars specialn_ns;
  struct ftKb_SpecialNPe_Vars
  {
    int facing_dir;
  } specialn_pe;
  struct ftKb_SpecialHiVars
  {
    int x0;
    int x4;
    int x8;
    int xC;
    int x10;
    int x14;
    Vec3 x18;
    char pad1[0x60];
    float xC4;
  } specialhi;
  struct ftKb_SpecialLWVars
  {
    s16 x0;
    s16 x2;
    s16 x4;
    s16 x6;
    int x8;
    int xC;
    int x10;
    int x14;
    Vec3 x18;
    Vec3 x24;
    Vec3 x30;
    Vec3 x3C;
    Vec3 x48;
    Vec3 x54;
    Vec3 x60;
    Vec3 x6C;
    Vec3 x78;
    float x84;
    float x88[9];
  } speciallw;
};
struct ftKoopa_FighterVars
{
  float x222C;
  float x2230;
};
union ftKoopa_MotionVars
{
  struct ftKoopa_State1Vars
  {
    void *x0;
    bool x4;
    void *x8;
    bool xC;
  } unk1;
  struct ftKoopa_SpecialSVars
  {
    bool b_held;
    bool x4;
    int facing_dir;
    bool xC;
    s32 x10;
    s32 x14;
    s32 x18;
  } specials;
};
typedef struct _ftKoopaAttributes
{
  float x0;
  s32 x4;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  float x1C;
  s32 x20;
  float x24;
  float x28;
  u32 x2C;
  float x30;
  float x34;
  float x38;
  float x3C;
  float x40;
  float x44;
  float x48;
  float x4C;
  u32 unk50;
  float x54;
  float x58;
  float x5C;
  float x60;
  float x64;
  float x68;
  float x6C;
  float x70;
  float x74;
  float x78;
  float x7C;
  float x80;
  float x84;
  float x88;
  float x8C;
  float x90;
  float x94;
  float x98;
  float x9C;
} ftKoopaAttributes;
typedef struct _ftKoopaVars
{
  float x0;
  float x4;
} ftKoopaVars;
typedef struct ftLk_DatAttrs ftLk_DatAttrs;
typedef struct ftLk_FighterVars ftLk_FighterVars;
typedef union ftLk_MotionVars ftLk_MotionVars;
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
typedef enum ftLink_MotionState
{
  ftLk_MS_AttackS42 = ftCo_MS_Count,
  ftLk_MS_AppealSR,
  ftLk_MS_AppealSL,
  ftLk_MS_SpecialNStart,
  ftLk_MS_SpecialNLoop,
  ftLk_MS_SpecialNEnd,
  ftLk_MS_SpecialAirNStart,
  ftLk_MS_SpecialAirNLoop,
  ftLk_MS_SpecialAirNEnd,
  ftLk_MS_SpecialS1,
  ftLk_MS_SpecialS2,
  ftLk_MS_SpecialS1Empty,
  ftLk_MS_SpecialAirS1,
  ftLk_MS_SpecialAirS2,
  ftLk_MS_SpecialAirS1Empty,
  ftLk_MS_SpecialHi,
  ftLk_MS_SpecialAirHi,
  ftLk_MS_SpecialLw,
  ftLk_MS_SpecialAirLw,
  ftLk_MS_AirCatch,
  ftLk_MS_AirCatchHit,
  ftLk_MS_Count,
  ftLk_MS_SelfCount = ftLk_MS_Count - ftCo_MS_Count
} ftLink_MotionState;
typedef enum ftLk_SpecialNIndex
{
  ftLk_SpecialNIndex_Start,
  ftLk_SpecialNIndex_Loop,
  ftLk_SpecialNIndex_End,
  ftLk_SpecialNIndex_AirStart,
  ftLk_SpecialNIndex_AirLoop,
  ftLk_SpecialNIndex_AirEnd,
  ftLk_SpecialNIndex_None
} ftLk_SpecialNIndex;
typedef enum ftLk_Submotion
{
  ftLk_SM_AttackS42 = ftCo_SM_Count,
  ftLk_SM_SpecialNStart,
  ftLk_SM_SpecialNLoop,
  ftLk_SM_SpecialNEnd,
  ftLk_SM_SpecialAirNStart,
  ftLk_SM_SpecialAirNLoop,
  ftLk_SM_SpecialAirNEnd,
  ftLk_SM_SpecialS1,
  ftLk_SM_SpecialS2,
  ftLk_SM_SpecialS1Empty,
  ftLk_SM_SpecialAirS1,
  ftLk_SM_SpecialAirS2,
  ftLk_SM_SpecialAirS1Empty,
  ftLk_SM_SpecialHi,
  ftLk_SM_SpecialAirHi,
  ftLk_SM_SpecialLw,
  ftLk_SM_SpecialAirLw,
  ftLk_SM_AirCatch,
  ftLk_SM_AirCatchHit,
  ftLk_SM_Count,
  ftLk_SM_SelfCount = ftLk_SM_Count - ftCo_SM_Count
} ftLk_Submotion;
struct ftLk_DatAttrs
{
  float x0;
  float specialn_anim_rate;
  float x8;
  int xC;
  int x10;
  float x14;
  float x18;
  float x1C;
  float x20;
  float x24;
  float specialhi_pos_y_offset;
  int x2C;
  float x30;
  float x34;
  float specialairhi_drift_stick_mul;
  float specialairhi_drift_max_mul;
  float x40;
  float specialhi_grav_mul;
  int x48;
  float attackairlw_hit_vel_y;
  float attackairlw_hit_anim_frame_start;
  float attackairlw_hit_anim_frame_end;
  u32 attackairlw_anim_flags[3];
  struct SwordAttrs x64;
  void *x84;
  s32 x88;
  void *x8C;
  void *x90;
  void *x94;
  s32 x98;
  void *x9C;
  void *xA0;
  int xA4;
  s32 xA8;
  int xAC;
  int xB0;
  float xB4;
  int xB8;
  int xBC;
  u8 xC0_filler[0xC4 - 0xC0];
  AbsorbDesc xC4;
  float xD8;
};
struct ftLk_FighterVars
{
  bool used_boomerang;
  bool x4;
  Item_GObj *boomerang_gobj;
  Item_GObj *xC;
  Item_GObj *arrow_gobj;
  Item_GObj *x14;
  Item_GObj *x18;
  u32 x1C;
};
union ftLk_MotionVars
{
  struct ftLk_AttackAirVars
  {
    float lw_frame_start;
  } attackair;
  struct ftLk_SpecialNVars
  {
    Vec2 x0;
    Vec3 x8;
    float x14;
    int unk_timer;
  } specialn;
};
struct ftLk_SpecialN_Vec3Group
{
  Vec3 a;
  Vec3 b;
  Vec3 c;
};
struct ftLuigi_FighterVars
{
  bool x222C_cycloneCharge;
  u32 x2230;
  u32 x2234;
  u8 _[0xF8 - 0xC];
};
typedef struct _ftLuigiAttributes
{
  float x0_LUIGI_GREENMISSILE_UNK1;
  float x4_LUIGI_GREENMISSILE_SMASH;
  float x8_LUIGI_GREENMISSILE_CHARGE_RATE;
  float xC_LUIGI_GREENMISSILE_MAX_CHARGE_FRAMES;
  float x10_LUIGI_GREENMISSILE_DAMAGE_TILT;
  float x14_LUIGI_GREENMISSILE_DAMAGE_SLOPE;
  float x18_LUIGI_GREENMISSILE_TRACTION;
  float x1C_LUIGI_GREENMISSILE_UNK2;
  float x20_LUIGI_GREENMISSILE_FALLING_SPEED;
  float x24_LUIGI_GREENMISSILE_VEL_X;
  float x28_LUIGI_GREENMISSILE_MUL_X;
  float x2C_LUIGI_GREENMISSILE_VEL_Y;
  float x30_LUIGI_GREENMISSILE_MUL_Y;
  float x34_LUIGI_GREENMISSILE_GRAVITY_START;
  float x38_LUIGI_GREENMISSILE_FRICTION_END;
  float x3C_LUIGI_GREENMISSILE_X_DECEL;
  float x40_LUIGI_GREENMISSILE_GRAVITY_MUL;
  float x44_LUIGI_GREENMISSILE_MISFIRE_CHANCE;
  float x48_LUIGI_GREENMISSILE_MISFIRE_VEL_X;
  float x4C_LUIGI_GREENMISSILE_MISFIRE_VEL_Y;
  float x50_LUIGI_SUPERJUMP_FREEFALL_MOBILITY;
  float x54_LUIGI_SUPERJUMP_LANDING_LAG;
  float x58_LUIGI_SUPERJUMP_REVERSE_STICK_RANGE;
  float x5C_LUIGI_SUPERJUMP_MOMENTUM_STICK_RANGE;
  float x60_LUIGI_SUPERJUMP_ANGLE_DIFF;
  float x64_LUIGI_SUPERJUMP_VEL_X;
  float x68_LUIGI_SUPERJUMP_GRAVITY_START;
  float x6C_LUIGI_SUPERJUMP_VEL_Y;
  float x70_LUIGI_CYCLONE_TAP_MOMENTUM;
  float x74_LUIGI_CYCLONE_MOMENTUM_X_GROUND;
  float x78_LUIGI_CYCLONE_MOMENTUM_X_AIR;
  float x7C_LUIGI_CYCLONE_MOMENTUM_X_MUL_GROUND;
  float x80_LUIGI_CYCLONE_MOMENTUM_X_MUL_AIR;
  float x84_LUIGI_CYCLONE_FRICTION_END;
  s32 x88_LUIGI_CYCLONE_UNK;
  float x8C_LUIGI_CYCLONE_TAP_Y_VEL_MAX;
  float x90_LUIGI_CYCLONE_TAP_GRAVITY;
  s32 x94_LUIGI_CYCLONE_LANDING_LAG;
} ftLuigiAttributes;
typedef struct ftLuigiSpecialS
{
  s32 chargeFrames;
  bool isMisfire;
} ftLuigiSpecialS;
typedef struct ftLuigiSpecialLw
{
  float groundVelX;
  s32 unk;
  s32 _;
  bool isUnkColl;
} ftLuigiSpecialLw;
typedef union ftLuigi_MotionVars
{
  ftLuigiSpecialS SpecialS;
  ftLuigiSpecialLw SpecialLw;
} ftLuigi_MotionVars;
static const MotionFlags ftMr_MF_Special = ((Ft_MF_SkipModel | Ft_MF_SkipItemVis) | Ft_MF_UnkUpdatePhys) | Ft_MF_FreezeState;
static const MotionFlags ftMr_MF_SpecialN = (ftMr_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_SkipThrowException;
static const MotionFlags ftMr_MF_SpecialHi = ((ftMr_MF_Special | Ft_MF_KeepFastFall) | Ft_MF_KeepGfx) | Ft_MF_KeepSfx;
static const MotionFlags ftMr_MF_SpecialLw = (ftMr_MF_Special | Ft_MF_KeepColAnimHitStatus) | Ft_MF_KeepSfx;
static const MotionFlags ftMr_MF_SpecialAirN = ftMr_MF_SpecialN | Ft_MF_SkipParasol;
static const MotionFlags ftMr_MF_SpecialAirHi = ftMr_MF_SpecialHi | Ft_MF_SkipParasol;
static const MotionFlags ftMr_MF_SpecialAirLw = ftMr_MF_SpecialLw | Ft_MF_SkipParasol;
static const MotionFlags ftMr_MF_SpecialS = ((ftMr_MF_Special | Ft_MF_KeepGfx) | Ft_MF_SkipModel) | Ft_MF_SkipColAnim;
typedef enum ftMario_MotionState
{
  ftMr_MS_AppealSR = ftCo_MS_Count,
  ftMr_MS_AppealSL,
  ftMr_MS_SpecialN,
  ftMr_MS_SpecialAirN,
  ftMr_MS_SpecialS,
  ftMr_MS_SpecialAirS,
  ftMr_MS_SpecialHi,
  ftMr_MS_SpecialAirHi,
  ftMr_MS_SpecialLw,
  ftMr_MS_SpecialAirLw,
  ftMr_MS_Count,
  ftMr_MS_SelfCount = ftMr_MS_Count - ftCo_MS_Count
} ftMario_MotionState;
typedef enum ftMr_Submotion
{
  ftMr_SM_SpecialN = ftCo_SM_Count,
  ftMr_SM_SpecialAirN,
  ftMr_SM_SpecialS,
  ftMr_SM_SpecialAirS,
  ftMr_SM_SpecialHi,
  ftMr_SM_SpecialAirHi,
  ftMr_SM_SpecialLw,
  ftMr_SM_SpecialAirLw,
  ftMr_SM_Count,
  ftMr_SM_SelfCount = ftMr_SM_Count - ftCo_SM_Count
} ftMr_Submotion;
struct ftMario_FighterVars
{
  int x222C_vitaminCurr;
  int x2230_vitaminPrev;
  bool x2234_tornadoCharge;
  bool x2238_isCapeBoost;
  HSD_GObj *x223C_capeGObj;
  u32 x2240;
  u8 _[0xF8 - 0x18];
};
typedef struct ftMario_DatAttrs
{
  struct ftMario_SpecialS_DatAttrs
  {
    float vel_x_decay;
    Vec2 vel;
    float grav;
    float terminal_vel;
    ItemKind cape_kind;
  } specials;
  struct ftMario_SpecialHi_DatAttrs
  {
    float freefall_mobility;
    float landing_lag;
    float reverse_stick_range;
    float momentum_stick_range;
    float angle_diff;
    float vel_x;
    float grav;
    float vel_mul;
  } specialhi;
  struct ftMario_SpecialLw_DatAttrs
  {
    float vel_y;
    float momentum_x;
    float air_momentum_x;
    float momentum_x_mul;
    float air_momentum_x_mul;
    float friction_end;
    s32 unk0;
    float tap_y_vel_max;
    float tap_grav;
    s32 landing_lag;
  } speciallw;
  ReflectDesc cape_reflection;
} ftMario_DatAttrs;
typedef struct ftMario_SpecialLw_ECB
{
  u8 x0_str_arr[3];
  u8 x3_balign;
  u32 x4;
  u32 x8;
  u32 xC;
  u32 x10;
  u32 x14;
} ftMario_SpecialLw_ECB;
typedef struct ftMarioSpecialS
{
  bool reflecting;
} ftMarioSpecialS;
typedef struct ftMarioSpecialLw
{
  float groundVelX;
  s32 unk;
  s32 _;
  bool isUnkColl;
} ftMarioSpecialLw;
typedef union ftMario_MotionVars
{
  ftMarioSpecialS SpecialS;
  ftMarioSpecialLw SpecialLw;
} ftMario_MotionVars;
typedef struct ftMasterHand_SpecialAttrs ftMasterHand_SpecialAttrs;
typedef enum ftMasterHand_UnkEnum0
{
  ftMh_UnkEnum0_Unk00,
  ftMh_UnkEnum0_Unk01,
  ftMh_UnkEnum0_Unk02,
  ftMh_UnkEnum0_Unk03,
  ftMh_UnkEnum0_Unk04,
  ftMh_UnkEnum0_Unk05,
  ftMh_UnkEnum0_Unk06,
  ftMh_UnkEnum0_Unk07,
  ftMh_UnkEnum0_Unk08,
  ftMh_UnkEnum0_Unk09,
  ftMh_UnkEnum0_Unk10
} ftMasterHand_UnkEnum0;
typedef enum ftMasterhand_MotionState
{
  ftMh_MS_Wait1_0 = ftCo_MS_Count,
  ftMh_MS_Wait2_0,
  ftMh_MS_Entry,
  ftMh_MS_Damage,
  ftMh_MS_Damage2,
  ftMh_MS_WaitSweep,
  ftMh_MS_SweepLoop,
  ftMh_MS_SweepWait,
  ftMh_MS_Slap,
  ftMh_MS_Walk2,
  ftMh_MS_WalkLoop,
  ftMh_MS_WalkWait,
  ftMh_MS_WalkShoot,
  ftMh_MS_Drill,
  ftMh_MS_RockCrushUp,
  ftMh_MS_RockCrushWait,
  ftMh_MS_RockCrushDown,
  ftMh_MS_PaperCrush,
  ftMh_MS_Poke1,
  ftMh_MS_Poke2,
  ftMh_MS_FingerBeamStart,
  ftMh_MS_FingerBeamLoop,
  ftMh_MS_FingerBeamEnd,
  ftMh_MS_FingerGun1,
  ftMh_MS_FingerGun2,
  ftMh_MS_FingerGun3,
  ftMh_MS_BackAirplane1,
  ftMh_MS_BackAirplane2,
  ftMh_MS_BackAirplane3,
  ftMh_MS_BackPunch,
  ftMh_MS_BackCrush,
  ftMh_MS_BackDisappear,
  ftMh_MS_Wait1_1,
  ftMh_MS_Grab,
  ftMh_MS_Cancel,
  ftMh_MS_Squeezing0,
  ftMh_MS_Squeezing1,
  ftMh_MS_Squeeze,
  ftMh_MS_Throw,
  ftMh_MS_Slam,
  ftMh_MS_Fail,
  ftMh_MS_TagCrush,
  ftMh_MS_TagApplaud,
  ftMh_MS_TagRockPaper,
  ftMh_MS_TagGrab,
  ftMh_MS_TagSqueeze,
  ftMh_MS_TagFail,
  ftMh_MS_TagCancel,
  ftMh_MS_Wait1_2,
  ftMh_MS_Wait2_1,
  ftMh_MS_Count,
  ftMh_MS_SelfCount = ftMh_MS_Count - ftCo_MS_Count
} ftMasterhand_MotionState;
typedef enum ftMh_Submotion
{
  ftMh_SM_Wait1_0 = ftCo_SM_Count,
  ftMh_SM_Wait2_0,
  ftMh_SM_Entry,
  ftMh_SM_Damage,
  ftMh_SM_Damage2,
  ftMh_SM_WaitSweep,
  ftMh_SM_SweepLoop,
  ftMh_SM_SweepWait,
  ftMh_SM_Slap,
  ftMh_SM_Walk2,
  ftMh_SM_WalkLoop,
  ftMh_SM_WalkWait,
  ftMh_SM_WalkShoot,
  ftMh_SM_Drill,
  ftMh_SM_RockCrushUp,
  ftMh_SM_RockCrushWait,
  ftMh_SM_RockCrushDown,
  ftMh_SM_PaperCrush,
  ftMh_SM_Poke1,
  ftMh_SM_Poke2,
  ftMh_SM_FingerBeamStart,
  ftMh_SM_FingerBeamLoop,
  ftMh_SM_FingerBeamEnd,
  ftMh_SM_FingerGun1,
  ftMh_SM_FingerGun2,
  ftMh_SM_FingerGun3,
  ftMh_SM_BackAirplane1,
  ftMh_SM_BackAirplane2,
  ftMh_SM_BackAirplane3,
  ftMh_SM_BackPunch,
  ftMh_SM_BackCrush,
  ftMh_SM_BackDisappear,
  ftMh_SM_Wait1_1,
  ftMh_SM_Grab,
  ftMh_SM_Cancel,
  ftMh_SM_Squeezing0,
  ftMh_SM_Squeezing1,
  ftMh_SM_Squeeze,
  ftMh_SM_Throw,
  ftMh_SM_Slam,
  ftMh_SM_Fail,
  ftMh_SM_TagCrush,
  ftMh_SM_TagApplaud,
  ftMh_SM_TagRockPaper,
  ftMh_SM_TagGrab,
  ftMh_SM_TagSqueeze,
  ftMh_SM_TagFail,
  ftMh_SM_TagCancel,
  ftMh_SM_Wait1_2,
  ftMh_SM_Wait2_1,
  ftMh_SM_Count,
  ftMh_SM_SelfCount = ftMh_SM_Count - ftCo_SM_Count
} ftMh_Submotion;
struct ftMasterhand_FighterVars
{
  HSD_GObj *x222C;
  u32 x2230;
  u32 x2234;
  float x2238;
  float x223C;
  Vec3 x2240_pos;
  u32 x224C;
  s32 x2250;
  s32 x2254;
  s32 x2258;
};
struct ftMasterHand_SpecialAttrs
{
  s32 x0;
  s32 x4;
  s32 x8;
  s32 xC;
  s32 x10;
  s32 x14;
  s32 x18;
  s32 x1C;
  s32 x20;
  s32 x24;
  float x28;
  float x2C;
  Vec2 x30_pos2;
  float x38;
  float x3C;
  Vec3 x40_pos;
  float x4C;
  Vec2 x50;
  float x58;
  float x5C;
  float x60;
  float x64;
  float x68;
  s32 x6C;
  s32 x70;
  s32 x74;
  float x78;
  s32 x7C;
  float x80;
  s32 x84;
  Vec2 x88_pos;
  s32 x90;
  s32 x94;
  float x98;
  float x9C;
  s32 xA0;
  float xA4;
  Vec2 xA8_pos;
  s32 xB0;
  s32 xB4;
  float xB8;
  Vec2 xBC_pos;
  Vec2 xC4_pos;
  Vec2 xCC_pos;
  float xD4;
  float xD8;
  float xDC;
  float xE0;
  float xE4;
  float xE8;
  s32 xEC;
  s32 xF0;
  float xF4;
  float xF8;
  float xFC;
  float x100;
  float x104;
  float x108;
  float x10C;
  Vec2 x110_pos;
  Vec2 x118_pos;
  float x120;
  Vec2 x124_pos;
  Vec2 x12C_pos;
  Vec2 x134_pos;
  Vec2 x13C_pos;
  s32 x144;
  s32 x148;
  float x14C;
  float x150;
  float x154;
  float x158;
  float x15C;
  s32 x160;
  s32 x164;
  s32 x168;
  s32 x16C;
  s32 x170;
  s32 x174;
  float x178;
};
union ftMasterHand_MotionVars
{
  struct ftMasterHand_Unk0Vars
  {
    float x0;
    HSD_GObjEvent x4;
    int x8;
    Vec3 xC;
    float x18;
    float x1C;
    int x20;
    float x24;
    int x28;
    int x2C;
    int x30;
    int x34;
    int x38;
    int x3C;
    int x40;
    int x44;
    int x48;
    int x4C;
    float x50;
    int x54;
    Vec3 x58;
    Vec3 x64;
    int x70;
    int x74;
    int x78;
  } unk0;
  struct ftMasterHand_Unk4Vars
  {
    ftMasterHand_UnkEnum0 x0;
    int x4;
    int x8;
  } unk4;
  struct ftMasterHand_Unk13Vars
  {
    float x0;
    float x4;
  } unk13;
  struct ftMasterHand_FingerBeamVars
  {
    char pad_0[0x34];
    Item_GObj *x34;
    Item_GObj *x38;
    Item_GObj *x3C;
    Item_GObj *x40;
  } fingerbeam;
  struct ftMasterHand_Damage_0
  {
    char pad_0[0x28];
    int x28;
    int x2C;
    int x30;
    Item_GObj *x34;
    Item_GObj *x38;
    Item_GObj *x3C;
    Item_GObj *x40;
  } dmg0;
};
struct ftMewtwo_FighterVars
{
  HSD_GObj *x222C_disableGObj;
  HSD_GObj *x2230_shadowHeldGObj;
  s32 x2234_shadowBallCharge;
  HSD_GObj *x2238_shadowBallGObj;
  bool x223C_isConfusionBoost;
};
typedef struct ftMewtwoSpecialHi
{
  s32 travelFrames;
  float stickX;
  float stickY;
  s32 unk4;
  float velX;
  float velY;
  float groundVelX;
} ftMewtwoSpecialHi;
typedef struct ftMewtwoSpecialS
{
  u8 isConfusionReflect : 1;
} ftMewtwoSpecialS;
typedef struct ftMewtwoSpecialN
{
  bool isFull;
  s32 x2344;
  bool x2348;
  s32 releaseLag;
  float chargeLevel;
} ftMewtwoSpecialN;
typedef union ftMewtwo_MotionVars
{
  ftMewtwoSpecialN SpecialN;
  ftMewtwoSpecialS SpecialS;
  ftMewtwoSpecialHi SpecialHi;
} ftMewtwo_MotionVars;
typedef struct _ftMewtwoAttributes
{
  float x0_MEWTWO_SHADOWBALL_CHARGE_CYCLES;
  float x4_MEWTWO_SHADOWBALL_GROUND_RECOIL_X;
  float x8_MEWTWO_SHADOWBALL_AIR_RECOIL_X;
  s32 xC_MEWTWO_SHADOWBALL_CHARGE_ITERATIONS;
  s32 x10_MEWTWO_SHADOWBALL_RELEASE_LAG;
  float x14_MEWTWO_SHADOWBALL_LANDING_LAG;
  float x18_MEWTWO_CONFUSION_AIR_BOOST;
  ReflectDesc x1C_MEWTWO_CONFUSION_REFLECTION;
  float x40_MEWTWO_TELEPORT_VEL_DIV_X;
  float x44_MEWTWO_TELEPORT_VEL_DIV_Y;
  float x48_MEWTWO_TELEPORT_GRAVITY;
  float x4C_MEWTWO_TELEPORT_TERMINAL_VELOCITY;
  s32 x50_MEWTWO_TELEPORT_DURATION;
  float x54_MEWTWO_TELEPORT_UNK2;
  float x58_MEWTWO_TELEPORT_STICK_RANGE_MIN;
  float x5C_MEWTWO_TELEPORT_MOMENTUM;
  float x60_MEWTWO_TELEPORT_MOMENTUM_ADD;
  float x64_MEWTWO_TELEPORT_DRIFT;
  s32 x68_MEWTWO_TELEPORT_ANGLE_CLAMP;
  float x6C_MEWTWO_TELEPORT_MOMENTUM_END_MUL;
  float x70_MEWTWO_TELEPORT_FREEFALL_MOBILITY;
  float x74_MEWTWO_TELEPORT_LANDING_LAG;
  float x78_MEWTWO_DISABLE_GRAVITY;
  float x7C_MEWTWO_DISABLE_TERMINAL_VELOCITY;
  float x80_MEWTWO_DISABLE_OFFSET_X;
  float x84_MEWTWO_DISABLE_OFFSET_Y;
} ftMewtwoAttributes;
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
typedef enum ftPeach_MotionState
{
  ftPe_MS_Float = ftCo_MS_Count,
  ftPe_MS_FloatFallF,
  ftPe_MS_FloatFallB,
  ftPe_MS_FloatAttackAirN,
  ftPe_MS_FloatAttackAirF,
  ftPe_MS_FloatAttackAirB,
  ftPe_MS_FloatAttackAirHi,
  ftPe_MS_FloatAttackAirLw,
  ftPe_MS_AttackS4Club,
  ftPe_MS_AttackS4Pan,
  ftPe_MS_AttackS4Racket,
  ftPe_MS_SpecialLw,
  ftPe_MS_SpecialAirLw,
  ftPe_MS_SpecialSStart,
  ftPe_MS_SpecialSEnd,
  ftPe_MS_SpecialSJump,
  ftPe_MS_SpecialAirSStart,
  ftPe_MS_SpecialAirSEnd_0,
  ftPe_MS_SpecialAirSEnd_1,
  ftPe_MS_SpecialAirSJump,
  ftPe_MS_SpecialHiStart,
  ftPe_MS_SpecialHiEnd,
  ftPe_MS_SpecialAirHiStart,
  ftPe_MS_SpecialAirHiEnd,
  ftPe_MS_SpecialN,
  ftPe_MS_SpecialNHit,
  ftPe_MS_SpecialAirN,
  ftPe_MS_SpecialAirNHit,
  ftPe_MS_ItemParasolOpen,
  ftPe_MS_ItemParasolFall,
  ftPe_MS_Count,
  ftPe_MS_SelfCount = ftPe_MS_Count - ftCo_MS_Count
} ftPeach_MotionState;
typedef enum ftPe_Submotion
{
  ftPe_SM_Float = ftCo_SM_Count,
  ftPe_SM_FloatFallF,
  ftPe_SM_FloatFallB,
  ftPe_SM_AttackS4_0,
  ftPe_SM_AttackS4_1,
  ftPe_SM_AttackS4_2,
  ftPe_SM_SpecialLw,
  ftPe_SM_SpecialSStart,
  ftPe_SM_SpecialSEnd,
  ftPe_SM_SpecialSJump,
  ftPe_SM_SpecialAirSStart,
  ftPe_SM_SpecialAirSEnd_0,
  ftPe_SM_SpecialAirSEnd_1,
  ftPe_SM_SpecialHiStart,
  ftPe_SM_SpecialHiEnd,
  ftPe_SM_SpecialAirHiStart,
  ftPe_SM_SpecialAirHiEnd,
  ftPe_SM_SpecialN,
  ftPe_SM_SpecialNHit,
  ftPe_SM_SpecialAirN,
  ftPe_SM_SpecialAirNHit,
  ftPe_SM_ItemParasolOpen,
  ftPe_SM_ItemParasolFall,
  ftPe_SM_Count,
  ftPe_SM_SelfCount = ftPe_SM_Count - ftCo_SM_Count
} ftPe_Submotion;
struct ftPeach_FighterVars
{
  bool has_float;
  float x4;
  FtMotionId attacks4_motion_id;
  Item_GObj *parasol_gobj_0;
  Item_GObj *parasol_gobj_1;
  bool specialairn_used;
  Item_GObj *toad_gobj;
  Item_GObj *veg_gobj;
};
typedef struct ftPe_DatAttrs
{
  float floatfallf_anim_start;
  float floatfallb_anim_start;
  float floatfall_anim_start_offset;
  float xC;
  int speciallw_item_table_count;
  int x14;
  struct ftPe_ItemChance
  {
    int randi_max;
    ItemKind kind;
  } speciallw_item_table[3];
  int x30;
  float x34;
  float specials_start_accel;
  float specials_start_vel_x;
  float x40;
  float specials_vel_x;
  float specials_smash_vel_x;
  float specials_vel_y;
  float x50_gravity;
  float x54;
  float x58_gravity;
  float x5C_terminal_vel;
  float specials_end_vel_x;
  float specials_end_vel_y;
  float x68;
  float x6C;
  float x70;
  float x74;
  float x78;
  float x7C;
  float x80;
  float x84;
  float x88;
  float x8C;
  int x90;
  float specialairn_vel_x_div;
  float x98;
  float specialairn_vel_y;
  float xA0;
  float xA4;
  float xA8;
  AbsorbDesc xAC;
} ftPe_DatAttrs;
union ftPe_MotionVars
{
  struct ftPe_FloatAttackVars
  {
    bool x0;
  } floatattack;
  struct ftPe_SpecialSVars
  {
    bool x0;
  } specials;
  struct ftPe_SpecialHiVars
  {
    ItemKind kind;
  } specialhi;
  struct ftPe_SpecialNVars
  {
    int facing_dir;
  } specialn;
};
struct ftPikachu_FighterVars
{
  char filler0[0xF8];
};
typedef struct _ftPikachuAttributes
{
  float x0;
  float x4;
  float x8;
  float xC;
  float x10;
  u32 x14;
  u32 x18;
  float x1C;
  float x20;
  float x24;
  float x28;
  float x2C;
  float x30;
  float specials_start_friction;
  float specials_start_gravity;
  float x3C;
  float x40;
  float x44;
  float x48;
  float x4C;
  float x50;
  float x54;
  float x58;
  int x5C;
  s32 x60;
  float x64;
  float x68;
  Vec3 x6C_scale;
  float x78;
  Vec3 x7C_scale;
  float x88;
  float x8C;
  float x90;
  float x94;
  float x98;
  float x9C;
  s32 xA0;
  float xA4;
  s32 xA8;
  float xAC;
  float xB0;
  float xB4;
  float xB8;
  float xBC;
  float xC0;
  float xC4;
  float xC8;
  float xCC;
  float xD0;
  s32 xD4;
  s32 xD8;
  u32 xDC;
  float height_attributes[6];
} ftPikachuAttributes;
union ftPikachu_MotionVars
{
  struct ftPikachu_State2Vars
  {
    s32 x0;
  } unk2;
  struct ftPikachu_State3Vars
  {
    s32 x0;
  } unk3;
  struct ftPikachu_SpecialHiVars
  {
    int x0;
    s32 x4;
    s32 x8;
    int xC;
    Vec2 x10;
    s32 x18;
    Vec2 x1C;
    float x24;
  } specialhi;
  struct ftPikachu_SpecialLwVars
  {
    Item_GObj *x0;
    bool x4;
  } speciallw;
};
struct ftPopo_FighterVars
{
  Item_GObj *x222C;
  u8 x2230_b0 : 1;
  u8 filler_x2231[3];
  u32 x2234;
  Item_GObj *x2238;
  u32 x223C;
  Vec x2240;
  u32 x224C;
  float x2250;
};
typedef struct ftIceClimberAttributes
{
  float x0;
  float x4;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  int x1C;
  float x20;
  float x24;
  float x28;
  float x2C;
  float x30;
  float x34;
  float x38;
  float x3C;
  float x40;
  float x44;
  float x48;
  float x4C_gravity;
  float x50_gravity;
  float x54_terminal_vel;
  float x58_terminal_vel;
  float x5C;
  float x60;
  float x64;
  int x68;
  float x6C;
  float x70;
  u8 _74[0x84 - 0x74];
  float x84;
  u8 _88[0x94 - 0x88];
  float x94;
  float x98;
  u8 _9C[0xB0 - 0x9C];
  float xB0;
  float xB4;
  u8 _B8[0xC4 - 0xB8];
  float xC4;
  float xC8;
  u8 _CC[0xD0 - 0xCC];
  float xD0;
  u8 _D4[0x12C - 0xD4];
  float x12C;
  float x130;
  float x134;
  float x138;
  float x13C;
  float x140;
  float x144;
  float x148;
  float x14C;
  u8 _150[0x15C - 0x150];
} ftIceClimberAttributes;
union ftPp_MotionVars
{
  struct ftPp_SpecialSVars
  {
    float x0;
    int x4;
    struct ftPp_SpecialSVars_x8_t
    {
      int x0;
      HSD_GObj *x4;
    } *x8;
    int xC;
    int x10;
    int x14;
    int x18;
    float x1C;
  } specials;
  struct 
  {
    int x0;
  } unk_80123954;
};
struct ftPurin_FighterVars
{
  u32 x222C;
  Vec3 x2230;
  HSD_JObj *x223C;
  DObjList x2240;
  u32 x2248;
};
typedef union ftPurin_MotionVars
{
  struct ftPurin_SpecialHiVars
  {
    bool x0;
  } specialhi;
  struct ftPurin_SpecialNVars
  {
    int x0;
    void *x4;
    void *x8;
    void *xC;
    u8 _10[0x1C - 0x10];
    float x1C;
    float facing_dir;
    u8 _24[0x34 - 0x24];
    Vec3 x34;
  } specialn;
} ftPurin_MotionVars;
typedef struct _ftPurinAttributes
{
  float x0;
  float x4;
  float x8;
  float xC;
  float x10;
  s32 x14;
  float x18;
  s32 x1C;
  s32 x20;
  s32 x24;
  s32 x28;
  s32 x2C;
  s32 x30;
  s32 x34;
  s32 x38;
  float x3C;
  float x40;
  float x44;
  u8 _48[0x88 - 0x48];
  Vec2 specialn_vel;
  u8 _90[0xDC - 0x90];
  float xDC;
  float xE0;
  float xE4;
  void *xE8;
  void *xEC;
  float xF0;
  float xF4;
  u8 _F8[0x100 - 0xF8];
} ftPurinAttributes;
struct ftSamus_FighterVars
{
  Item_GObj *x222C;
  s32 x2230;
  u32 x2234;
  u32 x2238;
  Item_GObj *x223C;
  u8 x2240;
  u8 x2241;
  u8 x2242;
  u8 x2243;
  u32 x2244;
  u32 x2248;
};
typedef struct _ftSamusAttributes
{
  float x0;
  float x4;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  float x1C;
  int x20;
  float x24;
  float x28;
  float x2C;
  float x30;
  float x34;
  float x38;
  float x3C;
  float x40;
  float x44;
  float x48;
  float x4C;
  float x50;
  float x54;
  float x58;
  float x5C;
  float x60;
  float x64;
  float x68;
  float x6C;
  float x70;
  Vec3 x74_vec;
  float x80;
  ftCollisionBox height_attributes;
  void *x9C;
  void *xA0;
  void *xA4;
  void *xA8;
  void *xAC;
  void *xB0;
  void *xB4;
  void *xB8;
  int xBC;
  int xC0;
  int xC4;
  int xC8;
  void *xCC;
  void *xD0;
} ftSs_DatAttrs;
struct UNK_SAMUS_S1
{
  HSD_Joint *x0_joint;
  HSD_AnimJoint **x4_anim_joints;
  HSD_AnimJoint *x8_anim_joint;
  HSD_MatAnimJoint *xC_matanim_joint;
};
union ftSamus_MotionVars
{
  struct ftSamus_State2Vars
  {
    s32 x0;
  } unk2;
  struct ftSamus_State3Vars
  {
    s32 x0;
    s32 x4;
    float x8;
  } unk3;
  struct ftSamus_State5Vars
  {
    s32 x0;
  } unk5;
  struct ftSamus_State6Vars
  {
    s32 x0;
  } unk6;
};
struct ftSandbag_FighterVars
{
  char filler0[0xF8];
};
struct ftSeak_FighterVars
{
  int x0;
  Item_GObj *x4;
  HSD_GObj *x8;
  Vec3 xC[4];
  Vec3 x3C[4];
  Vec3 lstick_delta;
};
typedef struct _ftSeakAttributes
{
  float x0;
  float x4;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  float x1C;
  float x20;
  float x24;
  float x28;
  float self_vel_y;
  f32 x30;
  f32 x34;
  int x38;
  f32 x3C;
  f32 x40;
  f32 x44;
  f32 x48;
  f32 x4C;
  int x50;
  f32 x54;
  f32 x58;
  f32 x5C;
  f32 x60;
  f32 x64;
  f32 x68;
  f32 x6C;
  f32 x70;
} ftSeakAttributes;
struct itChainSegment
{
  float x00;
  float x04;
  float x08;
  float x0C;
  float x10;
  float x14;
  float x18;
  float x1C;
  float x20;
  float x24;
  float x28;
  float x2C;
  float x30;
  float x34;
  float x38;
  float x3C;
  float x40;
  float x44;
  float x48;
  float x4C;
  float x50;
};
union ftSeak_MotionVars
{
  struct ftSeak_SpecialNVars
  {
    enum_t x0;
    bool x4;
    s32 x8;
    s32 xC;
    s32 x10;
    s32 x14;
    s32 x18;
    s32 x1C;
    s32 x20;
    s32 x24;
    s32 x28;
    s32 x2C;
  } specialn;
  struct ftSeak_SpecialSVars
  {
    s32 x0;
    s32 x4;
    s32 x8;
    s32 xC;
    float x10;
    float x14;
    float x18;
    s32 x1C;
    s32 x20;
    s32 x24;
    s32 x28;
    s32 x2C;
  } specials;
  struct ftSeakSpecialHi
  {
    s32 x0;
    Vec2 vel;
    s32 xC;
    s32 x10;
    s32 x14;
    s32 x18;
    s32 x1C;
    s32 x20;
    s32 x24;
    s32 x28;
    s32 x2C;
  } specialhi;
};
struct ftYoshi_FighterVars
{
  u32 x222C;
  u32 x2230;
  u32 x2234;
  Item_GObj *x2238;
};
typedef struct _ftYoshiAttributes
{
  s32 x0;
  float x4;
  float x8;
  float xC;
  float x10;
  float x14;
  float x18;
  float x1C;
  float x20;
  float x24;
  float x28;
  float x2C;
  float x30;
  float x34;
  int x38;
  Vec2 x3C;
  float x44;
  int x48;
  int x4C;
  u8 pad_x50[0x6C - 0x50];
  float specials_start_gravity;
  float specials_start_terminal_vel;
  u8 pad_x74[0x114 - 0x74];
  float x114;
  float x118;
  float x11C;
  float x120;
  u8 pad_x124[0x138 - 0x124];
} ftYoshiAttributes;
struct ftYs_DatAttrs
{
  char pad_0[0x10];
  Vec2 x10;
  float x18;
  void *x1C;
  void *x20;
  float x24;
  char pad_28[0xEC - 0x28];
  float xEC;
  float xF0;
  float xF4;
  float specialhi_base_angle;
  float xFC;
  float x100;
  char x104[0x118 - 0x104];
  Vec2 speciallw_star_offset;
};
struct S_UNK_YOSHI2
{
  s32 x0;
  s32 x4;
  s32 x8_end_index;
  u8 *xC_start_index;
};
struct S_UNK_YOSHI1
{
  s32 x0;
  struct S_UNK_YOSHI2 *unk_struct;
};
union ftYoshi_MotionVars
{
  struct ftYoshi_SpecialNVars
  {
    u8 x0_b0 : 1;
    u8 x0_b1 : 1;
    u8 x0_b2 : 1;
    u8 x0_b3 : 1;
  } specialn;
  struct ftYoshi_SpecialSVars
  {
    int x0;
    u8 x4[0x30 - 0x4];
    int x30;
  } specials;
  struct ftYoshi_SpecialHiVars
  {
    int x0;
    int x4;
  } specialhi;
  struct ftYoshi_GuardVars
  {
    f32 x0;
    u8 _pad[8];
    bool xC;
    f32 x10;
    f32 x14;
    f32 x18;
    void *x1C;
    int x20;
    int x24;
  } guard;
};
struct ftZakoBoy_FighterVars
{
  char filler0[0xF8];
};
typedef struct _ftZakoboyAttributes
{
  s32 x0;
} ftZakoboyAttributes;
struct ftZelda_FighterVars
{
  HSD_GObj *x222C;
};
typedef struct ftZelda_DatAttrs
{
  float x0;
  s32 x4;
  float x8;
  float xC;
  s32 x10;
  s32 x14;
  s32 x18;
  s32 x1C;
  float x20;
  float x24;
  s32 x28;
  float x2C;
  s32 x30;
  float x34;
  float x38;
  float x3C;
  float x40;
  float x44;
  s32 x48;
  float x4C;
  float x50;
  float x54;
  float x58;
  float x5C;
  s32 x60;
  float x64;
  float x68;
  float x6C;
  float x70;
  float x74;
  float x78;
  float x7C;
  float x80;
  ReflectDesc x84;
} ftZelda_DatAttrs;
union ftZelda_MotionVars
{
  struct ftZelda_SpecialHiVars
  {
    int x0;
    Vec2 x4;
    int xC;
    Vec2 x10;
    float x18;
  } specialhi;
  struct ftZelda_SpecialNVars
  {
    int x0;
  } specialn;
  struct ftZelda_SpecialSVars
  {
    int x0;
    int x4;
    int x8;
    int xC;
  } specials;
};
typedef struct DynamicModelDesc DynamicModelDesc;
typedef struct LightList LightList;
typedef struct SceneDesc SceneDesc;
typedef struct StaticModelDesc StaticModelDesc;
typedef struct StageBlastZone
{
  f32 left;
  f32 right;
  f32 top;
  f32 bottom;
} StageBlastZone;
typedef struct StageCameraInfo
{
  StageBlastZone cam_bounds;
  f32 cam_x_offset;
  f32 cam_y_offset;
  f32 cam_vertical_tilt;
  f32 cam_pan_degrees;
  f32 x20;
  f32 x24;
  f32 cam_track_ratio;
  f32 cam_fixed_zoom;
  f32 cam_track_smooth;
  f32 cam_zoom_rate;
  f32 cam_max_depth;
  f32 x3C;
  f32 pausecam_zpos_min;
  f32 pausecam_zpos_init;
  f32 pausecam_zpos_max;
  f32 cam_angle_up;
  f32 cam_angle_down;
  f32 cam_angle_left;
  f32 cam_angle_right;
  Vec3 fixed_cam_pos;
  f32 fixed_cam_fov;
  f32 fixed_cam_vert_angle;
  f32 fixed_cam_horz_angle;
} StageCameraInfo;
struct StageInfo
{
  StageCameraInfo cam_info;
  StageBlastZone blast_zone;
  u32 flags;
  InternalStageId internal_stage_id;
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
  } unk8C;
  bool (*x90)(Vec3 *, int);
  bool (*x94)(Vec3 *, int);
  s32 x98;
  u32 x9C;
  u8 xA0[4];
  u8 xA4_pad[0x12C - 0xA4];
  HSD_GObj *x12C;
  Vec3 x130;
  Vec3 x13C;
  Vec3 x148;
  Vec3 x154;
  Vec3 x160;
  Vec3 x16C;
  DynamicsDesc *(*x178)(int);
  bool (*x17C)(Vec3 *, int, HSD_JObj *);
  HSD_GObj *x180[4];
  u8 x190_pad[0x280 - 0x190];
  HSD_JObj *x280[261];
  void *x694[4];
  void *x6A4;
  struct 
  {
    s32 unk0;
    Article *unk4;
  } **itemdata;
  MapCollData *coll_data;
  UnkStage6B0 *param;
  void ***ald_yaku_all;
  void *map_ptcl;
  void *map_texg;
  void *yakumono_param;
  void *map_plit;
  void *x6C8;
  DynamicModelDesc *quake_model_set;
  s16 x6D0;
  s16 x6D2;
  s16 x6D4;
  s16 x6D6;
  s32 x6D8;
  s16 x6DC;
  s16 x6DE;
  f32 x6E0;
  int x6E4[2];
  u8 x6EC_pad[0x708 - 0x6EC];
  s16 x708;
  f32 x70C;
  f32 x710;
  s32 x714;
  f32 x718;
  f32 x71C;
  s32 x720;
  f32 x724;
  f32 x728;
  HSD_GObj *x72C;
  Vec3 x730;
  f32 x73C;
  s32 x740;
  u8 x744_pad[0x748 - 0x744];
};
typedef struct StageCallbacks
{
  void (*callback0)(Ground_GObj *);
  bool (*callback1)(Ground_GObj *);
  void (*callback2)(Ground_GObj *);
  void (*callback3)(Ground_GObj *);
  union 
  {
    u32 flags;
    struct 
    {
      u8 flags_b0 : 1;
      u8 flags_b1 : 1;
      u8 flags_b2 : 1;
      u8 flags_b3 : 1;
      u8 flags_b4 : 1;
      u8 flags_b5 : 1;
      u8 flags_b6 : 1;
      u8 flags_b7 : 1;
    };
  };
} StageCallbacks;
typedef struct StageData
{
  u32 flags1;
  StageCallbacks *callbacks;
  char *data1;
  void (*callback0)(void);
  void (*callback1)(int);
  void (*OnLoad)(void);
  void (*OnStart)(void);
  bool (*callback4)(void);
  DynamicsDesc *(*callback5)(enum_t);
  bool (*callback6)(Vec3 *, int, HSD_JObj *);
  u32 flags2;
  S16Vec3 *x2C;
  size_t x30;
} StageData;
typedef struct StructPairWithStageID
{
  s32 stage_id;
  s32 list_idx;
} StructPairWithStageID;
struct GroundVars_unk
{
  int xC4;
  int xC8;
  int xCC;
  int xD0;
  int xD4;
  int xD8;
  float xDC;
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
struct grDynamicAttr_UnkStruct
{
  grDynamicAttr_UnkStruct *next;
  s32 unk4;
  Vec3 unk8;
  s32 unk14;
  f32 unk18;
  s32 unk1C;
  u8 x0_fill[0x24 - 0x20];
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
  u8 x0;
  s8 x1;
  f32 x4;
  f32 x8;
  f32 xC;
};
struct grCorneria_GroundVars
{
  struct 
  {
    u8 b0 : 1;
    u8 b1 : 1;
  } xC4_flags;
  u8 xC5;
  struct 
  {
    u8 b0 : 1;
  } xC6_flags;
  u8 xC7;
  u32 xC8;
  u32 xCC;
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
  f32 xE4;
  f32 xE8;
  f32 xEC;
  f32 xF0;
  f32 xF4;
  f32 xF8;
  u32 xFC;
  u32 x100;
  u32 x104;
  u32 x108;
  u32 x10C;
  u32 x110;
  f32 x114;
  u8 x118;
  u8 x119;
  u8 x11A;
  u8 x11B;
  u32 x11C;
  Item_GObj *left_cannon;
  Item_GObj *right_cannon;
  HSD_GObj *x128;
  HSD_JObj *x12C;
};
struct grGreatBay_GroundVars
{
  u8 _0[0x10];
  u32 x10;
  s32 x14;
  u32 x18;
  f32 x1C;
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
typedef struct grInishie1_Block
{
  s16 status;
  s16 x2;
  s32 x4;
  f32 x8;
  f32 xC;
  HSD_JObj *jobj;
  HSD_JObj *jobj2;
  HSD_GObj *hatena_gobj;
  Item_GObj *item_gobj;
  s16 x20;
  s16 x22;
} grInishie1_Block;
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
  f32 x100;
  f32 x104;
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
  Vec3 xD8;
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
struct grYorster_GroundVars
{
  int xC4;
};
struct grZebes_GroundVars
{
  u8 x0_b0 : 1;
  void *x4;
  void *x8;
  Vec3 xC;
};
struct grFigureGet_GroundVars
{
  void *x0;
  void *x4;
  int x8;
  int xC;
};
struct grFourside_GroundVars
{
  u8 x0;
  u8 x1;
  s32 x4;
};
struct grGreens_BlockVars
{
  unsigned int status : 4;
  unsigned int index : 5;
  unsigned int x1_1 : 1;
  unsigned int x1_2 : 1;
  unsigned int x1_3 : 1;
  unsigned int x1_4 : 1;
  unsigned int x1_5 : 1;
  unsigned int x1_6 : 1;
  unsigned int x1_7 : 1;
  float x4;
  float x8;
  Ground_GObj *xC;
  Item_GObj *x10;
  HSD_JObj *x14;
  int x18;
  int x1C;
};
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
struct grOnett_AwningData
{
  float accumulator;
  u8 pad04[4];
  float initial;
  s16 counter;
  u8 pad0E[4];
  s16 flag;
  u8 pad14[8];
};
struct grOnett_GroundVars
{
  u8 x0_b0 : 1;
  u8 pad[0xCC - 0xC5];
  struct grOnett_AwningData awnings[2];
};
struct grBigBlue_GroundVars
{
  u8 x0_b0 : 1;
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
  int x6C;
  int x70;
  char pad_40[0xC4 - 0x74];
  union 
  {
    union GroundVars
    {
      char pad_0[0x204 - 0xC4];
      struct grBigBlue_GroundVars bigblue;
      struct grCorneria_GroundVars corneria;
      struct grGreatBay_GroundVars greatbay;
      struct grFigureGet_GroundVars figureget;
      struct GroundVars_flatzone flatzone;
      struct GroundVars_flatzone2 flatzone2;
      struct grFourside_GroundVars fourside;
      struct grGreens_GroundVars greens;
      struct grIceMt_GroundVars icemt;
      struct grIceMt_GroundVars2 icemt2;
      struct grInishie1_GroundVars inishie1;
      struct grInishie1_GroundVars2 inishie12;
      struct grInishie1_GroundVars3 inishie13;
      struct grInishie2_GroundVars inishie2;
      struct grInishie2_GroundVars2 inishie22;
      struct grInishie2_GroundVars3 inishie23;
      struct GroundVars_izumi izumi;
      struct GroundVars_izumi2 izumi2;
      struct GroundVars_izumi3 izumi3;
      struct grKongo_GroundVars kongo;
      struct grKongo_GroundVars2 kongo2;
      struct grKongo_GroundVars3 kongo3;
      struct grKraid_GroundVars kraid;
      struct grOnett_GroundVars onett;
      struct grPura_GroundVars pura;
      struct grPura_GroundVars2 pura2;
      struct GroundVars_unk unk;
      struct grYorster_GroundVars yorster;
      struct grZebes_GroundVars zebes;
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
    } u;
  };
};
struct UnkBgmStruct
{
  s32 x0;
  s32 x4;
  s32 x8;
  u32 xC;
  u32 x10;
  s16 x14;
  s16 x16;
  s16 x18;
  u8 pad[0x64 - 0x1A];
};
struct UnkStage6B0
{
  f32 x0;
  s16 x4;
  u8 x6_pad[2];
  s16 x8;
  s16 xA;
  s32 xC;
  s32 x10;
  s32 x14;
  f32 x18;
  f32 x1C;
  f32 x20;
  f32 x24;
  f32 x28;
  u8 x2C_pad[0x2E - 0x2C];
  s16 x2E;
  s32 x30;
  s32 x34;
  s32 x38;
  f32 x3C;
  f32 x40;
  f32 x44;
  f32 x48;
  bool x4C_fixed_cam;
  f32 x50;
  f32 x54;
  f32 x58;
  f32 x5C;
  f32 x60;
  f32 x64;
  s16 x68;
  u8 x6C_pad[0xB0 - 0x6A];
  UnkBgmStruct *xB0;
  s32 xB4;
  GXColor xB8;
  GXColor xBC;
  GXColor xC0;
  GXColor xC4;
  GXColor xC8;
  GXColor xCC;
  GXColor xD0;
  GXColor xD4;
  GXColor xD8;
};
struct UnkStageDatInternal
{
  u8 x0_fill[0x4];
  u32 unk4;
};
struct UnkStageDat_x8_t
{
  struct HSD_Joint *unk0;
  u8 _4[0x10 - 0x4];
  HSD_CameraDescPerspective *x10;
  void *x14;
  void *x18;
  HSD_FogDesc *x1C;
  S16Vec3 *unk20;
  s32 unk24;
  void *x28;
  s16 *x2C;
  int x30;
};
struct UnkStageDat
{
  void *unk0;
  s32 unk4;
  struct UnkStageDat_x8_t *unk8;
  s32 unkC;
  HSD_Spline **unk10;
  s32 unk14;
  u8 x18_fill[0x20 - 0x18];
  void *unk20;
  s32 unk24;
  UnkStageDatInternal **unk28;
  s32 unk2C;
};
struct UnkArchiveStruct
{
  HSD_Archive *unk0;
  UnkStageDat *unk4;
  u32 unk8;
};
struct FigaTrack
{
  u16 length;
  u16 startframe;
  u8 obj_type;
  u8 frac_value;
  u8 frac_slope;
  u8 *ad_head;
};
struct FigaTree
{
  int type;
  u32 flags;
  f32 frames;
  s8 *nodes;
  FigaTrack *tracks;
};
HSD_FObj *fn_8001E60C(FigaTrack *, s8 frames);
void lbAnim_8001E6D8(HSD_JObj *, FigaTree *, FigaTrack *, s8 frames);
void lbAnim_8001E7E8(HSD_JObj *, FigaTree *, FigaTrack *, s8 frames);
float lbAnim_8001E8F8(FigaTree *);
void Command_00(CommandInfo *info);
void Command_01(CommandInfo *info);
void Command_02(CommandInfo *info);
void Command_03(CommandInfo *info);
void Command_04(CommandInfo *info);
void Command_05(CommandInfo *info);
void Command_14(CommandInfo *info);
void Command_06(CommandInfo *info);
void Command_07(CommandInfo *info);
void Command_08(CommandInfo *info);
void Command_09(CommandInfo *info);
bool Command_Execute(CommandInfo *info, u32 command);
struct FighterPartsTable
{
  u8 *joint_to_part;
  u8 *part_to_joint;
  u32 parts_num;
};
struct ftCommonData
{
  float x0;
  float x4;
  float x8_someStickThreshold;
  float xC;
  float x10;
  float x14;
  float x18;
  int x1C;
  float x20_radians;
  float x24;
  float x28;
  float x2C;
  float x30;
  float x34;
  float x38_someLStickXThreshold;
  float x3C;
  int x40;
  float x44;
  float x48;
  float x4C;
  float x50;
  float x54;
  float x58_someLStickXThreshold;
  float x5C;
  float x60_someFrictionMul;
  float x64;
  float x68;
  float x6C;
  float tap_jump_threshold;
  int x74;
  float x78;
  float tap_jump_release_threshold;
  float x80;
  float x84;
  float x88;
  int x8C;
  float x90;
  float x94;
  float x98;
  float x9C_radians;
  float xA0_radians;
  float xA4_radians;
  float xA8_radians;
  float attackhi3_stick_threshold_y;
  float xB0;
  float xB4;
  float xB8_radians;
  float xBC_radians;
  float xC0_radians;
  float xC4_radians;
  float xC8;
  float xCC;
  float xD0;
  float xD4;
  float xD8;
  float xDC;
  float xE0;
  int xE4;
  float xE8;
  float xEC;
  float xF0;
  float xF4;
  float xF8;
  int xFC;
  float x100;
  float kb_min;
  float x108;
  float x10C;
  float x110;
  float x114;
  float x118;
  float x11C;
  float x120;
  float kb_squat_mul;
  float x128;
  float x12C;
  int x130;
  int x134;
  float x138;
  float x13C;
  float x140;
  float x144_radians;
  float x148;
  float x14C;
  float x150;
  float x154;
  float x158;
  float x15C;
  float x160;
  float x164;
  float x168;
  float x16C;
  float x170;
  float x174;
  float x178;
  float x17C;
  float x180;
  float x184;
  float x188;
  int x18C;
  float x190;
  float x194_unkHitLagFrames;
  float x198;
  float x19C;
  float x1A0;
  float x1A4;
  float x1A8;
  float x1AC;
  float x1B0;
  float x1B4;
  int x1B8;
  float x1BC;
  float x1C0;
  float x1C4;
  float x1C8;
  float x1CC;
  float x1D0;
  float x1D4;
  float x1D8;
  void *x1DC;
  float x1E0;
  float x1E4;
  float x1E8_radians;
  float x1EC;
  float x1F0;
  float x1F4;
  float x1F8;
  float x1FC;
  float x200;
  float x204_knockbackFrameDecay;
  float x208;
  float x20C;
  float x210;
  int x214;
  float x218;
  float x21C;
  float x220;
  int x224;
  float x228;
  float x22C;
  float x230;
  float x234_radians;
  float x238_radians;
  void *x23C;
  float x240;
  float x244;
  float x248;
  float x24C;
  float x250;
  float x254;
  float x258;
  float x25C;
  float x260_startShieldHealth;
  float x264;
  float x268;
  float x26C;
  float x270;
  void *x274;
  float x278;
  float x27C;
  float x280_unkShieldHealth;
  float x284;
  float x288;
  float x28C;
  float x290;
  float x294;
  float x298;
  float x29C;
  int x2A0;
  float x2A4;
  float x2A8;
  float x2AC;
  float x2B0;
  float x2B4;
  int x2B8;
  float x2BC;
  float x2C0;
  float x2C4;
  float x2C8;
  float x2CC;
  float x2D0;
  float x2D4;
  float x2D8;
  float x2DC;
  float x2E0;
  float x2E4;
  float x2E8;
  float x2EC;
  float x2F0;
  float x2F4;
  float x2F8;
  float x2FC;
  float x300;
  float x304;
  float x308;
  float x30C;
  float x310;
  float x314;
  int x318;
  float x31C;
  int x320;
  int x324;
  float x328;
  Vec2 escapeair_deadzone;
  int x334;
  float escapeair_force;
  float escapeair_decay;
  float x340;
  float x344;
  int x348;
  float x34C;
  float x350;
  float x354;
  float x358;
  float x35C;
  float x360;
  float x364;
  float x368;
  float x36C;
  float x370;
  float x374;
  float x378;
  float x37C;
  lbColl_80008D30_arg1 x380;
  float grab_timer_decrement;
  float x3A8;
  float x3AC;
  float x3B0;
  float shouldered_anim_rate;
  float x3B8;
  float x3BC;
  int x3C0;
  float x3C4;
  float x3C8;
  int x3CC;
  float x3D0;
  float x3D4;
  float x3D8;
  float x3DC;
  float x3E0;
  float x3E4;
  float x3E8_shieldKnockbackFrameDecay;
  float x3EC_shieldGroundFrictionMultiplier;
  float x3F0;
  void *x3F4;
  void *x3F8;
  int x3FC;
  float x400;
  float x404;
  float x408;
  float x40C;
  int x410;
  int x414;
  int x418;
  int x41C;
  float x420;
  float x424;
  int x428;
  float x42C;
  float x430;
  float x434;
  float x438;
  float x43C;
  float x440;
  float x444;
  float x448;
  float x44C;
  float x450;
  float x454;
  float x458;
  float x45C;
  float x460;
  float x464;
  float x468;
  float x46C;
  float x470;
  float x474;
  float x478;
  float x47C;
  float x480;
  float x484;
  int x488;
  float x48C;
  float x490;
  float x494;
  int ledge_cooldown;
  int x49C;
  float x4A0;
  float x4A4;
  float x4A8;
  float x4AC;
  float x4B0;
  int x4B4;
  float x4B8;
  float x4BC;
  float x4C0;
  int x4C4;
  int x4C8;
  int x4CC;
  float x4D0;
  float x4D4;
  u32 x4D8;
  Vec2 x4DC;
  Vec3 x4E4;
  float x4F0;
  float x4F4;
  u32 x4F8;
  u32 x4FC;
  void *x500;
  int x504;
  void *x508;
  void *x50C;
  float x510;
  float x514;
  void *x518;
  float x51C_radians;
  int x520;
  void *x524;
  void *x528;
  void *x52C;
  void *x530;
  void *x534;
  void *x538;
  float x53C;
  float x540;
  void *x544;
  float x548;
  float x54C;
  float x550;
  float x554;
  float x558;
  float x55C;
  float x560_radians;
  float x564;
  float x568;
  float x56C;
  float x570;
  float x574;
  float x578;
  int x57C;
  int x580;
  int x584;
  int x588;
  float x58C;
  float x590;
  float open_parasol_threshold;
  float close_parasol_threshold;
  float x59C;
  float x5A0;
  int x5A4;
  float x5A8;
  float x5AC;
  float x5B0;
  int x5B4;
  float x5B8;
  void *x5BC;
  float x5C0;
  void *x5C4;
  int x5C8;
  float x5CC;
  void *x5D0;
  void *x5D4;
  int x5D8;
  u32 bury_timer_unk1;
  u32 bury_timer_unk2;
  u32 bury_timer_unk3;
  float x5E8;
  void *x5EC;
  u32 x5F0;
  int x5F4;
  float x5F8;
  float x5FC;
  float x600;
  float x604;
  float x608;
  float x60C;
  float x610;
  float x614;
  float x618;
  float x61C;
  int x620;
  float x624;
  float x628;
  float x62C;
  float x630;
  float x634;
  float x638;
  float x63C;
  float x640;
  float x644;
  int x648;
  float x64C;
  float x650;
  float x654;
  float x658;
  float x65C;
  float x660;
  float x664;
  float x668;
  float x66C;
  float x670;
  float x674;
  float x678;
  float x67C;
  float x680;
  float x684;
  int x688;
  int x68C;
  int x690;
  float x694;
  float x698;
  float warpstarfall_drift_scaling;
  float warpstarfall_drift_flat;
  float warpstarfall_drift_max;
  float x6A8;
  int x6AC;
  int x6B0;
  int x6B4;
  int x6B8;
  int x6BC;
  int x6C0;
  float x6C4;
  int x6C8;
  int x6CC;
  float x6D0;
  void *x6D4;
  void *x6D8[1];
  GXColor x6DC_colorsByPlayer[4];
  u8 x6EC[0x6F0 - 0x6EC];
  float metal_armor;
  int x6F4_unkDamage;
  int x6F8;
  int x6FC;
  int x700;
  float x704;
  float x708;
  float x70C;
  float x710;
  float x714;
  float kb_ice_mul;
  float x71C;
  float x720;
  float x724;
  float x728;
  float x72C;
  float x730;
  float x734;
  float x738;
  int x73C;
  float x740;
  float x744;
  float x748;
  float x74C;
  float x750;
  float x754;
  float x758;
  float x75C;
  int x760;
  int x764;
  float x768;
  float x76C;
  float x770;
  int x774;
  float passive_wall_vel_y_base;
  float damageice_gravity_mult;
  float damageice_min_speed;
  float damageice_speed_mult_on_break;
  float damageice_rot_speed_min;
  float damageice_rot_speed_max;
  float x790_damageice_unk;
  float x794_damageice_unk;
  float x798_damageice_unk;
  float damageice_dmg_time_reduction_mult;
  float damageice_ice_size;
  float damageicejump_escape_time;
  float x7A8;
  int x7AC;
  int x7B0;
  int x7B4_unkDamage;
  float x7B8;
  float x7BC;
  float x7C0;
  float kb_smashcharge_mul;
  float x7C8;
  int x7CC;
  int x7D0;
  float hit_weight_mul;
  GXColor x7D8;
  int x7DC;
  int x7E0;
  float x7E4_scaleZ;
  u32 unk_kb_angle_min;
  u32 unk_kb_angle_max;
  int x7F0;
  float x7F4;
  float x7F8;
  float x7FC;
  float x800;
  float x804;
  Vec3 x808;
  int x814;
};
typedef struct _FtSFXArr
{
  int num;
  int *sfx_ids;
} FtSFXArr;
struct FtSFX
{
  FtSFXArr *smash;
  int x4;
  int x8;
  int xC;
  int x10;
  int x14;
  int x18;
  int x1C;
  int x20;
  int x24;
  int x28;
  int x2C;
  int x30;
  int x34;
};
typedef struct 
{
  u32 unk0;
  f32 unk4;
} ftData_x34;
typedef struct ftData_x44_t
{
  s16 unk0;
  s16 unk2;
  s16 unk4;
  s16 unk6;
  s16 unk8;
  s16 unkA;
  float unkC;
  float ledge_snap_x;
  float ledge_snap_y;
  float ledge_snap_height;
} ftData_x44_t;
struct ftData
{
  struct ftCo_DatAttrs *x0;
  void *ext_attr;
  struct ftData_x8
  {
    u32 x0;
    u8 x4[0x4];
    struct ftData_x8_x8
    {
      u32 x8;
      u16 **xC;
    } x8;
    u8 x10;
    u8 x11;
    u8 x12;
    u8 x13;
    u8 x14;
  } *x8;
  struct S_TEMP4 *xC;
  u8 *x10;
  struct S_TEMP4 *x14;
  u8 *x18;
  struct ftData_x1C
  {
    u16 x0;
    u16 x2;
    u8 *x4;
    HSD_AnimJoint **x8;
  } **x1C;
  struct 
  {
    void *x0;
    HSD_Joint *x8;
  } *x20;
  void *x24;
  WaitStruct *x28;
  struct ftDynamics *x2C;
  void *x30;
  struct ftData_x34
  {
    Fighter_Part x0;
    float scale;
  } *x34;
  struct ftData_x38
  {
    int x0;
    Vec3 x4;
    float x10;
  } *x38;
  struct UnkFloat6_Camera *x3C;
  struct itPickup *x40;
  ftData_x44_t *x44;
  void **x48_items;
  FtSFX *x4C_sfx;
  Vec2 *x50;
  int x54;
  void *x58;
  HSD_Joint *x5C;
};
typedef struct _ThrowFlags
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
    u32 flags;
  };
} ThrowFlags;
struct ftCo_DatAttrs_xBC_t
{
  float size;
  Vec3 x4;
  Vec3 x10;
  float x1C;
};
typedef struct ftCo_DatAttrs
{
  float walk_init_vel;
  float walk_accel;
  float walk_max_vel;
  float slow_walk_max;
  float mid_walk_point;
  float fast_walk_min;
  float gr_friction;
  float dash_initial_velocity;
  float dash_run_acceleration_a;
  float dash_run_acceleration_b;
  float dash_run_terminal_velocity;
  float run_animation_scaling;
  float max_run_brake_frames;
  float ground_max_horizontal_velocity;
  float jump_startup_time;
  float jump_h_initial_velocity;
  float jump_v_initial_velocity;
  float ground_to_air_jump_momentum_multiplier;
  float jump_h_max_velocity;
  float hop_v_initial_velocity;
  float air_jump_v_multiplier;
  float air_jump_h_multiplier;
  int max_jumps;
  float grav;
  float terminal_vel;
  float air_drift_stick_mul;
  float aerial_drift_base;
  float air_drift_max;
  float aerial_friction;
  float fast_fall_velocity;
  float air_max_horizontal_velocity;
  float jab_2_input_window;
  float jab_3_input_window;
  float frames_to_change_direction_on_standing_turn;
  float weight;
  float model_scaling;
  float initial_shield_size;
  float shield_break_initial_velocity;
  int rapid_jab_window;
  float x9C;
  int xA0;
  int xA4;
  float ledge_jump_horizontal_velocity;
  float ledge_jump_vertical_velocity;
  float item_throw_velocity_multiplier;
  float xB4;
  float xB8;
  ftCo_DatAttrs_xBC_t xBC;
  float xDC;
  float kirby_b_star_damage;
  float normal_landing_lag;
  float landingairn_lag;
  float landingairf_lag;
  float landingairb_lag;
  float landingairhi_lag;
  float landingairlw_lag;
  float name_tag_height;
  float passivewall_vel_x;
  float wall_jump_horizontal_velocity;
  float wall_jump_vertical_velocity;
  float passiveceil_vel_x;
  float trophy_scale;
  Vec3 x114;
  Vec3 x120;
  float x12C;
  Vec3 x130;
  float x13C;
  float x140;
  float x144;
  float x148;
  float damageice_ice_size;
  float x150_damageice_unk;
  float x154_damageice_unk;
  float damageicejump_vel_y;
  float damageicejump_vel_x_mult;
  float respawn_platform_scale;
  float x164;
  float x168;
  int camera_zoom_target_bone;
  Vec3 x170;
  float x17C;
  u8 weight_independent_throws_mask;
} ftCo_DatAttrs;
struct FighterBone
{
  HSD_JObj *joint;
  HSD_JObj *x4_jobj2;
  union 
  {
    struct 
    {
      u8 flags_b0 : 1;
      u8 flags_b1 : 1;
      u8 flags_b2 : 1;
      u8 flags_b3 : 1;
      u8 flags_b4 : 1;
      u8 flags_b5 : 1;
      u8 flags_b6 : 1;
      u8 flags_b7 : 1;
      u8 flags2_b0 : 1;
      u8 flags2_b1 : 1;
      u8 flags2_b2 : 1;
      u8 flags2_b3 : 1;
      u8 flags2_b4 : 1;
      u8 flags2_b5 : 1;
      u8 flags2_b6 : 1;
      u8 flags2_b7 : 1;
    };
    u16 flags8;
  };
  union 
  {
    struct 
    {
      u8 xC;
      u8 xD : 7;
    };
    u32 flagsC;
  };
};
typedef struct _SmashAttr
{
  SmashState state;
  float x2118_frames;
  float x211C_holdFrame;
  float x2120_damageMul;
  float x2124_frameSpeedMul;
  s32 x2128;
  u8 x212C;
  u8 x212D;
  s8 x212E;
  s8 x212F;
  s32 x2130_sfxBool;
  u8 x2134_vibrateFrame;
  s8 x2135;
  s8 x2136;
  s8 x2137;
  float x2138_smashSinceHitbox;
} SmashAttr;
typedef struct itPickup
{
  Vec4 gr_light_offset;
  Vec4 gr_heavy_offset;
  Vec4 air_light_offset;
} itPickup;
typedef struct 
{
  HSD_Joint *joint;
  HSD_MatAnimJoint *x4;
  u32 pad_x8;
  u32 pad_xC;
  u32 pad_x10;
  HSD_Archive *x14_archive;
} UnkCostumeStruct;
struct UnkCostumeList
{
  UnkCostumeStruct *costume_list;
  u8 numCostumes;
};
struct MotionState
{
  enum_t anim_id;
  enum_t x4_flags;
  union 
  {
    u32 _;
    struct 
    {
      u8 move_id : 8;
      struct 
      {
        u8 x9_b0 : 1;
        u8 x9_b1 : 1;
        u8 x9_b2 : 1;
        u8 x9_b3 : 1;
        u8 x9_b4 : 1;
        u8 x9_b5 : 1;
        u8 x9_b6 : 1;
        u8 x9_b7 : 1;
      };
      u8 xA;
      u8 xB;
    };
  };
  HSD_GObjEvent anim_cb;
  HSD_GObjEvent input_cb;
  HSD_GObjEvent phys_cb;
  HSD_GObjEvent coll_cb;
  HSD_GObjEvent cam_cb;
};
struct S_TEMP4
{
  char *x0;
  s32 x4;
  s32 x8;
  ftSubactionList *xC;
  s32 x10_animCurrFlags;
  u32 x14;
};
struct Fighter_CostumeStrings
{
  char *dat_filename;
  char *joint_name;
  char *matanim_joint_name;
};
struct Fighter_DemoStrings
{
  char *result_filename;
  char *intro_filename;
  char *ending_filename;
  char *vi_wait_filename;
};
union Struct2070
{
  struct 
  {
    s8 x2070;
    u8 x2071_b0_3 : 4;
    u8 x2071_b4 : 1;
    u8 x2071_b5 : 1;
    u8 x2071_b6 : 1;
    u8 x2071_b7 : 1;
    u8 x2072_b0 : 1;
    u8 x2072_b1 : 1;
    u8 x2072_b2 : 1;
    u8 x2072_b3 : 1;
    u8 x2072_b4 : 1;
    u8 x2072_b5 : 1;
    u8 x2072_b6 : 1;
    u8 x2072_b7 : 1;
    u8 x2073;
  };
  s32 x2070_int;
};
struct Struct2074
{
  Vec2 x2074_vec;
  S32Vec2 x207C;
  u32 x2084;
  u16 x2088;
};
struct ftSubactionList
{
  u8 x0_opcode;
};
struct ftDeviceUnk3
{
  Ground_GObj *ground;
  u32 type;
  ftDevice_Callback0 active_cb;
};
struct ftDeviceUnk4
{
  int x0;
  void *x4;
};
struct ftDeviceUnk5
{
  void *x0;
  ftCommon_BuryType x4;
  bool (*cb)(void *, Fighter_GObj *);
};
struct Fighter_x1A88_xFC_t
{
  HSD_Pad x0;
  u8 x4;
  u8 x5;
  u8 lstickX;
  u8 lstickY;
  u8 cstickX;
  u8 cstickY;
  u8 xA;
  u8 xB;
  Vec3 cur_pos;
  float facing_dir;
};
struct Fighter_x1A88_t
{
  HSD_Pad x0;
  s8 lstickX;
  s8 lstickY;
  s8 cstickX;
  s8 cstickY;
  u8 ltrigger;
  u8 rtrigger;
  enum_t xC;
  int level;
  int x14;
  int x18;
  int x1C;
  int x20;
  int x24;
  int x28;
  int x2C;
  int x30;
  int x34;
  float x38;
  float x3C;
  float x40;
  Fighter *x44;
  void *x48;
  Item *x4C;
  int x50;
  Vec2 x54;
  float x5C;
  int x60;
  Vec2 x64;
  Vec2 x6C;
  Vec2 x74;
  int x7C;
  int x80;
  int x84;
  int x88;
  int x8C;
  int x90;
  int x94;
  Vec3 x98;
  int xA4;
  u8 pad_xA8[0xC8 - 0xA8];
  u8 xC8;
  u8 pad_xC9[0xEC - 0xC9];
  u8 xEC;
  u8 pad_xED[0xF0 - 0xED];
  Fighter *xF0;
  Item *xF4;
  u8 xF8_b0 : 1;
  u8 xF8_b12 : 2;
  u8 xF8_b34 : 2;
  u8 xF8_b5 : 1;
  u8 xF8_b6 : 1;
  u8 xF8_b7 : 1;
  u8 xF9_b0 : 1;
  u8 xF9_b1 : 1;
  u8 xF9_b2 : 1;
  u8 xF9_b3 : 1;
  u8 xF9_b4 : 1;
  u8 xF9_b5 : 1;
  u8 xF9_b6 : 1;
  u8 xF9_b7 : 1;
  u8 xFA_b0 : 1;
  u8 xFA_b1 : 1;
  u8 xFA_b2 : 1;
  u8 xFA_b34 : 2;
  u8 xFA_b5 : 1;
  u8 xFA_b6 : 1;
  u8 xFA_b7 : 1;
  u8 xFB_b0 : 1;
  u8 xFB_b1 : 1;
  u8 xFB_b2 : 1;
  u8 xFB_b3 : 1;
  u8 xFB_b4 : 1;
  u8 xFB_b5 : 1;
  u8 xFB_b6 : 1;
  u8 xFB_b7 : 1;
  struct Fighter_x1A88_xFC_t xFC[30];
  struct Fighter_x1A88_xFC_t *x444;
  struct Fighter_x1A88_xFC_t *x448;
  u32 command_duration;
  s8 *csP;
  s8 buffer[0x100];
  s8 *write_pos;
  float x558;
  float x55C;
  float x560;
  float x564;
  float x568;
  float x56C;
  float x570;
  float half_width;
  float half_height;
};
struct Fighter_x59C_t
{
  u8 x0[0x8000];
};
struct UnkPlBonusBits
{
  u8 x0;
  u8 x1;
  u8 x2_b0 : 1;
  u8 x2_b1 : 1;
  u8 x2_b2 : 1;
  u8 x2_b3 : 1;
  u8 x2_b4 : 1;
  u8 x2_b5 : 1;
  u8 x2_b6 : 1;
  u8 x2_b7 : 1;
  u8 x3;
};
struct ft_800898B4_t
{
  int x0;
  int x4;
  float kb_applied1;
  int xC;
  u32 x10_b0 : 1;
  u32 x10_b1 : 1;
  u32 x10_b2 : 1;
  u32 x10_b3 : 1;
  u32 x10_b4 : 1;
  u32 x10_b5 : 1;
  u32 x10_b6 : 1;
  u32 x10_b7 : 1;
  u32 x11_b0 : 1;
  u32 x11_b1 : 1;
  u32 x11_b2 : 1;
  u32 x11_b3 : 1;
  u32 x11_b4 : 1;
};
struct Fighter
{
  HSD_GObj *gobj;
  FighterKind kind;
  s32 x8_spawnNum;
  u8 player_id;
  FtMotionId motion_id;
  enum_t anim_id;
  s32 x18;
  MotionState *x1C_actionStateList;
  MotionState *x20_actionStateList;
  struct S_TEMP4 *x24;
  u8 *x28;
  float facing_dir;
  float facing_dir1;
  Vec3 x34_scale;
  float x40;
  Mtx x44_mtx;
  Vec3 x74_anim_vel;
  Vec3 self_vel;
  Vec3 x8c_kb_vel;
  Vec3 x98_atk_shield_kb;
  Vec3 xA4_unk_vel;
  Vec3 cur_pos;
  Vec3 prev_pos;
  Vec3 pos_delta;
  Vec3 xD4_unk_vel;
  GroundOrAir ground_or_air;
  float xE4_ground_accel_1;
  float xE8_ground_accel_2;
  float gr_vel;
  float xF0_ground_kb_vel;
  float xF4_ground_attacker_shield_kb_vel;
  Vec2 xF8_playerNudgeVel;
  float x100;
  u8 x104;
  s8 x105;
  s8 x106;
  s8 x107;
  HSD_Joint *x108_costume_joint;
  ftData *ft_data;
  ftCo_DatAttrs co_attrs;
  itPickup x294_itPickup;
  Vec2 x2C4;
  ftDonkeyAttributes *x2CC;
  struct Fighter_x2D0_t
  {
    int x0;
    float x4;
    float x8;
    float xC;
    float x10;
    float x14[5];
    int x28;
    enum_t x2C;
    enum_t x30;
  } *x2D0;
  void *dat_attrs;
  void *dat_attrs_backup;
  float x2DC;
  float x2E0;
  float x2E4;
  float x2E8;
  float x2EC;
  BoneDynamicsDesc dynamic_bone_sets[Ft_Dynamics_NumMax];
  int dynamics_num;
  CommandInfo x3E4_fighterCmdScript;
  ColorOverlay x408;
  ColorOverlay x488;
  ColorOverlay x508;
  HSD_LObj *x588;
  u32 x58C;
  FigaTree *x590;
  union 
  {
    struct 
    {
      u8 x594_b0 : 1;
      u8 x594_b1 : 1;
      u8 x594_b2 : 1;
      u8 x594_b3 : 1;
      u8 x594_b4 : 1;
      u8 x594_b5 : 1;
      u8 x594_b6 : 1;
      u8 x594_b7 : 1;
      struct 
      {
        u8 x0 : 7;
        u16 x7 : 3;
      } x596_bits;
    };
    struct 
    {
      u32 x594_pad : 10;
      u32 x594_bits : 13;
      u32 x594_pad2 : 3;
      u32 x597_bits : 6;
    };
    s32 x594_s32;
  };
  FigaTree *x598;
  struct Fighter_x59C_t *x59C;
  struct Fighter_x59C_t *x5A0;
  void *x5A4;
  void *x5A8;
  u32 x5AC;
  u8 _5B0[0x5B8 - 0x5B0];
  s32 x5B8;
  void *x5BC;
  u8 filler_x598[0x5C8 - 0x5C0];
  void *x5C8;
  u32 n_costume_tobjs;
  u16 *x5D0;
  HSD_TObj *costume_tobjs[5];
  FighterBone *parts;
  DObjList dobj_list;
  struct 
  {
    s8 x0;
    s8 x1;
  } x5F4_arr[2];
  s8 x5F8;
  u8 filler_x5FC[0x60C - 0x5F9];
  void *x60C;
  GXColor x610_color_rgba[2];
  u8 x618_player_id;
  u8 x619_costume_id;
  u8 x61A_controller_index;
  u8 team;
  s8 x61C;
  u8 x61D;
  u8 filler_x61E[0x620 - 0x61E];
  struct 
  {
    Vec2 lstick;
    Vec2 lstick1;
    float x630;
    float x634;
    Vec2 cstick;
    Vec2 cstick1;
    float x648;
    float x64C;
    float x650;
    float x654;
    float x658;
    HSD_Pad held_inputs;
    HSD_Pad x660;
    HSD_Pad x664;
    HSD_Pad x668;
    HSD_Pad x66C;
  } input;
  u8 x670_timer_lstick_tilt_x;
  u8 x671_timer_lstick_tilt_y;
  u8 x672_input_timer_counter;
  u8 x673;
  u8 x674;
  u8 x675;
  u8 x676_x;
  u8 x677_y;
  u8 x678;
  u8 x679_x;
  u8 x67A_y;
  u8 x67B;
  u8 x67C;
  u8 x67D;
  u8 x67E;
  u8 x67F;
  u8 x680;
  u8 x681;
  u8 x682;
  u8 x683;
  u8 x684;
  u8 x685;
  u8 x686;
  u8 x687;
  u8 x688;
  u8 x689;
  u8 x68A;
  u8 x68B;
  Vec3 x68C_transNPos;
  Vec3 x698;
  Vec3 x6A4_transNOffset;
  Vec3 x6B0;
  float lstick_angle;
  Vec3 x6C0;
  Vec3 x6CC;
  Vec3 x6D8;
  Vec3 x6E4;
  CollData coll_data;
  s32 ecb_lock;
  CmSubject *x890_cameraBox;
  float cur_anim_frame;
  float x898_unk;
  float frame_speed_mul;
  float x8A0_unk;
  float x8A4_animBlendFrames;
  float x8A8_unk;
  HSD_JObj *x8AC_animSkeleton;
  struct Fighter_x8B0_t
  {
    int x0;
    float x4;
    float x8;
    float xC;
    s8 x10;
    s8 x11;
  } x8B0[5];
  HitCapsule x914[4];
  HitCapsule xDF4[2];
  HitCapsule x1064_thrownHitbox;
  u8 x119C_teamUnk;
  u8 grabber_unk1;
  u8 hurt_capsules_len;
  u8 x119F;
  FighterHurtCapsule hurt_capsules[15];
  struct Fighter_x1614_t
  {
    f32 x0;
    HSD_JObj *x4;
    Vec3 x8;
    Vec3 x14;
    Vec3 x20;
  } x1614[2];
  u8 x166C;
  struct Fighter_x1670_t
  {
    Vec3 v1;
    float v2;
    HSD_JObj *jobj;
    float x14;
    Vec3 x18;
    u8 pad[0x28 - 0x24];
  } x1670[1];
  u8 filler_x1674[(0x1828 - 0x1670) - 0x28];
  enum_t x1828;
  struct dmg
  {
    float x182c_behavior;
    float x1830_percent;
    float x1834;
    float x1838_percentTemp;
    int x183C_applied;
    int x1840;
    float facing_dir_1;
    int x1848_kb_angle;
    int x184c_damaged_hurtbox;
    float kb_applied;
    Vec3 x1854_collpos;
    u32 x1860_element;
    int x1864;
    HSD_GObj *x1868_source;
    int x186c;
    struct DmgLogEntry *x1870;
    int x1874;
    int x1878;
    float x187c;
    Vec3 x1880;
    int x188c;
    int x1890;
    int x1894;
    float x1898;
    float x189C_unk_num_frames;
    float x18a0;
    float x18A4_knockbackMagnitude;
    float x18A8;
    int x18ac_time_since_hit;
    float armor0;
    float armor1;
    float x18B8;
    float x18BC;
    int x18C0;
    int x18c4_source_ply;
    int x18C8;
    int x18CC;
    int x18D0;
    UnkPlBonusBits x18d4;
    ft_800898B4_t x18d8;
    u16 x18ec_instancehitby;
    int x18F0;
    int x18F4;
    u8 x18F8;
    u8 x18f9;
    u16 x18fa_model_shift_frames;
    u8 x18FC;
    u8 x18FD;
    float x1900;
    float x1904;
    enum_t x1908;
    void *x190C;
    int x1910;
    int x1914;
    int int_value;
    float x191C;
    float facing_dir;
    int x1924;
    float x1928;
    float x192c;
    struct lb_80014638_arg0_t x1930;
    int x1948;
    int x194C;
    bool x1950;
    float x1954;
    float x1958;
    float x195c_hitlag_frames;
  } dmg;
  float x1960_vibrateMult;
  float x1964;
  u8 x1968_jumpsUsed;
  u8 x1969_walljumpUsed;
  float hitlag_mul;
  enum_t unk_msid;
  Item_GObj *item_gobj;
  Item_GObj *x1978;
  HSD_GObj *x197C;
  HSD_GObj *x1980;
  Item_GObj *x1984_heldItemSpec;
  enum_t x1988;
  s32 x198C;
  s32 x1990;
  bool x1994;
  float shield_health;
  float lightshield_amount;
  s32 x19A0_shieldDamageTaken;
  int x19A4;
  HSD_GObj *x19A8;
  float specialn_facing_dir;
  enum_t x19B0;
  float shield_unk0;
  float shield_unk1;
  s32 x19BC_shieldDamageTaken3;
  HitResult shield_hit;
  HitResult reflect_hit;
  HitResult absorb_hit;
  struct 
  {
    float x1A2C_reflectHitDirection;
    s32 x1A30_maxDamage;
    float x1A34_damageMul;
    float x1A38_speedMul;
    s32 x1A3C_damageOver;
  } ReflectAttr;
  struct 
  {
    float x1A40_absorbHitDirection;
    s32 x1A44_damageTaken;
    s32 x1A48_hitsTaken;
  } AbsorbAttr;
  float grab_timer;
  s8 x1A50;
  s8 x1A51;
  u8 x1A52;
  u8 x1A53;
  s32 x1A54;
  Fighter_GObj *victim_gobj;
  Fighter_GObj *x1A5C;
  Item_GObj *target_item_gobj;
  void *x1A64;
  u16 x1A68;
  u16 x1A6A;
  float x1A6C;
  Vec3 x1A70;
  Vec3 x1A7C;
  struct Fighter_x1A88_t x1A88;
  int x2004;
  s32 x2008;
  s32 x200C;
  s32 x2010;
  s32 x2014;
  s32 x2018;
  s32 x201C;
  s8 x2020;
  s8 x2021;
  s8 x2022;
  s32 x2024;
  int metal_timer;
  int metal_health;
  s32 x2030;
  s32 x2034;
  s32 x2038;
  u32 x203C;
  HSD_DObj **x2040;
  u8 filler_x203C[0x2064 - 0x2044];
  int x2064_ledgeCooldown;
  s32 x2068_attackID;
  u16 x206C_attack_instance;
  short x206E;
  union Struct2070 x2070;
  struct Struct2074 x2074;
  s32 x208C;
  u16 x2090;
  u16 x2092;
  Fighter_GObj *x2094;
  u16 x2098;
  u16 x209A;
  u16 x209C;
  HSD_JObj *x20A0_accessory;
  LbShadow x20A4;
  HSD_GObj *unk_gobj;
  struct Fighter_x20B0_t
  {
    Vec3 x0;
    Vec3 xC;
  } x20B0[3];
  float x20F8;
  float x20FC;
  s8 x2100;
  u8 x2101_bits_0to6 : 7;
  u8 x2101_bits_8 : 1;
  s8 x2102;
  s8 x2103;
  int x2104;
  int capture_timer;
  u8 wall_jump_input_timer;
  u8 filler_x210C[3];
  float x2110_walljumpWallSide;
  SmashAttr smash_attrs;
  s32 x213C;
  float x2140;
  int x2144;
  s32 x2148;
  s32 x214C;
  s32 x2150;
  s32 x2154;
  s32 x2158;
  s32 x215C;
  s32 x2160;
  int x2164;
  int x2168;
  float unk_grab_val;
  float x2170;
  Vec x2174;
  s32 x2180;
  HSD_JObj *x2184;
  S32Vec2 x2188;
  HSD_GObjEvent grab_cb;
  HSD_GObjEvent x2194;
  HSD_GObjInteraction grabbed_cb;
  HSD_GObjEvent input_cb;
  HSD_GObjEvent anim_cb;
  HSD_GObjEvent phys_cb;
  HSD_GObjEvent coll_cb;
  HSD_GObjEvent cam_cb;
  HSD_GObjEvent accessory1_cb;
  HSD_GObjEvent accessory2_cb;
  HSD_GObjEvent accessory3_cb;
  HSD_GObjEvent accessory4_cb;
  HSD_GObjEvent deal_dmg_cb;
  HSD_GObjEvent shield_hit_cb;
  HSD_GObjEvent reflect_hit_cb;
  HSD_GObjEvent x21CC;
  HSD_GObjEvent hitlag_cb;
  HSD_GObjEvent pre_hitlag_cb;
  HSD_GObjEvent post_hitlag_cb;
  HSD_GObjEvent take_dmg_cb;
  HSD_GObjEvent death1_cb;
  HSD_GObjEvent death2_cb;
  HSD_GObjEvent death3_cb;
  HSD_GObjEvent x21EC;
  HSD_GObjEvent take_dmg_2_cb;
  HSD_GObjEvent hurtbox_detect_cb;
  HSD_GObjEvent x21F8;
  UnkFlagStruct x21FC_flag;
  u8 filler_x21FC[0x2200 - 0x21FD];
  u32 cmd_vars[4];
  union 
  {
    u32 throw_flags;
    struct 
    {
      u8 throw_flags_b0 : 1;
      u8 throw_flags_b1 : 1;
      u8 throw_flags_b2 : 1;
      u8 throw_flags_b3 : 1;
      u8 throw_flags_b4 : 1;
      u8 throw_flags_b5 : 1;
      u8 throw_flags_b6 : 1;
      u8 throw_flags_b7 : 1;
    };
  };
  float cmd_timer;
  u8 allow_interrupt : 1;
  u8 x2218_b1 : 1;
  u8 x2218_b2 : 1;
  u8 reflecting : 1;
  u8 x2218_b4 : 1;
  u8 x2218_b5 : 1;
  u8 x2218_b6 : 1;
  u8 x2218_b7 : 1;
  u8 x2219_b0 : 1;
  u8 x2219_b1 : 1;
  u8 x2219_b2 : 1;
  u8 x2219_b3 : 1;
  u8 x2219_b4 : 1;
  u8 x2219_b5 : 1;
  u8 x2219_b6 : 1;
  u8 x2219_b7 : 1;
  u8 x221A_b0 : 1;
  u8 x221A_b1 : 1;
  u8 x221A_b2 : 1;
  u8 x221A_b3 : 1;
  u8 fall_fast : 1;
  u8 x221A_b5 : 1;
  u8 x221A_b6 : 1;
  u8 x221A_b7 : 1;
  struct 
  {
    u8 x221B_b0 : 1;
    u8 x221B_b1 : 1;
    u8 x221B_b2 : 1;
    u8 x221B_b3 : 1;
    u8 x221B_b4 : 1;
    u8 x221B_b5 : 1;
    u8 x221B_b6 : 1;
    u8 x221B_b7 : 1;
  };
  u16 x221C_b0 : 1;
  u16 x221C_b1 : 1;
  u16 x221C_b2 : 1;
  u16 x221C_b3 : 1;
  u16 x221C_b4 : 1;
  u16 x221C_b5 : 1;
  u16 x221C_b6 : 1;
  u16 x221C_u16_y : 3;
  u16 x221D_b2 : 1;
  u16 x221D_b3 : 1;
  u16 x221D_b4 : 1;
  u16 x221D_b5 : 1;
  u16 x221D_b6 : 1;
  u16 x221D_b7 : 1;
  u8 invisible : 1;
  u8 x221E_b1 : 1;
  u8 x221E_b2 : 1;
  u8 x221E_b3 : 1;
  u8 x221E_b4 : 1;
  u8 x221E_b5 : 1;
  u8 x221E_b6 : 1;
  u8 x221E_b7 : 1;
  u8 x221F_b0 : 1;
  u8 x221F_b1 : 1;
  u8 x221F_b2 : 1;
  u8 x221F_b3 : 1;
  u8 x221F_b4 : 1;
  u8 x221F_b5 : 1;
  u8 x221F_b6 : 1;
  u8 x221F_b7 : 1;
  u8 x2220_b0 : 3;
  u8 x2220_b3 : 1;
  u8 x2220_b4 : 1;
  u8 x2220_b5 : 1;
  u8 x2220_b6 : 1;
  u8 x2220_b7 : 1;
  u8 x2221_b0 : 1;
  u8 x2221_b1 : 1;
  u8 x2221_b2 : 1;
  u8 x2221_b3 : 1;
  u8 x2221_b4 : 1;
  u8 x2221_b5 : 1;
  u8 x2221_b6 : 1;
  u8 x2221_b7 : 1;
  u8 x2222_b0 : 1;
  u8 can_multijump : 1;
  u8 x2222_b2 : 1;
  u8 x2222_b3 : 1;
  u8 x2222_b4 : 1;
  u8 x2222_b5 : 1;
  u8 x2222_b6 : 1;
  u8 x2222_b7 : 1;
  u8 x2223_b0 : 1;
  u8 x2223_b1 : 1;
  u8 x2223_b2 : 1;
  u8 x2223_b3 : 1;
  u8 x2223_b4 : 1;
  u8 x2223_b5 : 1;
  u8 is_always_metal : 1;
  u8 is_metal : 1;
  u8 x2224_b0 : 1;
  u8 x2224_b1 : 1;
  u8 x2224_b2 : 1;
  u8 x2224_b3 : 1;
  u8 x2224_b4 : 1;
  u8 x2224_b5 : 1;
  u8 x2224_b6 : 1;
  u8 can_walljump : 1;
  u8 x2225_b0 : 1;
  u8 x2225_b1 : 1;
  u8 x2225_b2 : 1;
  u8 x2225_b3 : 1;
  u8 x2225_b4 : 1;
  u8 x2225_b5 : 1;
  u8 x2225_b6 : 1;
  u8 x2225_b7 : 1;
  u8 x2226_b0 : 1;
  u8 x2226_b1 : 1;
  u8 x2226_b2 : 1;
  u8 x2226_b3 : 1;
  u8 x2226_b4 : 1;
  u8 x2226_b5 : 1;
  u8 x2226_b6 : 1;
  u8 x2226_b7 : 1;
  u8 x2227_b0 : 1;
  u8 x2227_b1 : 1;
  u8 x2227_b2 : 1;
  u8 x2227_b3 : 1;
  u8 x2227_b4 : 1;
  u8 x2227_b5 : 1;
  u8 x2227_b6 : 1;
  u8 x2227_b7 : 1;
  u8 x2228_b0 : 1;
  u8 x2228_b1 : 1;
  u8 x2228_b2 : 1;
  u8 x2228_b3 : 2;
  u8 x2228_b5 : 1;
  u8 used_tether : 1;
  u8 x2228_b7 : 1;
  u8 x2229_b0 : 1;
  u8 x2229_b1 : 1;
  u8 x2229_b2 : 1;
  u8 x2229_b3 : 1;
  u8 x2229_b4 : 1;
  u8 no_normal_motion : 1;
  u8 x2229_b6 : 1;
  u8 no_kb : 1;
  u8 x222A_b0 : 1;
  u8 x222A_b1 : 1;
  u8 x222A_b2 : 1;
  u8 x222A_b3 : 2;
  u8 x222A_b5 : 1;
  u8 x222A_b6 : 1;
  u8 x222A_b7 : 1;
  union Fighter_FighterVars
  {
    struct ftCaptain_FighterVars ca;
    struct ftCaptain_FighterVars gn;
    struct ftDonkey_FighterVars dk;
    struct ftFox_FighterVars fx;
    struct ftFox_FighterVars fc;
    struct ftGameWatch_FighterVars gw;
    struct ftKb_FighterVars kb;
    struct ftKoopa_FighterVars kp;
    struct ftKoopa_FighterVars gk;
    struct ftLk_FighterVars lk;
    struct ftLuigi_FighterVars lg;
    struct ftMario_FighterVars mr;
    struct ftMars_FighterVars ms;
    struct ftMasterhand_FighterVars mh;
    struct ftMasterhand_FighterVars ch;
    struct ftMewtwo_FighterVars mt;
    struct ftNess_FighterVars ns;
    struct ftPeach_FighterVars pe;
    struct ftPikachu_FighterVars pk;
    struct ftPikachu_FighterVars pc;
    struct ftPopo_FighterVars pp;
    struct ftPopo_FighterVars nn;
    struct ftPurin_FighterVars pr;
    struct ftSamus_FighterVars ss;
    struct ftSandbag_FighterVars sb;
    struct ftSeak_FighterVars sk;
    struct ftYoshi_FighterVars ys;
    struct ftZakoBoy_FighterVars bo;
    struct ftZakoBoy_FighterVars gl;
    struct ftZelda_FighterVars zd;
  } fv;
  InternalStageId bury_stage_kind;
  u32 bury_timer_1;
  u32 bury_timer_2;
  IntVec2 x2330;
  IntVec2 x2338;
  union Fighter_MotionVars
  {
    u8 _[0x23EC - 0x2340];
    union ftCaptain_MotionVars ca;
    union ftCaptain_MotionVars gn;
    union ftCommon_MotionVars co;
    union ftDonkey_MotionVars dk;
    union ftFox_MotionVars fx;
    union ftFox_MotionVars fc;
    union ftGameWatch_MotionVars gw;
    union ftKb_MotionVars kb;
    union ftKoopa_MotionVars kp;
    union ftLk_MotionVars lk;
    union ftLuigi_MotionVars lg;
    union ftMario_MotionVars mr;
    union ftMario_MotionVars dr;
    union ftMars_MotionVars ms;
    union ftMars_MotionVars fe;
    union ftMasterHand_MotionVars mh;
    union ftMasterHand_MotionVars ch;
    union ftMewtwo_MotionVars mt;
    union ftNess_MotionVars ns;
    union ftPe_MotionVars pe;
    union ftPikachu_MotionVars pk;
    union ftPikachu_MotionVars pc;
    union ftPp_MotionVars pp;
    union ftPurin_MotionVars pr;
    union ftSamus_MotionVars ss;
    union ftSeak_MotionVars sk;
    union ftYoshi_MotionVars ys;
    union ftZelda_MotionVars zd;
  } mv;
};
struct gmScriptEventDefault
{
  u32 opcode : 6;
  u32 value1 : 26;
};
struct ftData_UnkCountStruct
{
  void *data;
  int count;
};
struct UnkFloat6_Camera
{
  Vec3 x0;
  Vec3 xC;
};
typedef struct ftData_UnkModelStruct
{
  Fighter_ModelEvent model_events[FTKIND_MAX];
  HSD_JObj *(*getter[FTKIND_MAX])(HSD_GObj *);
} ftData_UnkModelStruct;
struct ftData_80085FD4_ret
{
  const char *x0;
  void *x4;
  size_t x8;
  void *xC;
  u8 x10_b0 : 1;
  u8 x10_b1 : 1;
  u32 x14;
};
typedef struct ArticleDynamicBones
{
  BoneDynamicsDesc array[Ft_Dynamics_NumMax];
} ArticleDynamicBones;
typedef struct ftDynamics
{
  struct 
  {
    int dynamicsNum;
    ArticleDynamicBones *ftDynamicBones;
  };
  int x4;
  void *x8;
  FigaTree ***x10;
} ftDynamics;
typedef struct KirbyHatStruct
{
  HSD_Joint *hat_joint;
  u32 joint_num;
  void *hat_vis_table;
  ftDynamics *hat_dynamics[5];
} KirbyHatStruct;
typedef struct Kirby_Unk
{
  HSD_Joint *x0;
  HSD_Joint *x4;
  void *x8;
  void *xC;
  ftDynamics *x10;
  void *x14;
  ftDynamics *x18;
  ftDynamics *x1C;
} Kirby_Unk;
struct ft_80459B88_t
{
  Kirby_Unk *x0;
  KirbyHatStruct *hats[FTKIND_MAX];
};
typedef struct DmgLogEntry
{
  enum EntityKind x0;
  FighterKind kind;
  HSD_GObj *gobj;
  union 
  {
    HitCapsule *hit0;
    DynamicsDesc *unk_anim0;
  };
  union 
  {
    HitCapsule *hit1;
    FighterHurtCapsule *hurt1;
  };
  Vec3 pos;
  int x20;
  size_t size_of_xC;
} DmgLogEntry;
s32 ftLib_800860C4(void);
bool ftLib_IsMasterHandPresent(void);
bool ftLib_IsCrazyHandPresent(void);
HSD_GObj *ftLib_80086198(HSD_GObj *);
HSD_GObj *ftLib_8008627C(Vec3 *pos, HSD_GObj *);
HSD_GObj *ftLib_80086368(Vec3 *, HSD_GObj *, float);
float ftLib_800864A8(Vec3 *, HSD_GObj *);
float ftLib_800865C0(HSD_GObj *);
s32 ftLib_800865CC(HSD_GObj *);
void ftLib_800865D8(HSD_GObj *, float *, float *);
void *ftLib_800865F0(HSD_GObj *);
void *ftLib_80086630(Fighter_GObj *, Fighter_Part part);
void ftLib_80086644(HSD_GObj *, Vec3 *);
void ftLib_80086664(HSD_GObj *, Vec3 *);
void ftLib_80086684(HSD_GObj *, Vec3 *);
void ftLib_SetScale(HSD_GObj *, float);
void ftLib_800866DC(HSD_GObj *, Vec3 *);
void ftLib_80086724(HSD_GObj *, HSD_GObj *);
void ftLib_80086764(HSD_GObj *);
HSD_GObj *ftLib_80086794(HSD_GObj *);
bool ftLib_800867A0(HSD_GObj *, HSD_GObj *);
HSD_GObj *ftLib_800867CC(HSD_GObj *);
bool ftLib_800867D8(HSD_GObj *);
void ftLib_800867E8(HSD_GObj *);
void ftLib_80086824(void);
void ftLib_8008688C(HSD_GObj *);
void ftLib_800868A4(void);
bool ftLib_800868D4(HSD_GObj *, HSD_GObj *);
bool ftLib_80086960(HSD_GObj *gobj);
CollData *ftLib_80086984(HSD_GObj *);
void ftLib_80086990(HSD_GObj *, Vec3 *);
float ftLib_800869D4(HSD_GObj *);
float ftLib_800869F8(HSD_GObj *);
float ftLib_80086A0C(HSD_GObj *);
bool ftLib_80086A18(HSD_GObj *);
void ftLib_80086A4C(HSD_GObj *, float);
bool ftLib_80086A58(HSD_GObj *, S32Vec2 *);
bool ftLib_80086A8C(HSD_GObj *);
bool ftLib_80086B64(HSD_GObj *);
CmSubject *ftLib_80086B74(HSD_GObj *);
float ftLib_80086B80(HSD_GObj *);
void ftLib_80086B90(HSD_GObj *, Vec3 *v);
bool ftLib_80086BB4(HSD_GObj *);
u8 ftLib_80086BE0(HSD_GObj *);
void ftLib_80086BEC(HSD_GObj *, Vec3 *);
enum_t ftLib_80086C0C(HSD_GObj *);
void ftLib_80086C18(HSD_GObj *, s32, s32);
void ftLib_80086C9C(s32, s32);
void ftLib_80086D40(HSD_GObj *, s32, s32);
void ftLib_80086DC4(s32, s32);
void ftLib_80086E68(HSD_GObj *);
s32 ftLib_80086EB4(HSD_GObj *);
bool ftLib_80086EC0(HSD_GObj *);
bool ftLib_80086ED0(HSD_GObj *);
bool ftLib_80086F4C(HSD_GObj *);
float ftLib_80086F80(HSD_GObj *);
bool ftLib_80086FA8(HSD_GObj *);
bool ftLib_80086FD4(HSD_GObj *, HSD_GObj *);
bool ftLib_8008701C(HSD_GObj *);
void ftLib_8008702C(s32);
void ftLib_80087050(s32);
bool ftLib_80087074(HSD_GObj *, Vec3 *);
bool ftLib_800870BC(HSD_GObj *, void **);
void ftLib_800870F0(HSD_GObj *, s32);
s32 ftLib_80087120(HSD_GObj *);
void ftLib_80087140(HSD_GObj *);
void ftLib_800871A8(Fighter_GObj *, Item_GObj *);
bool ftLib_80087284(HSD_GObj *);
FighterKind ftLib_800872A4(HSD_GObj *);
LbShadow *ftLib_800872B0(HSD_GObj *);
bool ftLib_800872BC(HSD_GObj *);
s32 ftLib_80087300(HSD_GObj *);
s32 ftLib_8008730C(HSD_GObj *);
s32 ftLib_8008731C(HSD_GObj *);
bool ftLib_8008732C(HSD_GObj *);
bool ftLib_80087354(HSD_GObj *);
bool ftLib_8008737C(HSD_GObj *);
bool ftLib_800873A4(HSD_GObj *);
bool ftLib_800873CC(HSD_GObj *);
bool ftLib_800873F4(HSD_GObj *);
HSD_GObj *ftLib_8008741C(u32);
float ftLib_80087454(HSD_GObj *);
u32 ftLib_80087460(HSD_GObj *);
s32 ftLib_8008746C(HSD_GObj *);
s32 ftLib_800874BC(HSD_GObj *);
void ftLib_800874CC(HSD_GObj *, void *, s32);
void ftLib_80087508(s8, u8);
void ftLib_80087574(s8);
void ftLib_80087610(u8);
void ftLib_800876B4(HSD_GObj *);
bool ftLib_800876D4(HSD_GObj *);
s32 ftLib_800876F4(HSD_GObj *);
s32 ftLib_80087700(HSD_GObj *);
void ftLib_8008770C(HSD_GObj *, void *dst);
void ftLib_80087744(HSD_GObj *, void *dst);
float ftLib_8008777C(HSD_GObj *);
bool ftLib_800877D4(HSD_GObj *);
void grDynamicAttr_801CA0B4(void);
grDynamicAttr_UnkStruct *grDynamicAttr_801CA0F8(s32 arg0, Vec3 *v, enum_t floor_id, f32 f, s32 arg3);
void grDynamicAttr_801CA1C0(grDynamicAttr_UnkStruct *arg);
void grDynamicAttr_801CA224(void);
int grDynamicAttr_801CA284(Vec3 *v, int arg1);
float it_8026B1D4(Item_GObj *gobj, HitCapsule *itemHitboxUnk);
void it_8026B294(Item_GObj *gobj, Vec3 *pos);
enum_t it_8026B2B4(Item_GObj *gobj);
bool it_8026B2D8(Item_GObj *gobj);
s32 itGetKind(Item_GObj *gobj);
enum_t it_8026B30C(Item_GObj *gobj);
enum_t it_8026B320(Item_GObj *gobj);
float it_8026B334(Item_GObj *gobj);
void it_8026B344(Item_GObj *gobj, Vec3 *pos);
float it_8026B378(Item_GObj *gobj);
float it_8026B384(Item_GObj *gobj);
void it_8026B390(Item_GObj *gobj);
void it_8026B3A8(Item_GObj *gobj);
int it_8026B3C0(ItemKind kind);
void it_8026B3F8(Article *article, s32 kind);
void it_8026B40C(Article *article, s32 kind);
float it_8026B424(s32 damage);
s32 it_8026B47C(Item_GObj *gobj);
bool it_8026B4F0(Item_GObj *gobj);
float it_8026B54C(Item_GObj *gobj);
float it_8026B560(Item_GObj *gobj);
float it_8026B574(Item_GObj *gobj);
s32 it_8026B588(void);
bool it_8026B594(Item_GObj *gobj);
HSD_GObj *it_8026B5E4(Vec3 *vector, Vec3 *vector2, Item_GObj *gobj);
HSD_GObj *it_8026B634(Vec3 *vector, Vec3 *vector2, Item_GObj *gobj);
float it_8026B684(Vec3 *pos);
float it_8026B6A8(Vec3 *pos, HSD_GObj *arg);
bool it_8026B6C8(Item_GObj *gobj);
void it_8026B718(Item_GObj *gobj, float hitlagFrames);
void it_8026B724(Item_GObj *gobj);
void it_8026B73C(Item_GObj *gobj);
bool it_8026B774(Item_GObj *gobj, u8 arg1);
s32 it_8026B7A4(Item_GObj *gobj);
u8 it_8026B7B0(Item_GObj *gobj);
s32 it_8026B7BC(Item_GObj *gobj);
s32 it_8026B7CC(Item_GObj *gobj);
s32 it_8026B7D8(void);
s32 it_8026B7E0(void);
s32 it_8026B7E8(Item_GObj *gobj);
void it_8026B7F8(Item_GObj *gobj);
bool it_8026B894(Item_GObj *gobj, HSD_GObj *referenced_gobj);
s32 it_8026B924(Item_GObj *gobj);
float it_8026B960(Item_GObj *gobj);
void it_8026B9A8(Item_GObj *gobj, HSD_GObj *arg1, Fighter_Part arg2);
void it_8026BAE8(Item_GObj *gobj, float scale_mul);
void it_8026BB20(Item_GObj *gobj);
void it_8026BB44(Item_GObj *gobj);
void it_8026BB68(Item_GObj *gobj, Vec3 *pos);
void it_8026BB88(Item_GObj *gobj, Vec3 *pos);
void it_8026BBCC(Item_GObj *gobj, Vec3 *pos);
void it_8026BC14(Item_GObj *gobj);
bool it_8026BC68(Item_GObj *gobj);
HSD_GObj *it_8026BC78(Item_GObj *gobj);
bool it_8026BC84(Item_GObj *gobj);
void it_8026BC90(Item_GObj *gobj, Vec3 *pos);
void it_8026BCF4(Item_GObj *gobj);
void it_8026BD0C(Item_GObj *gobj);
void it_8026BD24(Item_GObj *gobj);
void it_8026BD3C(Item_GObj *gobj);
void it_8026BD54(Item_GObj *gobj);
void it_8026BD6C(Item_GObj *gobj);
void it_8026BD84(Item_GObj *gobj);
void it_8026BD9C(Item_GObj *gobj);
void it_8026BDB4(Item_GObj *gobj);
void it_8026BDCC(Item_GObj *gobj);
void it_8026BE28(Item_GObj *gobj);
HSD_GObj *it_8026BE84(BobOmbRain *bobOmbRain);
CollData *it_8026C100(Item_GObj *gobj);
void it_8026C16C(Item_GObj *gobj, bool isHeadless);
bool it_8026C1B4(Item_GObj *gobj);
u32 it_8026C1D4(void);
bool it_8026C1E8(Item_GObj *gobj);
void it_8026C220(Item_GObj *gobj, HSD_GObj *arg1);
HSD_GObj *it_8026C258(Vec3 *vector, float facingDir);
void it_8026C334(Item_GObj *gobj, Vec3 *pos);
void it_8026C368(Item_GObj *gobj);
void it_8026C3FC(void);
void it_8026C42C(void);
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
typedef struct _HSD_FreeList
{
  struct _HSD_FreeList *next;
} HSD_FreeList;
typedef struct _HSD_MemoryEntry
{
  u32 size;
  u32 nb_alloc;
  u32 nb_free;
  struct _HSD_FreeList *free_list;
  struct _HSD_MemoryEntry *next;
} HSD_MemoryEntry;
extern HSD_ClassInfo hsdClass;
void ClassInfoInit(HSD_ClassInfo *info);
void hsdInitClassInfo(HSD_ClassInfo *class_info, HSD_ClassInfo *parent_info, char *base_class_library, char *type, s32 info_size, s32 class_size);
void OSReport_PrintSpaces(s32 count);
void *hsdAllocMemPiece(s32 size);
void hsdFreeMemPiece(void *mem, s32 size);
void *hsdNew(HSD_ClassInfo *);
bool hsdChangeClass(void *object, void *class_info);
bool hsdIsDescendantOf(void *info, void *p);
bool hsdObjIsDescendantOf(HSD_Obj *o, HSD_ClassInfo *p);
HSD_ClassInfo *hsdSearchClassInfo(const char *class_name);
void hsdForgetClassLibrary(const char *library_name);
HSD_MemoryEntry *GetMemoryEntry(s32 idx);
HSD_Class *_hsdClassAlloc(HSD_ClassInfo *info);
int _hsdClassInit(HSD_Class *arg0);
void _hsdClassRelease(HSD_Class *cls);
void _hsdClassDestroy(HSD_Class *cls);
void _hsdClassAmnesia(HSD_ClassInfo *info);
void class_set_flags(HSD_ClassInfo *class_info, s32 set, s32 reset);
void ForgetClassLibraryReal(HSD_ClassInfo *class_info);
void DumpClassStat(HSD_ClassInfo *info, s32 level);
void hsdDumpClassStat(HSD_ClassInfo *info, bool recursive, s32 level);
void ForgetClassLibraryChild(const char *library_name, HSD_ClassInfo *class_info);
inline static void hsdDelete(void *object)
{
  if (object == 0L)
  {
    return;
  }
  ((HSD_Class *) object)->class_info->release((HSD_Class *) object);
  ((HSD_Class *) object)->class_info->destroy((HSD_Class *) object);
}

typedef void (*ReportCallback)(const unsigned char *, size_t);
typedef void (*PanicCallback)(OSContext *, ...);
void __assert(char *, u32, char *);
void HSD_LogInit(void);
void HSD_Panic(char *, u32, char *);
int report_func(__file_handle arg0, unsigned char *arg1, size_t *arg2, __idle_proc arg3);
void HSD_SetReportCallback(ReportCallback cb);
void HSD_SetPanicCallback(PanicCallback cb);
typedef struct _objheap
{
  u32 top;
  u32 curr;
  u32 size;
  u32 remain;
} objheap;
typedef struct _HSD_ObjAllocLink
{
  struct _HSD_ObjAllocLink *next;
} HSD_ObjAllocLink;
typedef struct _HSD_ObjAllocData
{
  u32 num_limit_flag : 1;
  u32 heap_limit_flag : 1;
  HSD_ObjAllocLink *freehead;
  u32 used;
  u32 free;
  u32 peak;
  u32 num_limit;
  u32 heap_limit_size;
  u32 heap_limit_num;
  u32 size;
  u32 align;
  struct _HSD_ObjAllocData *next;
} HSD_ObjAllocData;
inline static u32 HSD_ObjAllocGetUsing(HSD_ObjAllocData *data)
{
  (data) ? ((void) 0) : (__assert("src/sysdolphin/baselib/objalloc.h", 205, "data"));
  return data->used;
}

inline static u32 HSD_ObjAllocGetFreed(HSD_ObjAllocData *data)
{
  (data) ? ((void) 0) : (__assert("src/sysdolphin/baselib/objalloc.h", 221, "data"));
  return data->free;
}

inline static u32 HSD_ObjAllocGetPeak(HSD_ObjAllocData *data)
{
  (data) ? ((void) 0) : (__assert("src/sysdolphin/baselib/objalloc.h", 237, "data"));
  return data->peak;
}

inline static void HSD_ObjAllocSetNumLimit(HSD_ObjAllocData *data, u32 num_limit)
{
  (data) ? ((void) 0) : (__assert("src/sysdolphin/baselib/objalloc.h", 251, "data"));
  data->num_limit = num_limit;
}

inline static void HSD_ObjAllocEnableNumLimit(HSD_ObjAllocData *data)
{
  (data) ? ((void) 0) : (__assert("src/sysdolphin/baselib/objalloc.h", 278, "data"));
  data->num_limit_flag = 1;
}

inline static void HSD_ObjAllocDisableNumLimit(HSD_ObjAllocData *data)
{
  (data) ? ((void) 0) : (__assert("src/sysdolphin/baselib/objalloc.h", 291, "data"));
  data->num_limit_flag = 0;
}

void HSD_ObjSetHeap(u32 size, void *ptr);
s32 HSD_ObjAllocAddFree(HSD_ObjAllocData *data, u32 num);
void *HSD_ObjAlloc(HSD_ObjAllocData *data);
void HSD_ObjFree(HSD_ObjAllocData *data, void *obj);
void _HSD_ObjAllocForgetMemory(void *low, void *high);
void HSD_ObjAllocInit(HSD_ObjAllocData *data, size_t size, u32 align);
typedef struct _HSD_SList
{
  struct _HSD_SList *next;
  void *data;
} HSD_SList;
typedef struct _HSD_DList
{
  struct _HSD_DList *next;
  struct _HSD_DList *prev;
  void *data;
} HSD_DList;
void HSD_ListInitAllocData(void);
HSD_ObjAllocData *HSD_SListGetAllocData(void);
HSD_ObjAllocData *HSD_DListGetAllocData(void);
HSD_SList *HSD_SListAlloc(void);
HSD_SList *HSD_SListAllocAndAppend(HSD_SList *next, void *data);
HSD_SList *HSD_SListAllocAndPrepend(HSD_SList *prev, void *data);
HSD_SList *HSD_SListAppendList(HSD_SList *list, HSD_SList *next);
HSD_SList *HSD_SListPrependList(HSD_SList *list, HSD_SList *prev);
HSD_SList *HSD_SListRemove(HSD_SList *list);
typedef enum _HSD_Type
{
  AOBJ_TYPE = 1,
  COBJ_TYPE,
  DOBJ_TYPE,
  FOBJ_TYPE,
  FOG_TYPE,
  JOBJ_TYPE,
  LOBJ_TYPE,
  MOBJ_TYPE,
  POBJ_TYPE,
  ROBJ_TYPE,
  TOBJ_TYPE,
  WOBJ_TYPE,
  RENDER_TYPE,
  CHAN_TYPE,
  TEVREG_TYPE,
  CBOBJ_TYPE,
  HSD_MAX_TYPE
} HSD_Type;
typedef enum _HSD_TypeMask
{
  AOBJ_MASK = 1 << (AOBJ_TYPE - 1),
  COBJ_MASK = 1 << (COBJ_TYPE - 1),
  DOBJ_MASK = 1 << (DOBJ_TYPE - 1),
  FOBJ_MASK = 1 << (FOBJ_TYPE - 1),
  FOG_MASK = 1 << (FOG_TYPE - 1),
  JOBJ_MASK = 1 << (JOBJ_TYPE - 1),
  LOBJ_MASK = 1 << (LOBJ_TYPE - 1),
  MOBJ_MASK = 1 << (MOBJ_TYPE - 1),
  POBJ_MASK = 1 << (POBJ_TYPE - 1),
  ROBJ_MASK = 1 << (ROBJ_TYPE - 1),
  TOBJ_MASK = 1 << (TOBJ_TYPE - 1),
  WOBJ_MASK = 1 << (WOBJ_TYPE - 1),
  RENDER_MASK = 1 << (RENDER_TYPE - 1),
  CHAN_MASK = 1 << (CHAN_TYPE - 1),
  TEVREG_MASK = 1 << (TEVREG_TYPE - 1),
  CBOBJ_MASK = 1 << (CBOBJ_TYPE - 1),
  ALL_TYPE_MASK = (1 << (HSD_MAX_TYPE - 1)) - 1
} HSD_TypeMask;
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
extern HSD_ClassInfo hsdObj;
void ObjInfoInit(void);
inline static bool ref_DEC(void *o)
{
  bool ret;
  if (ret = ((HSD_Obj *) o)->ref_count == ((u16) (-1)))
  {
    return ret;
  }
  return (((HSD_Obj *) o)->ref_count--) == 0;
}

inline static void ref_INC(void *o)
{
  if (o != 0L)
  {
    ((HSD_Obj *) o)->ref_count++;
    (((HSD_Obj *) o)->ref_count != ((u16) (-1))) ? ((void) 0) : (__assert("src/sysdolphin/baselib/object.h", 93, "HSD_OBJ(o)->ref_count != HSD_OBJ_NOREF"));
  }
}

inline static int ref_CNT(void *o)
{
  if (((HSD_Obj *) o)->ref_count == ((u16) (-1)))
  {
    return -1;
  }
  else
  {
    return ((HSD_Obj *) o)->ref_count;
  }
}

inline static int iref_CNT(void *o)
{
  return ((HSD_Obj *) o)->ref_count_individual;
}

inline static bool iref_DEC(void *o)
{
  bool ret;
  if (ret = ((HSD_Obj *) o)->ref_count_individual == 0)
  {
    return ret;
  }
  ((HSD_Obj *) o)->ref_count_individual -= 1;
  return ((HSD_Obj *) o)->ref_count_individual == 0;
}

inline static void iref_INC(void *o)
{
  ((HSD_Obj *) o)->ref_count_individual++;
  (((HSD_Obj *) o)->ref_count_individual != 0) ? ((void) 0) : (__assert("src/sysdolphin/baselib/object.h", 158, "HSD_OBJ(o)->ref_count_individual != 0"));
}

typedef struct _HSD_FObj
{
  struct _HSD_FObj *next;
  u8 *ad;
  u8 *ad_head;
  u32 length;
  u8 flags;
  u8 op;
  u8 op_intrp;
  u8 obj_type;
  u8 frac_value;
  u8 frac_slope;
  u16 nb_pack;
  s16 startframe;
  u16 fterm;
  f32 time;
  f32 p0;
  f32 p1;
  f32 d0;
  f32 d1;
} HSD_FObj;
typedef struct _HSD_FObjDesc
{
  struct _HSD_FObjDesc *next;
  u32 length;
  f32 startframe;
  u8 type;
  u8 frac_value;
  u8 frac_slope;
  u8 dummy0;
  u8 *ad;
} HSD_FObjDesc;
union HSD_ObjData
{
  f32 fv;
  s32 iv;
  Vec3 p;
};
HSD_ObjAllocData *HSD_FObjGetAllocData(void);
void HSD_FObjInitAllocData(void);
void HSD_FObjRemove(HSD_FObj *fobj);
void HSD_FObjRemoveAll(HSD_FObj *fobj);
u32 HSD_FObjSetState(HSD_FObj *fobj, u32 state);
u32 HSD_FObjGetState(HSD_FObj *fobj);
void HSD_FObjReqAnimAll(HSD_FObj *fobj, f32 startframe);
void HSD_FObjStopAnim(HSD_FObj *fobj, void *obj, HSD_ObjUpdateFunc obj_update, f32 rate);
void HSD_FObjStopAnimAll(HSD_FObj *fobj, void *obj, HSD_ObjUpdateFunc obj_update, f32 rate);
void FObjUpdateAnim(HSD_FObj *fobj, void *obj, HSD_ObjUpdateFunc update_func);
void HSD_FObjInterpretAnim(HSD_FObj *fobj, void *obj, HSD_ObjUpdateFunc obj_update, f32 rate);
void HSD_FObjInterpretAnimAll(void *fobj, void *obj, HSD_ObjUpdateFunc obj_update, f32 rate);
HSD_FObj *HSD_FObjLoadDesc(HSD_FObjDesc *desc);
HSD_FObj *HSD_FObjAlloc(void);
void HSD_FObjFree(HSD_FObj *fobj);
typedef enum _AObj_Arg_Type
{
  AOBJ_ARG_A,
  AOBJ_ARG_AF,
  AOBJ_ARG_AV,
  AOBJ_ARG_AU,
  AOBJ_ARG_AO,
  AOBJ_ARG_AOF,
  AOBJ_ARG_AOV,
  AOBJ_ARG_AOU,
  AOBJ_ARG_AOT,
  AOBJ_ARG_AOTF,
  AOBJ_ARG_AOTV,
  AOBJ_ARG_AOTU
} AObj_Arg_Type;
typedef union _callbackArg
{
  f32 f;
  u32 d;
  void *v;
} callbackArg;
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
struct HSD_AObjDesc
{
  u32 flags;
  f32 end_frame;
  HSD_FObjDesc *fobjdesc;
  u32 obj_id;
};
struct HSD_AnimJoint
{
  HSD_AnimJoint *child;
  HSD_AnimJoint *next;
  HSD_AObjDesc *aobjdesc;
  HSD_RObjAnimJoint *robj_anim;
  u32 flags;
};
void HSD_AObjInitAllocData(void);
HSD_ObjAllocData *HSD_AObjGetAllocData(void);
u32 HSD_AObjGetFlags(HSD_AObj *aobj);
void HSD_AObjSetFlags(HSD_AObj *aobj, u32 flags);
void HSD_AObjClearFlags(HSD_AObj *aobj, u32 flags);
void HSD_AObjSetFObj(HSD_AObj *aobj, HSD_FObj *fobj);
void HSD_AObjInitEndCallBack(void);
void HSD_AObjInvokeCallBacks(void);
void HSD_AObjReqAnim(HSD_AObj *aobj, f32 frame);
void HSD_AObjStopAnim(HSD_AObj *aobj, void *obj, HSD_ObjUpdateFunc func);
void HSD_AObjInterpretAnim(HSD_AObj *aobj, void *obj, HSD_ObjUpdateFunc update_func);
float fmod(float x, float y);
HSD_AObj *HSD_AObjLoadDesc(HSD_AObjDesc *aobjdesc);
void HSD_AObjRemove(HSD_AObj *aobj);
HSD_AObj *HSD_AObjAlloc(void);
void HSD_AObjFree(HSD_AObj *aobj);
void HSD_ForeachAnim(void *obj, HSD_Type type, HSD_TypeMask mask, void *func, AObj_Arg_Type arg_type, ...);
void HSD_AObjSetRate(HSD_AObj *aobj, f32 rate);
void HSD_AObjSetRewindFrame(HSD_AObj *aobj, f32 frame);
void HSD_AObjSetEndFrame(HSD_AObj *aobj, f32 frame);
void HSD_AObjSetCurrentFrame(HSD_AObj *aobj, f32 frame);
void _HSD_AObjForgetMemory(void *low, void *high);
inline static f32 HSD_AObjGetCurrFrame(HSD_AObj *aobj)
{
  (aobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/aobj.h", 0x92, "aobj"));
  return aobj->curr_frame;
}

inline static f32 HSD_AObjGetEndFrame(HSD_AObj *aobj)
{
  (aobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/aobj.h", 0xAA, "aobj"));
  return aobj->end_frame;
}

struct _unk_struct_pobj
{
  u32 data[8];
  HSD_AObj *aobj;
};
struct HSD_PObj
{
  HSD_Class parent;
  HSD_PObj *next;
  HSD_VtxDescList *verts;
  u16 flags;
  u16 n_display;
  u8 *display;
  union HSD_PObjUnion
  {
    HSD_JObj *jobj;
    HSD_ShapeSet *shape_set;
    HSD_SList *envelope_list;
    struct _unk_struct_pobj *unk;
  } u;
};
struct HSD_PObjDesc
{
  char *class_name;
  HSD_PObjDesc *next;
  HSD_VtxDescList *verts;
  u16 flags;
  u16 n_display;
  u8 *display;
  union 
  {
    HSD_Joint *joint;
    HSD_ShapeSetDesc *shape_set;
    HSD_EnvelopeDesc **envelope_p;
  } u;
};
struct HSD_VtxDescList
{
  GXAttr attr;
  GXAttrType attr_type;
  GXCompCnt comp_cnt;
  GXCompType comp_type;
  u8 frac;
  u16 stride;
  void *vertex;
};
struct HSD_Envelope
{
  HSD_Envelope *next;
  HSD_JObj *jobj;
  f32 weight;
};
struct HSD_EnvelopeDesc
{
  HSD_Joint *joint;
  f32 weight;
};
struct HSD_ShapeSet
{
  u16 flags;
  u16 nb_shape;
  int nb_vertex_index;
  HSD_VtxDescList *vertex_desc;
  u8 **vertex_idx_list;
  s32 nb_normal_index;
  HSD_VtxDescList *normal_desc;
  u8 **normal_idx_list;
  union 
  {
    f32 *bp;
    f32 bl;
  } blend;
  HSD_AObj *aobj;
};
struct HSD_ShapeSetDesc
{
  u16 flags;
  u16 nb_shape;
  s32 nb_vertex_index;
  HSD_VtxDescList *vertex_desc;
  u8 **vertex_idx_list;
  s32 nb_normal_index;
  HSD_VtxDescList *normal_desc;
  u8 **normal_idx_list;
};
struct HSD_ShapeAnim
{
  HSD_ShapeAnim *next;
  HSD_AObjDesc *aobjdesc;
};
struct HSD_ShapeAnimJoint
{
  HSD_ShapeAnimJoint *child;
  HSD_ShapeAnimJoint *next;
  HSD_ShapeAnimDObj *shapeanimdobj;
};
struct HSD_PObjInfo
{
  HSD_ClassInfo parent;
  void (*disp)(HSD_PObj *pobj, Mtx vmtx, Mtx pmtx, u32 rendermode);
  void (*setup_mtx)(HSD_PObj *pobj, Mtx vmtx, Mtx pmtx, u32 rendermode);
  s32 (*load)(HSD_PObj *pobj, HSD_PObjDesc *desc);
};
extern HSD_PObjInfo hsdPObj;
HSD_PObjInfo *HSD_PObjGetDefaultClass(void);
void HSD_PObjSetDefaultClass(HSD_PObjInfo *info);
HSD_PObj *HSD_PObjAlloc(void);
void HSD_PObjFree(HSD_PObj *);
u32 HSD_PObjGetFlags(HSD_PObj *pobj);
void HSD_PObjRemoveAnimAllByFlags(HSD_PObj *pobj, u32 flags);
void HSD_PObjReqAnimByFlags(HSD_PObj *pobj, f32 startframe, u32 flags);
void HSD_PObjReqAnimAllByFlags(HSD_PObj *pobj, f32 startframe, u32 flags);
void HSD_ClearVtxDesc(void);
HSD_PObj *HSD_PObjLoadDesc(HSD_PObjDesc *);
void HSD_PObjClearMtxMark(void *obj, u32 mark);
void HSD_PObjSetMtxMark(int idx, void *obj, u32 mark);
void HSD_PObjGetMtxMark(int idx, void **obj, u32 *mark);
void HSD_PObjAddAnim(HSD_PObj *, HSD_ShapeAnim *);
void HSD_PObjAddAnimAll(HSD_PObj *, HSD_ShapeAnim *);
void HSD_PObjAnim(HSD_PObj *pobj);
void HSD_PObjAnimAll(HSD_PObj *);
void HSD_PObjResolveRefs(HSD_PObj *, HSD_PObjDesc *);
void HSD_PObjResolveRefsAll(HSD_PObj *, HSD_PObjDesc *);
void HSD_PObjRemove(HSD_PObj *);
void HSD_PObjRemoveAll(HSD_PObj *);
void HSD_PObjRemoveAnimByFlags(HSD_PObj *pobj, u32 flags);
void HSD_PObjDisp(HSD_PObj *pobj, Mtx vmtx, Mtx pmtx, u32 rendermode);
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
struct HSD_Joint
{
  char *class_name;
  u32 flags;
  HSD_Joint *child;
  HSD_Joint *next;
  union 
  {
    HSD_DObjDesc *dobjdesc;
    HSD_Spline *spline;
    HSD_SList *ptcl;
  } u;
  Vec3 rotation;
  Vec3 scale;
  Vec3 position;
  MtxPtr mtx;
  HSD_RObjDesc *robjdesc;
};
typedef struct _HSD_JObjInfo
{
  HSD_ObjInfo parent;
  s32 (*load)(HSD_JObj *jobj, HSD_Joint *joint, HSD_JObj *jobj_2);
  void (*make_mtx)(HSD_JObj *jobj);
  void (*make_pmtx)(HSD_JObj *jobj, Mtx mtx, Mtx rmtx);
  void (*disp)(HSD_JObj *jobj, Mtx vmtx, Mtx pmtx, HSD_TrspMask trsp_mask, u32 rendermode);
  void (*release_child)(HSD_JObj *jobj);
} HSD_JObjInfo;
extern HSD_JObjInfo hsdJObj;
typedef void (*HSD_JObjWalkTreeCallback)(HSD_JObj *, f32 **, s32);
typedef void (*DPCtlCallback)(int, int lo, int hi, HSD_JObj *jobj);
void HSD_JObjSetDefaultClass(HSD_ClassInfo *info);
void HSD_JObjCheckDepend(HSD_JObj *jobj);
u32 HSD_JObjGetFlags(HSD_JObj *jobj);
void HSD_JObjReqAnimAll(HSD_JObj *, f32);
void HSD_JObjResetRST(HSD_JObj *jobj, HSD_Joint *joint);
void HSD_JObjSetupMatrixSub(HSD_JObj *);
void HSD_JObjSetMtxDirtySub(HSD_JObj *);
void HSD_JObjUnref(HSD_JObj *jobj);
HSD_JObj *HSD_JObjRemove(HSD_JObj *jobj);
void HSD_JObjRemoveAll(HSD_JObj *);
struct HSD_DObj *HSD_JObjGetDObj(HSD_JObj *jobj);
HSD_JObj *HSD_JObjLoadJoint(HSD_Joint *);
void HSD_JObjAddAnimAll(HSD_JObj *, HSD_AnimJoint *, HSD_MatAnimJoint *, HSD_ShapeAnimJoint *);
void HSD_JObjAnimAll(HSD_JObj *);
void HSD_JObjSetFlags(HSD_JObj *, u32 flags);
void HSD_JObjSetFlagsAll(HSD_JObj *, u32 flags);
void HSD_JObjClearFlags(HSD_JObj *, u32 flags);
void HSD_JObjClearFlagsAll(HSD_JObj *, u32 flags);
HSD_JObj *HSD_JObjAlloc(void);
void HSD_JObjSetCurrent(HSD_JObj *jobj);
HSD_JObj *HSD_JObjGetCurrent(void);
void HSD_JObjResolveRefsAll(HSD_JObj *, HSD_Joint *);
void HSD_JObjDispAll(HSD_JObj *jobj, Mtx vmtx, u32 flags, u32 rendermode);
void HSD_JObjRemoveAnim(HSD_JObj *jobj);
void HSD_JObjAddNext(HSD_JObj *jobj, HSD_JObj *next);
void HSD_JObjRemoveAnimAll(HSD_JObj *jobj);
void HSD_JObjWalkTree(HSD_JObj *jobj, HSD_JObjWalkTreeCallback cb, f32 **cb_args);
void HSD_JObjPrependRObj(HSD_JObj *jobj, HSD_RObj *robj);
void HSD_JObjDeleteRObj(HSD_JObj *jobj, HSD_RObj *robj);
inline static HSD_JObj *HSD_JObjGetChild(HSD_JObj *jobj)
{
  if (jobj == 0L)
  {
    return 0L;
  }
  else
  {
    return jobj->child;
  }
}

inline static HSD_JObj *HSD_JObjGetNext(HSD_JObj *jobj)
{
  if (jobj == 0L)
  {
    return 0L;
  }
  else
  {
    return jobj->next;
  }
}

inline static HSD_JObj *HSD_JObjGetParent(HSD_JObj *jobj)
{
  if (jobj == 0L)
  {
    return 0L;
  }
  else
  {
    return jobj->parent;
  }
}

inline static HSD_RObj *HSD_JObjGetRObj(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 405, "jobj"));
  return jobj->robj;
}

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

inline void HSD_JObjSetupMatrix(HSD_JObj *jobj)
{
  if ((!jobj) || (!HSD_JObjMtxIsDirty(jobj)))
  {
    return;
  }
  HSD_JObjSetupMatrixSub(jobj);
}

inline static void HSD_JObjSetMtxDirtyInline(HSD_JObj *jobj)
{
  if ((jobj != 0L) && (!HSD_JObjMtxIsDirty(jobj)))
  {
    HSD_JObjSetMtxDirtySub(jobj);
  }
}

inline static void HSD_JObjSetRotation(HSD_JObj *jobj, Quaternion *rotate)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 618, "jobj"));
  (rotate) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 619, "rotate"));
  jobj->rotate = *rotate;
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

inline static void HSD_JObjSetRotationX(HSD_JObj *jobj, f32 x)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 639, "jobj"));
  (!(jobj->flags & (1 << 17))) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 640, "!(jobj->flags & JOBJ_USE_QUATERNION)"));
  jobj->rotate.x = x;
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

inline static void HSD_JObjSetRotationY(HSD_JObj *jobj, f32 y)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 660, "jobj"));
  (!(jobj->flags & (1 << 17))) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 661, "!(jobj->flags & JOBJ_USE_QUATERNION)"));
  jobj->rotate.y = y;
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

inline static void HSD_JObjSetRotationZ(HSD_JObj *jobj, f32 z)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 681, "jobj"));
  (!(jobj->flags & (1 << 17))) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 682, "!(jobj->flags & JOBJ_USE_QUATERNION)"));
  jobj->rotate.z = z;
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

inline static void HSD_JObjGetRotation(HSD_JObj *jobj, Quaternion *quat)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 699, "jobj"));
  *quat = jobj->rotate;
}

inline static f32 HSD_JObjGetRotationX(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 715, "jobj"));
  return jobj->rotate.x;
}

inline static f32 HSD_JObjGetRotationY(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 730, "jobj"));
  return jobj->rotate.y;
}

inline static f32 HSD_JObjGetRotationZ(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 745, "jobj"));
  return jobj->rotate.z;
}

inline static void HSD_JObjSetScale(HSD_JObj *jobj, Vec3 *scale)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 760, "jobj"));
  (scale) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 761, "scale"));
  jobj->scale = *scale;
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

inline static void HSD_JObjSetScaleX(HSD_JObj *jobj, f32 x)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 776, "jobj"));
  jobj->scale.x = x;
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

inline static void HSD_JObjSetScaleY(HSD_JObj *jobj, f32 y)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 791, "jobj"));
  jobj->scale.y = y;
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

inline static void HSD_JObjSetScaleZ(HSD_JObj *jobj, f32 z)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 806, "jobj"));
  jobj->scale.z = z;
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

inline static void HSD_JObjGetScale(HSD_JObj *jobj, Vec3 *scale)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 823, "jobj"));
  (scale) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 824, "scale"));
  *scale = jobj->scale;
}

inline static f32 HSD_JObjGetScaleX(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 875, "jobj"));
  return jobj->scale.x;
}

inline static f32 HSD_JObjGetScaleY(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 888, "jobj"));
  return jobj->scale.y;
}

inline static f32 HSD_JObjGetScaleZ(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 901, "jobj"));
  return jobj->scale.z;
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

inline static void HSD_JObjSetTranslateX(HSD_JObj *jobj, f32 x)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 932, "jobj"));
  jobj->translate.x = x;
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

inline static void HSD_JObjSetTranslateY(HSD_JObj *jobj, f32 y)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 947, "jobj"));
  jobj->translate.y = y;
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

inline static void HSD_JObjSetTranslateZ(HSD_JObj *jobj, f32 z)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 962, "jobj"));
  jobj->translate.z = z;
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

inline static void HSD_JObjGetTranslation2(HSD_JObj *jobj, Vec3 *translate)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 979, "jobj"));
  *translate = jobj->translate;
}

inline static f32 HSD_JObjGetTranslationX(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 993, "jobj"));
  return jobj->translate.x;
}

inline static f32 HSD_JObjGetTranslationY(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1006, "jobj"));
  return jobj->translate.y;
}

inline static float HSD_JObjGetTranslationZ(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1019, "jobj"));
  return jobj->translate.z;
}

inline static void HSD_JObjAddRotationX(HSD_JObj *jobj, float x)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1029, "jobj"));
  jobj->rotate.x += x;
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

inline static void HSD_JObjAddRotationY(HSD_JObj *jobj, float y)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1041, "jobj"));
  jobj->rotate.y += y;
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

inline static void HSD_JObjAddRotationZ(HSD_JObj *jobj, float z)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1053, "jobj"));
  jobj->rotate.z += z;
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

inline static void HSD_JObjAddScaleX(HSD_JObj *jobj, float x)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1065, "jobj"));
  jobj->scale.x += x;
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

inline static void HSD_JObjAddScaleY(HSD_JObj *jobj, float y)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1077, "jobj"));
  jobj->scale.y += y;
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

inline static void HSD_JObjAddScaleZ(HSD_JObj *jobj, float z)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1089, "jobj"));
  jobj->scale.z += z;
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

inline static void HSD_JObjAddTranslationX(HSD_JObj *jobj, float x)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1102, "jobj"));
  jobj->translate.x += x;
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

inline static void HSD_JObjAddTranslationY(HSD_JObj *jobj, float y)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1114, "jobj"));
  jobj->translate.y += y;
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

inline static void HSD_JObjAddTranslationZ(HSD_JObj *jobj, float z)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1126, "jobj"));
  jobj->translate.z += z;
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

inline static MtxPtr HSD_JObjGetMtxPtr(HSD_JObj *jobj)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1144, "jobj"));
  HSD_JObjSetupMatrix(jobj);
  return jobj->mtx;
}

inline static void HSD_JObjCopyMtx(HSD_JObj *jobj, Mtx mtx)
{
  (jobj) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1170, "jobj"));
  (mtx) ? ((void) 0) : (__assert("src/sysdolphin/baselib/jobj.h", 1171, "mtx"));
  PSMTXCopy(mtx, jobj->mtx);
}

inline static void HSD_JObjRef(HSD_JObj *jobj)
{
  ref_INC(jobj);
}

inline static void HSD_JObjRefThis(HSD_JObj *jobj)
{
  if (jobj != 0L)
  {
    iref_INC(jobj);
  }
}

void HSD_JObjResolveRefs(HSD_JObj *jobj, HSD_Joint *joint);
void HSD_JObjUnrefThis(HSD_JObj *jobj);
void HSD_JObjRefThis(HSD_JObj *jobj);
void HSD_JObjMakeMatrix(HSD_JObj *jobj);
void RecalcParentTrspBits(HSD_JObj *jobj);
void HSD_JObjAddChild(HSD_JObj *jobj, HSD_JObj *child);
HSD_JObj *HSD_JObjReparent(HSD_JObj *jobj, HSD_JObj *parent);
void HSD_JObjAddDObj(HSD_JObj *jobj, HSD_DObj *dobj);
HSD_JObj *jobj_get_effector_checked(HSD_JObj *eff);
void resolveIKJoint1(HSD_JObj *jobj);
void resolveIKJoint2(HSD_JObj *jobj);
void HSD_JObjRemoveAnimByFlags(HSD_JObj *jobj, u32 flags);
void HSD_JObjSetDPtclCallback(DPCtlCallback cb);
int JObjInit(HSD_Class *o);
void JObjReleaseChild(HSD_JObj *jobj);
void JObjRelease(HSD_Class *o);
void HSD_JObjRemoveAnimAllByFlags(HSD_JObj *jobj, u32 flags);
void JObjAmnesia(HSD_ClassInfo *info);
void HSD_JObjReqAnimByFlags(HSD_JObj *jobj, u32 flags, f32 frame);
void HSD_JObjReqAnimAllByFlags(HSD_JObj *jobj, u32 flags, f32 frame);
void HSD_JObjReqAnim(HSD_JObj *jobj, f32 frame);
void JObjSortAnim(HSD_AObj *aobj);
void JObjResetRST(HSD_JObj *jobj, HSD_Joint *joint);
void JObjUpdateFunc(void *obj, enum_t type, HSD_ObjData *val);
void HSD_JObjAnim(HSD_JObj *jobj);
void JObjAnimAll(HSD_JObj *jobj);
s32 JObjLoad(HSD_JObj *jobj, HSD_Joint *joint, HSD_JObj *parent);
void HSD_JObjAddAnim(HSD_JObj *, HSD_AnimJoint *an_joint, HSD_MatAnimJoint *mat_joint, HSD_ShapeAnimJoint *sh_joint);
void HSD_JObjWalkTree0(HSD_JObj *jobj, HSD_JObjWalkTreeCallback cb, f32 **cb_args);
typedef enum _HSD_TEInput
{
  HSD_TE_END = 0,
  HSD_TE_RGB = 1,
  HSD_TE_R = 2,
  HSD_TE_G = 3,
  HSD_TE_B = 4,
  HSD_TE_A = 5,
  HSD_TE_X = 6,
  HSD_TE_0 = 7,
  HSD_TE_1 = 8,
  HSD_TE_1_8 = 9,
  HSD_TE_2_8 = 10,
  HSD_TE_3_8 = 11,
  HSD_TE_4_8 = 12,
  HSD_TE_5_8 = 13,
  HSD_TE_6_8 = 14,
  HSD_TE_7_8 = 15,
  HSD_TE_INPUT_MAX = 16,
  HSD_TE_UNDEF = 0xFF
} HSD_TEInput;
typedef enum _HSD_TEType
{
  HSD_TE_U8 = 0,
  HSD_TE_U16 = 1,
  HSD_TE_U32 = 2,
  HSD_TE_F32 = 3,
  HSD_TE_F64 = 4,
  HSD_TE_COMP_TYPE_MAX = 5
} HSD_TEType;
typedef enum _HSD_TExpType
{
  HSD_TE_ZERO = 0,
  HSD_TE_TEV = 1,
  HSD_TE_TEX = 2,
  HSD_TE_RAS = 3,
  HSD_TE_CNST = 4,
  HSD_TE_IMM = 5,
  HSD_TE_KONST = 6,
  HSD_TE_ALL = 7,
  HSD_TE_TYPE_MAX = 8
} HSD_TExpType;
typedef struct _HSD_TevConf
{
  GXTevOp clr_op;
  GXTevColorArg clr_a;
  GXTevColorArg clr_b;
  GXTevColorArg clr_c;
  GXTevColorArg clr_d;
  GXTevScale clr_scale;
  GXTevBias clr_bias;
  u8 clr_clamp;
  GXTevRegID clr_out_reg;
  GXTevOp alpha_op;
  GXTevAlphaArg alpha_a;
  GXTevAlphaArg alpha_b;
  GXTevAlphaArg alpha_c;
  GXTevAlphaArg alpha_d;
  GXTevScale alpha_scale;
  GXTevBias alpha_bias;
  u8 alpha_clamp;
  GXTevRegID alpha_out_reg;
  GXTevClampMode mode;
  GXTevSwapSel ras_swap;
  GXTevSwapSel tex_swap;
  GXTevKColorSel kcsel;
  GXTevKAlphaSel kasel;
} HSD_TevConf;
typedef struct HSD_TExpRes
{
  int failed;
  int texmap;
  int cnst_remain;
  struct 
  {
    u8 color;
    u8 alpha;
  } reg[8];
  u8 c_ref[4];
  u8 a_ref[4];
  u8 c_use[4];
  u8 a_use[4];
} HSD_TExpRes;
typedef struct _HSD_TevDesc
{
  struct _HSD_TevDesc *next;
  u32 flags;
  u32 stage;
  u32 coord;
  u32 map;
  u32 color;
  union 
  {
    HSD_TevConf tevconf;
    struct 
    {
      u32 tevmode;
    } tevop;
  } u;
} HSD_TevDesc;
typedef struct _HSD_TExpTevDesc
{
  struct _HSD_TevDesc desc;
  HSD_TObj *tobj;
} HSD_TExpTevDesc;
typedef struct _HSD_TECommon
{
  HSD_TExpType type;
  HSD_TExp *next;
} HSD_TECommon;
typedef struct _HSD_TECnst
{
  HSD_TExpType type;
  HSD_TExp *next;
  void *val;
  HSD_TEInput comp;
  HSD_TEType ctype;
  u8 reg;
  u8 idx;
  u8 ref;
  u8 range;
} HSD_TECnst;
typedef struct _HSD_TEArg
{
  u8 type;
  u8 sel;
  u8 arg;
  HSD_TExp *exp;
} HSD_TEArg;
typedef struct _HSD_TETev
{
  HSD_TExpType type;
  HSD_TExp *next;
  s32 c_ref;
  u8 c_dst;
  u8 c_op;
  u8 c_clamp;
  u8 c_bias;
  u8 c_scale;
  u8 c_range;
  s32 a_ref;
  u8 a_dst;
  u8 a_op;
  u8 a_clamp;
  u8 a_bias;
  u8 a_scale;
  u8 tex_swap;
  u8 ras_swap;
  u8 kcsel;
  u8 kasel;
  HSD_TEArg c_in[4];
  HSD_TEArg a_in[4];
  HSD_TObj *tex;
  u8 chan;
} HSD_TETev;
union HSD_TExp
{
  HSD_TExpType type;
  struct _HSD_TECommon comm;
  struct _HSD_TETev tev;
  struct _HSD_TECnst cnst;
};
HSD_TExpType HSD_TExpGetType(HSD_TExp *texp);
HSD_TExp *HSD_TExpTev(HSD_TExp **);
HSD_TExp *HSD_TExpCnst(void *, HSD_TEInput, HSD_TEType, HSD_TExp **);
void HSD_TExpOrder(HSD_TExp *, HSD_TObj *, GXChannelID);
void HSD_TExpColorOp(HSD_TExp *, GXTevOp, GXTevBias, GXTevScale, u8);
void HSD_TExpColorIn(HSD_TExp *, HSD_TEInput, HSD_TExp *, HSD_TEInput, HSD_TExp *, HSD_TEInput, HSD_TExp *, HSD_TEInput, HSD_TExp *);
void HSD_TExpAlphaOp(HSD_TExp *, GXTevOp, GXTevBias, GXTevScale, u8);
void HSD_TExpAlphaIn(HSD_TExp *texp, HSD_TEInput sel_a, HSD_TExp *exp_a, HSD_TEInput sel_b, HSD_TExp *exp_b, HSD_TEInput sel_c, HSD_TExp *exp_c, HSD_TEInput sel_d, HSD_TExp *exp_d);
void HSD_TExpFreeTevDesc(HSD_TExpTevDesc *);
HSD_TExp *HSD_TExpFreeList(HSD_TExp *, HSD_TExpType, s32);
int HSD_TExpCompile(HSD_TExp *, HSD_TExpTevDesc **, HSD_TExp **);
void HSD_TExpSetupTev(HSD_TExpTevDesc *, HSD_TExp *);
void HSD_TExpFree(HSD_TExp *texp);
void HSD_TExpRef(HSD_TExp *texp, u8 sel);
void HSD_TExpUnref(HSD_TExp *texp, u8 sel);
void HSD_TExpSetReg(HSD_TExp *texp);
inline static bool IsThroughColor(HSD_TExp *texp)
{
  return ((((texp->tev.c_op == GX_TEV_ADD) && (texp->tev.c_in[0].sel == HSD_TE_0)) && (texp->tev.c_in[1].sel == HSD_TE_0)) && (texp->tev.c_bias == 0)) && (texp->tev.c_scale == 0);
}

inline static bool IsThroughAlpha(HSD_TExp *texp)
{
  return ((((texp->tev.a_op == GX_TEV_ADD) && (texp->tev.a_in[0].sel == HSD_TE_0)) && (texp->tev.a_in[1].sel == HSD_TE_0)) && (texp->tev.a_bias == 0)) && (texp->tev.a_scale == 0);
}

bool lb_8000B074(HSD_JObj *);
bool lb_8000B09C(HSD_JObj *);
bool lb_8000B134(HSD_JObj *);
void lb_8000B1CC(HSD_JObj *jobj, Vec3 *pos0, Vec3 *pos1);
void lb_8000B4FC(HSD_JObj *, HSD_Joint *);
void lb_8000B5DC(HSD_JObj *, HSD_Joint *);
void lb_8000B6A4(HSD_JObj *, HSD_Joint *);
void lb_8000B760(HSD_JObj *, HSD_Joint *);
void lb_8000B804(HSD_JObj *, HSD_Joint *);
void lb_8000BA0C(HSD_JObj *, float);
void lbDObjSetRateAll(HSD_DObj *, float);
void lbDObjReqAnimAll(HSD_DObj *, float);
float lbGetJObjFramerate(HSD_JObj *);
float lbGetJObjCurrFrame(HSD_JObj *);
float lbGetJObjEndFrame(HSD_JObj *);
float lb_8000BFF0(HSD_AnimJoint *animjoint);
void lb_8000C07C(HSD_JObj *, s32 i, HSD_AnimJoint **, HSD_MatAnimJoint **, HSD_ShapeAnimJoint **);
void lb_8000C0E8(HSD_JObj *jobj, s32 i, DynamicModelDesc *);
void memzero(void *mem, ssize_t size);
void lb_8000C1C0(HSD_JObj *, HSD_JObj *constraint);
void lb_8000C228(HSD_JObj *, HSD_JObj *constraint);
void lb_8000C290(HSD_JObj *, HSD_JObj *constraint);
void lb_8000C2F8(HSD_JObj *, HSD_JObj *constraint);
void lb_8000C390(HSD_JObj *);
void lb_8000C420(HSD_JObj *, u32 flags, float limit);
void lb_8000C490(HSD_JObj *jobj1, HSD_JObj *jobj2, HSD_JObj *, float, float);
void lbCopyJObjSRT(HSD_JObj *src, HSD_JObj *dst);
void lb_8000C868(HSD_Joint *, HSD_JObj *, HSD_JObj *, float, float);
s32 lbGetFreeColorRegister(s32 i0, HSD_MObj *, HSD_TExp *);
s32 lb_8000CC8C(s32 i);
s32 lb_8000CCA4(s32 i);
s32 lbGetFreeAlphaRegister(s32 i0, HSD_MObj *, HSD_TExp *);
s32 lb_8000CD90(s32 i);
s32 lb_8000CDA8(s32 i);
HSD_LObj *lb_8000CDC0(HSD_LObj *);
void lb_8000CE30(HSD_DObj *, HSD_DObj *);
void lb_8000CE40(HSD_JObj *, HSD_DObj *);
float lbVector_Len(Vec3 *vec);
float lbVector_Len_xy(Vec3 *vec);
float lbVector_Normalize(Vec3 *vec);
float lbVector_NormalizeXY(Vec3 *a);
Vec3 *lbVector_Add(Vec3 *a, Vec3 *b);
Vec3 *lbVector_Add_xy(Vec3 *a, Vec3 *b);
Vec3 *lbVector_Sub(Vec3 *a, Vec3 *b);
Vec3 *lbVector_Diff(Vec3 *a, Vec3 *b, Vec3 *result);
Vec3 *lbVector_CrossprodNormalized(Vec3 *a, Vec3 *b, Vec3 *result);
float lbVector_Angle(Vec3 *a, Vec3 *b);
float lbVector_AngleXY(Vec3 *a, Vec3 *b);
float sin(float angle);
float cos(float angle);
void lbVector_RotateAboutUnitAxis(Vec3 *v, Vec3 *axis, float angle);
void lbVector_Rotate(Vec3 *v, int axis, float angle);
float dummy(void);
void lbVector_Mirror(Vec3 *a, Vec3 *b);
float lbVector_CosAngle(Vec3 *a, Vec3 *b);
Vec3 *lbVector_Lerp(Vec3 *a, Vec3 *b, Vec3 *result, float f);
Vec3 *lbVector_8000DE38(Mtx m, Vec3 *v, float c);
Vec3 *lbVector_EulerAnglesFromONB(Vec3 *result_angles, Vec3 *a, Vec3 *b, Vec3 *c);
Vec3 *lbVector_EulerAnglesFromPartialONB(Vec3 *result_angles, Vec3 *a, Vec3 *c);
Vec3 *lbVector_ApplyEulerRotation(Vec3 *v, Vec3 *angles);
float lbVector_sqrtf_accurate(float x);
Vec3 *lbVector_WorldToScreen(HSD_CObj *cobj, const Vec3 *pos3d, Vec3 *screenCoords, int d);
void lbVector_CreateEulerMatrix(Mtx m, Vec3 *angles);
float lbVector_8000E838(Vec3 *a, Vec3 *b, Vec3 *c, Vec3 *d);
MapCollData *mpLib_8004D164(void);
CollVtx *mpGetGroundCollVtx(void);
CollLine *mpGetGroundCollLine(void);
CollJoint *mpGetGroundCollJoint(void);
void mpPruneEmptyLines(MapCollData *coll_data);
void mpLibLoad(MapCollData *coll_data);
int mpLineGetNext(int line_id);
int mpLineGetPrev(int line_id);
int mpLib_8004DD90_Floor(int line_id, Vec3 *, float *y_out, u32 *flags_out, Vec3 *normal_out);
int mpLib_8004E090_Ceiling(int line_id, Vec3 *, float *y_out, u32 *flags_out, Vec3 *normal_out);
int mpLib_8004E398_LeftWall(int line_id, Vec3 *, float *x_out, u32 *flags_out, Vec3 *normal_out);
int mpLib_8004E684_RightWall(int line_id, Vec3 *, float *x_out, u32 *flags_out, Vec3 *normal_out);
bool mpLineIntersectionH(float *int_x, float *int_y, float a0x, float a0y, float a1x, float b0x, float b0y, float b1x, float b1y);
void mpLib_8004ED5C(int, float *, float *, float *, float *);
bool mpCheckFloor(float ax, float ay, float bx, float by, float y_offset, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int line_id_skip, int joint_id_skip, int joint_id_only, bool (*)(Fighter_GObj *, int), Fighter_GObj *);
bool mpCheckFloorRemap(float ax, float ay, float bx, float by, float y_offset, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int line_id_skip, int joint_id_skip, int joint_id_only, bool (*)(Fighter_GObj *, int), Fighter_GObj *);
bool mpCheckCeiling(float ax, float ay, float bx, float by, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only);
bool mpCheckCeilingRemap(float ax, float ay, float bx, float by, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only);
bool mpLineIntersectionV(float *int_x, float *int_y, float a0x, float a0y, float a1y, float b0x, float b0y, float b1x, float b1y);
bool mpCheckLeftWall(float ax, float ay, float bx, float by, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only);
bool mpCheckLeftWallRemap(float ax, float ay, float bx, float by, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only);
bool mpCheckRightWall(float ax, float ay, float bx, float by, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only);
bool mpCheckRightWallRemap(float ax, float ay, float bx, float by, Vec3 *vec_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only);
bool mpLib_800511A4_RightWall(float ax, float ay, float bx, float by, float cx, float cy, float dx, float dy, int *line_id_out, int joint_id_skip, int joint_id_only);
bool mpLib_800515A0_LeftWall(float a0x, float a0y, float a1x, float a1y, float b0x, float b0y, float b1x, float b1y, int *line_id_out, int joint_id_skip, int joint_id_only);
int mpLib_8005199C_Floor(Vec3 *, int joint_id_skip, int joint_id_only);
int mpLib_80051BA8_Floor(Vec3 *out_vec, int line_id_skip, int joint_id_skip, int joint_id_only, int dir, float left, float bottom, float right, float top);
bool mpCheckMultiple(float x0, float y0, float x1, float y1, Vec3 *pos_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, u32 checks, int joint_id_skip, int joint_id_only);
bool mpCheckAllRemap(Vec3 *pos_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only, float x0, float y0, float x1, float y1);
bool mpCheckAll(Vec3 *pos_out, int *line_id_out, u32 *flags_out, Vec3 *normal_out, int joint_id_skip, int joint_id_only, float x0, float y0, float x1, float y1);
int mpLineNextNonFloor(int line_id);
int mpLinePrevNonFloor(int line_id);
int mpLinePrevNonCeiling(int line_id);
int mpLineNextNonCeiling(int line_id);
int mpLineNextNonLeftWall(int line_id);
int mpLinePrevNonLeftWall(int line_id);
int mpLinePrevNonRightWall(int line_id);
int mpLineNextNonRightWall(int line_id);
int mpLib_80053394_Floor(int line_id);
int mpLib_80053448_Floor(int line_id);
int mpLib_800534FC_Floor(int line_id);
int mpLib_800536CC_Floor(int line_id);
int mpLib_8005389C_Ceiling(int line_id);
int mpLib_80053950_Ceiling(int line_id);
int mpLib_80053A04_Ceiling(int line_id);
int mpLib_80053BD4_Ceiling(int line_id);
void mpLib_80053DA4_Floor(int line_id, Vec3 *);
void mpLib_80053ECC_Floor(int line_id, Vec3 *);
void mpFloorGetRight(int line_id, Vec3 *);
void mpFloorGetLeft(int line_id, Vec3 *);
void mpCeilingGetRight(int line_id, Vec3 *);
void mpCeilingGetLeft(int line_id, Vec3 *);
void mpLeftWallGetTop(int line_id, Vec3 *);
void mpLeftWallGetBottom(int line_id, Vec3 *);
void mpRightWallGetTop(int line_id, Vec3 *);
void mpRightWallGetBottom(int line_id, Vec3 *);
void mpLineGetV1Pos(int line_id, Vec3 *pos_out);
void mpLineGetV0Pos(int line_id, Vec3 *pos_out);
enum_t mpLineGetKind(int line_id);
u32 mpLineGetFlags(int line_id);
void mpLib_80054D68(int line_id, u32 flags);
Vec3 *mpLineGetNormal(int line_id, Vec3 *normal_out);
bool mpLib_80054ED8(int line_id);
bool mpLinesConnected(int start_id, int target_id);
void mpLib_800552B0(int joint_id, HSD_JObj *, int z);
void mpJointHide(int joint_id);
void mpJointUnhide(int joint_id);
void mpJointUpdateDynamics(int joint_id);
void mpLib_80055E24(int joint_id);
void mpLib_80055E9C(int joint_id);
void mpJointUpdateBounding(int joint_id);
void mpLib_8005667C(int joint_id);
void mpVtxGetPos(int vtx_id, float *x_out, float *y_out);
void mpVtxSetPos(int vtx_id, float x, float y);
void mpLineSetPos(int line_id, float x0, float y0, float x1, float y1);
void mpLib_80056758(int line_id, float x0, float y0, float x1, float y1);
bool mpGetSpeed(int line_id, Vec3 *pos, Vec3 *speed);
float mpLib_800569EC(u32);
int *mpLib_80056A1C(int, int *);
int mpLib_80056A54(int, int *);
int *mpLib_80056A8C(int, int *);
int mpLib_80056AC4(int, int *);
int *mpLib_80056AFC(int, int *);
int mpLib_80056B34(int, int *);
int mpJointFromLine(int line_id);
bool mpLib_80056C54(int line_id, Vec3 *pos, int *line_id_out, Vec3 *vec_out, u32 *flags_out, Vec3 *normal_out, float, float, float, float);
void mpLib_80057424(int joint_id);
void mpLib_80057528(int line_id);
void mpLib_800575B0(int line_id);
void mpJointListAdd(int joint_id);
void mpJointListUnlink(CollJoint *);
void mpLib_80057BC0(int joint_id);
void mpLib_80057FDC(int joint_id);
void mpLib_80058044(int joint_id);
void mpJointSetB10(int joint_id);
void mpJointSetCb1(int joint_id, Ground *, mpLib_Callback);
void mpJointClearCb1(int joint_id);
void mpJointGetCb1(int joint_id, mpLib_Callback *, Ground **);
void mpLib_8005811C(CollData *, int ledge_id);
void mpJointSetCb2(int joint_id, Ground *, mpLib_Callback);
void mpJointGetCb2(int joint_id, mpLib_Callback *, Ground **);
void mpLib_800581DC(int joint_id0, int joint_id1);
void mpLib_80058560(void);
void mpLib_80058614_Floor(void);
void mpLib_800587FC(HSD_GObj *);
void mpLib_80058820(void);
bool mpCheckedBounding(void);
void mpBoundingCheck(float left, float bottom, float right, float top);
void mpBoundingCheck2(float x1, float y1, float x2, float y2);
void mpBoundingCheck3(float x0, float y0, float x1, float y1, float x2, float y2, float x3, float y3);
void mpUncheckBounding(void);
void mpLib_SetupDraw(GXColor);
void mpLib_DrawEcbs(CollData *);
void mpLib_DrawSnapping(void);
void mpLib_DrawMatchingLines(int, int, GXColor);
void mpLib_80059554(void);
void mpLib_80059E60(void);
void mpLib_DrawCrosses(s16 *idx, int len, GXColor);
void mpLib_DrawSpecialPoints(void);
void mpLib_8005A2DC(void);
void mpLib_DrawZones(void);
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
typedef void (*GObjFunc)(HSD_Obj *);
typedef struct _GObjFuncs
{
  struct _GObjFuncs *next;
  u8 size;
  GObjFunc *funcs;
} GObjFuncs;
typedef struct _HSD_GObjLibInitDataType
{
  u8 p_link_max;
  u8 gx_link_max;
  u8 gproc_pri_max;
  GObjFuncs *funcs;
  u64 *unk_2;
} HSD_GObjLibInitDataType;
typedef struct _HSD_GObjList
{
  HSD_GObj *x0;
  HSD_GObj *x4;
  HSD_GObj *x8;
  HSD_GObj *xC;
  HSD_GObj *x10;
  HSD_GObj *x14;
  HSD_GObj *x18;
  HSD_GObj *x1C;
  HSD_GObj *fighters;
  HSD_GObj *items;
  HSD_GObj *x28;
  HSD_GObj *x2C;
  HSD_GObj *x30;
  HSD_GObj *x34;
  HSD_GObj *x38;
  HSD_GObj *x3C;
  HSD_GObj *x40;
  HSD_GObj *x44;
  HSD_GObj *x48;
} HSD_GObjList;
extern struct _unk_gobj_struct
{
  union 
  {
    u32 flags;
    struct 
    {
      u32 b0 : 1;
      u32 b1 : 1;
      u32 b2 : 1;
      u32 b3 : 1;
    };
  };
  u32 type;
  u8 p_link;
  u8 p_prio;
  HSD_GObj *gobj;
} HSD_GObj_804CE3E4;
extern GObjFunc *HSD_GObj_804D7810;
extern HSD_GObj *HSD_GObj_804D7814;
extern HSD_GObj *HSD_GObj_804D7818;
extern HSD_GObj *HSD_GObj_804D781C;
extern HSD_GObj **HSD_GObj_804D7820;
extern HSD_GObj **HSD_GObj_804D7824;
extern HSD_GObj **plinklow_gobjs;
extern HSD_GObjList *HSD_GObj_Entities;
extern HSD_GObjProc *HSD_GObj_804D7830;
extern s32 HSD_GObj_804D7834;
extern HSD_GObjProc *HSD_GObj_804D7838;
extern s32 HSD_GObj_804D783C;
extern HSD_GObjProc **HSD_GObj_804D7840;
extern HSD_GObjProc **HSD_GObj_804D7844;
extern s8 HSD_GObj_804D7848;
extern u8 HSD_GObj_804D7849;
extern s8 HSD_GObj_804D784A;
extern u8 HSD_GObj_804D784B;
extern HSD_GObjLibInitDataType HSD_GObjLibInitData;
void HSD_GObj_80390C5C(HSD_GObj *gobj);
void HSD_GObj_80390C84(HSD_GObj *gobj);
void HSD_GObj_80390CAC(HSD_GObj *gobj);
u32 HSD_GObj_80390EB8(s32 i);
void HSD_GObj_803910D8(HSD_GObj *, int);
u8 HSD_GObj_803912A8(HSD_GObjLibInitDataType *, GObjFuncs *);
HSD_GObj *GObj_Create(u16 classifier, u8 p_link, u8 priority);
void HSD_GObj_JObjCallback(HSD_GObj *gobj, int arg1);
void HSD_GObj_80390CD4(HSD_GObj *gobj);
void HSD_GObj_80390CFC(void);
void render_gobj(HSD_GObj *cur, int i);
void HSD_GObj_80390FC0(void);
void HSD_GObj_LObjCallback(HSD_GObj *gobj, int unused);
void HSD_GObj_FogCallback(HSD_GObj *gobj, int unused);
void HSD_GObj_80391120(HSD_Obj *obj);
void HSD_GObj_803911C0(HSD_Obj *obj);
void HSD_GObj_80391260(HSD_GObjLibInitDataType *);
void HSD_GObj_803912E0(HSD_GObjLibInitDataType *arg0);
void HSD_GObj_80390ED0(HSD_GObj *gobj, u32 mask);
void HSD_GObj_80391304(HSD_GObjLibInitDataType *);
inline static void *HSD_GObjGetUserData(HSD_GObj *gobj)
{
  return gobj->user_data;
}

inline static void *HSD_GObjGetHSDObj(HSD_GObj *gobj)
{
  return gobj->hsd_obj;
}

inline static u16 HSD_GObjGetClassifier(HSD_GObj *gobj)
{
  return gobj->classifier;
}

inline static HSD_GObj *HSD_GObjGetNext(HSD_GObj *gobj)
{
  return gobj->next;
}

float acosf(float);
float asinf(float);
float atan2f(float y, float x);
float atanf(float);
float cosf(float);
float sinf(float);
float tanf(float);
struct mpColl_80458810_t
{
  int right[9];
  int left[9];
  Vec3 normal;
  u8 x54_pad[4];
};
static struct mpColl_80458810_t mpColl_80458810;
static bool mpColl_IsEcbTiny;
static bool (*mpColl_804D64A0)(Fighter_GObj *, int);
static Fighter_GObj *mpColl_804D64A4;
static Event mpColl_804D64A8;
int mpColl_804D64AC;
int mpColl_804D6488;
int mpColl_804D648C;
const float mpColl_804D7F9C = -3.4028235e38f;
const float mpColl_804D7FA0 = 3.4028235e38f;
const float flt_804D7FF8 = 5.0F;
const f64 flt_804D8000 = -0.75;
const f64 flt_804D8008 = 0.75;
const float flt_804D8010 = -3.0F;
const float flt_804D7FD8 = 6.0F;
void mpColl_80041C78(void);
void mpCollPrev(CollData *cd);
inline void clamp_above(float *value, float min)
{
  if ((*value) < min)
  {
    *value = min;
  }
}

inline void clamp_below(float *value, float max)
{
  if ((*value) > max)
  {
    *value = max;
  }
}

void mpCollCheckBounding(CollData *cd, u32 flags);
void mpColl_80041EE4(CollData *cd);
void mpColl_SetECBSource_JObj(CollData *cd, HSD_GObj *gobj, HSD_JObj *arg1, HSD_JObj *arg2, HSD_JObj *arg3, HSD_JObj *arg4, HSD_JObj *arg5, HSD_JObj *arg6, HSD_JObj *arg7, float arg9);
void mpColl_SetECBSource_Fixed(CollData *cd, HSD_GObj *gobj, float arg1, float arg2, float arg3, float arg4);
void mpColl_SetLedgeSnap(CollData *coll, float ledge_snap_x, float ledge_snap_y, float ledge_snap_height);
void mpColl_80042384(CollData *cd);
inline void update_min_max(float *min, float *max, float val)
{
  if ((*min) > val)
  {
    *min = val;
  }
  else
    if ((*max) < val)
  {
    *max = val;
  }
}

void mpColl_LoadECB_JObj(CollData *coll, u32 flags);
inline void update_min_max_2(float *min, float *max, float val)
{
  if ((*max) < val)
  {
    *max = val;
  }
  else
    if ((*min) > val)
  {
    *min = val;
  }
}

inline void clamp_above_2(float *value, float min)
{
  if ((*value) < min)
  {
    *value = min;
  }
}

inline void clamp_below_2(float *value, float max)
{
  if ((*value) > max)
  {
    *value = max;
  }
}

void mpColl_LoadECB_Fixed(CollData *coll);
void mpColl_80042C58(CollData *coll, ftCollisionBox *arg1);
inline static void mpColl_LoadECB_inline(CollData *coll, enum_t i)
{
  float saved_bottom_x;
  float saved_bottom_y;
  if (coll->x130_flags & CollData_X130_Locked)
  {
    saved_bottom_x = coll->desired_ecb.bottom.x;
    saved_bottom_y = coll->desired_ecb.bottom.y;
  }
  if (coll->ecb_source.kind == ECBSource_JObj)
  {
    mpColl_LoadECB_JObj(coll, i);
  }
  else
  {
    mpColl_LoadECB_Fixed(coll);
  }
  if (coll->x130_flags & CollData_X130_Locked)
  {
    coll->desired_ecb.bottom.x = saved_bottom_x;
    coll->desired_ecb.bottom.y = saved_bottom_y;
  }
  mpColl_80042384(coll);
}

#pragma push
#pragma dont_inline on
void mpColl_LoadECB(CollData *coll);
#pragma pop
inline void Vec2_Interpolate(float time, Vec2 *dest, Vec2 *src)
{
  dest->x += time * (src->x - dest->x);
  dest->y += time * (src->y - dest->y);
}

void mpCollInterpolateECB(CollData *coll, float time);
void mpColl_RightWall_inline(int line_id);
void mpColl_LeftWall_inline(int line_id);
void mpColl_LeftWall_inline3(int line_id, int *arr);
void mpColl_80043268(CollData *coll, int line_id, bool arg2, float dy);
inline static void mpCollEnd_inline2(CollData *coll, int line_id, bool arg2, float dy)
{
  int dummy = 0;
  int joint_id;
  joint_id = mpJointFromLine(line_id);
  if (joint_id != (-1))
  {
    mpLib_Callback callback;
    Ground *ground = 0L;
    mpJointGetCb2(joint_id, &callback, &ground);
    if (callback != 0L)
    {
      callback(ground, joint_id, coll, coll->x50, 0, dy);
    }
  }
}

inline static void mpCollEnd_inline(CollData *coll, int line_id, bool arg2, float dy)
{
  mpColl_80043268(coll, line_id, arg2, dy);
}

void mpCollEnd(CollData *coll, bool arg1, bool arg2);
void mpColl_80043558(CollData *coll, int line_id);
void mpColl_80043670(CollData *coll);
void mpColl_80043680(CollData *coll, Vec3 *arg1);
void mpCollSetFacingDir(CollData *coll, int facing_dir);
float six(void);
void mpColl_800436E4(CollData *coll, float arg1);
inline float max_inline(float a, float b)
{
  return (a > b) ? (a) : (b);
}

bool mpColl_80043754(mpColl_Callback cb, CollData *coll, u32 flags);
void mpColl_800439FC(CollData *coll);
void mpColl_80043ADC(CollData *coll);
bool mpColl_80043BBC(CollData *coll, int *line_id_out);
void mpColl_80043C6C(CollData *coll, int line_id, bool ignore_bottom);
bool mpColl_80043E90(CollData *coll, int *line_id_out);
void mpColl_80043F40(CollData *coll, int line_id, bool ignore_bottom);
bool mpColl_80044164(CollData *cd, int *p_ledge_id);
bool mpColl_800443C4(CollData *cd, int *p_ledge_id);
bool mpColl_80044628_Floor(CollData *coll, bool (*cb)(Fighter_GObj *, int), Fighter_GObj *gobj, int left_right);
bool mpColl_80044838_Floor(CollData *coll, bool ignore_bottom);
bool mpColl_80044948_Floor(CollData *coll);
bool mpColl_80044AD8_Ceiling(CollData *coll, int left_right);
bool mpColl_80044C74_Ceiling(CollData *coll);
inline static bool mpColl_RightWall_inline2(CollData *coll, float ax, float ay, float bx, float by, int *line_id_out)
{
  if (coll->x38 != mpColl_804D64AC)
  {
    return mpCheckRightWallRemap(ax, ay, bx, by, 0L, line_id_out, 0L, 0L, coll->joint_id_skip, coll->joint_id_only);
  }
  return mpCheckRightWall(ax, ay, bx, by, 0L, line_id_out, 0L, 0L, coll->joint_id_skip, coll->joint_id_only);
}

bool mpColl_80044E10_RightWall(CollData *coll);
float mpColl_804D6490_max_x;
int mpColl_804D6494_line_id;
u32 mpColl_804D6498_flags;
bool mpColl_800454A4_RightWall(CollData *coll);
inline static bool mpColl_LeftWall_inline2(CollData *coll, float ax, float ay, float bx, float by, int *line_id_out)
{
  if (coll->x38 != mpColl_804D64AC)
  {
    return mpCheckLeftWallRemap(ax, ay, bx, by, 0L, line_id_out, 0L, 0L, coll->joint_id_skip, coll->joint_id_only);
  }
  return mpCheckLeftWall(ax, ay, bx, by, 0L, line_id_out, 0L, 0L, coll->joint_id_skip, coll->joint_id_only);
}

bool mpColl_80045B74_LeftWall(CollData *coll);
bool mpColl_80046224_LeftWall(CollData *coll);
inline static void mpCollCeilingInline(CollData *coll)
{
  int right_wall_id;
  int left_wall_id;
  float top_x;
  float top_y;
  float side_x;
  float side_y;
  bool hit_wall;
  int non_ceiling_id = mpLineNextNonCeiling(coll->ceiling.index);
  top_x = coll->cur_pos.x + coll->ecb.top.x;
  top_y = coll->cur_pos.y + coll->ecb.top.y;
  side_x = coll->cur_pos.x + coll->ecb.right.x;
  side_y = coll->cur_pos.y + coll->ecb.right.y;
  if (mpCheckLeftWall(top_x, top_y, side_x, side_y, 0L, &left_wall_id, 0L, 0L, coll->joint_id_skip, coll->joint_id_only) && (left_wall_id != non_ceiling_id))
  {
    hit_wall = 1;
  }
  else
  {
    hit_wall = 0;
  }
  if (hit_wall)
  {
    mpColl_800439FC(coll);
  }
  non_ceiling_id = mpLinePrevNonCeiling(coll->ceiling.index);
  top_x = coll->cur_pos.x + coll->ecb.top.x;
  top_y = coll->cur_pos.y + coll->ecb.top.y;
  side_x = coll->cur_pos.x + coll->ecb.left.x;
  side_y = coll->cur_pos.y + coll->ecb.left.y;
  if (mpCheckRightWall(top_x, top_y, side_x, side_y, 0L, &right_wall_id, 0L, 0L, coll->joint_id_skip, coll->joint_id_only) && (right_wall_id != non_ceiling_id))
  {
    hit_wall = 1;
  }
  else
  {
    hit_wall = 0;
  }
  if (hit_wall)
  {
    mpColl_80043ADC(coll);
  }
}

inline static void mpCollFloorInline(CollData *coll, bool ecb_unlocked, u32 squeeze_flags)
{
  int wall_id;
  if (mpColl_80043BBC(coll, &wall_id))
  {
    mpColl_80043C6C(coll, wall_id, ecb_unlocked && (!(squeeze_flags & 1)));
  }
  if (mpColl_80043E90(coll, &wall_id))
  {
    mpColl_80043F40(coll, wall_id, ecb_unlocked && (!(squeeze_flags & 1)));
  }
}

bool mpColl_80046904(CollData *coll, u32 flags)
{
  bool prev_b6;
  int squeeze_flags;
  int old_squeeze_flags;
  int squeeze_flags_all;
  bool touched_floor;
  CollData *new_var;
  bool platform_pass;
  bool stay_airborne;
  int left_right_flags;
  do
  {
    unsigned char _[0x8];
  }
  while (0);
  platform_pass = flags & 0x2;
  stay_airborne = flags & 0x1;
  left_right_flags = 0;
  touched_floor = 0;
  squeeze_flags_all = 0;
  squeeze_flags = 0;
  do
  {
    float x_after_collide_right;
    bool r3;
    float x_after_collide_left;
    float y_after_collide_floor;
    float y_after_collide_ceiling;
    x_after_collide_right = 0.0F;
    old_squeeze_flags = squeeze_flags;
    x_after_collide_left = 0.0F;
    prev_b6 = coll->x34_flags.b6;
    squeeze_flags = 0;
    if (mpColl_80045B74_LeftWall(coll))
    {
      if (mpColl_80046224_LeftWall(coll))
      {
        left_right_flags |= 1;
        squeeze_flags |= 8;
      }
      x_after_collide_left = coll->cur_pos.x;
    }
    if (mpColl_80044E10_RightWall(coll))
    {
      if (mpColl_800454A4_RightWall(coll))
      {
        left_right_flags |= 2;
        squeeze_flags |= 4;
      }
      x_after_collide_right = coll->cur_pos.x;
    }
    if (mpColl_80045B74_LeftWall(coll))
    {
      if (mpColl_80046224_LeftWall(coll))
      {
        left_right_flags |= 1;
        squeeze_flags |= 8;
      }
      x_after_collide_left = coll->cur_pos.x;
    }
    if (mpColl_80044E10_RightWall(coll))
    {
      if (mpColl_800454A4_RightWall(coll))
      {
        left_right_flags |= 2;
        squeeze_flags |= 4;
      }
      x_after_collide_right = coll->cur_pos.x;
    }
    new_var = coll;
    if ((squeeze_flags & 0b1100) == 0b1100)
    {
      mpCollSqueezeHorizontal(coll, 1, x_after_collide_right, x_after_collide_left);
    }
    y_after_collide_ceiling = 0.0F;
    y_after_collide_floor = 0.0F;
    if (mpColl_80044AD8_Ceiling(coll, left_right_flags) && mpColl_80044C74_Ceiling(coll))
    {
      mpCollCeilingInline(coll);
      squeeze_flags |= 1;
      y_after_collide_ceiling = new_var->cur_pos.y;
    }
    if (platform_pass)
    {
      r3 = mpColl_80044628_Floor(new_var, mpColl_804D64A0, mpColl_804D64A4, left_right_flags);
    }
    else
    {
      r3 = mpColl_80044628_Floor(new_var, 0L, 0L, left_right_flags);
    }
    if (r3)
    {
      if (stay_airborne)
      {
        if (mpColl_80044948_Floor(new_var))
        {
          mpCollFloorInline(new_var, 0, squeeze_flags);
        }
      }
      else
      {
        bool ecb_unlocked = 0;
        if (new_var->ecb.bottom.y > 0.0F)
        {
          ecb_unlocked = 1;
        }
        if (mpColl_80044838_Floor(new_var, ecb_unlocked && (!(squeeze_flags & 1))))
        {
          mpCollFloorInline(new_var, ecb_unlocked, squeeze_flags);
          new_var->x34_flags.b5 = 1;
          touched_floor = 1;
        }
      }
      y_after_collide_floor = new_var->cur_pos.y;
      squeeze_flags |= 2;
      if (mpColl_80044AD8_Ceiling(new_var, left_right_flags) && mpColl_80044C74_Ceiling(new_var))
      {
        mpCollCeilingInline(new_var);
        squeeze_flags |= 1;
        y_after_collide_ceiling = new_var->cur_pos.y;
      }
    }
    if ((squeeze_flags & 0b0011) == 0b0011)
    {
      bool airborne;
      if (touched_floor)
      {
        airborne = 0;
      }
      else
      {
        airborne = 1;
      }
      mpCollSqueezeVertical(new_var, airborne, y_after_collide_ceiling, y_after_collide_floor);
    }
    squeeze_flags_all |= squeeze_flags;
  }
  while ((prev_b6 != coll->x34_flags.b6) || (squeeze_flags != old_squeeze_flags));
  if ((!touched_floor) && (flags & 0x4))
  {
    bool on_edge = (new_var->env_flags & 0x100000) || (new_var->env_flags & 0x200000);
    if ((!on_edge) && (new_var->cur_pos.y < new_var->prev_pos.y))
    {
      if ((new_var->facing_dir == 1) || (new_var->facing_dir == 0))
      {
        if (mpColl_80044164(new_var, &new_var->ledge_id_left))
        {
          on_edge = 1;
          new_var->env_flags |= 0x1000000;
        }
        else
        {
          on_edge = 0;
        }
        if (on_edge)
        {
          new_var->env_flags |= 0x1000000;
        }
      }
      if ((new_var->facing_dir == (-1)) || (new_var->facing_dir == 0))
      {
        if (mpColl_800443C4(new_var, &new_var->ledge_id_right))
        {
          on_edge = 1;
          new_var->env_flags |= 0x2000000;
        }
        else
        {
          on_edge = 0;
        }
        if (on_edge)
        {
          new_var->env_flags |= 0x2000000;
        }
      }
    }
  }
  if (!(squeeze_flags_all & 0b1000))
  {
    new_var->env_flags &= ~0x3F;
  }
  if (!(squeeze_flags_all & 0b0100))
  {
    new_var->env_flags &= ~0xFC0;
  }
  return touched_floor;
}

inline static bool mpColl_80046F78_inline(CollData *coll, int *line_id_out)
{
  if (coll->x38 != mpColl_804D64AC)
  {
    float prev_x = coll->prev_pos.x;
    float prev_y = coll->prev_pos.y;
    float x = coll->cur_pos.x;
    float y = coll->cur_pos.y;
    return mpCheckAllRemap(&coll->contact, line_id_out, 0L, 0L, coll->joint_id_skip, coll->joint_id_only, prev_x, prev_y, x, y);
  }
  else
  {
    float prev_x = coll->prev_pos.x;
    float prev_y = coll->prev_pos.y;
    float x = coll->cur_pos.x;
    float y = coll->cur_pos.y;
    return mpCheckAll(&coll->contact, line_id_out, 0L, 0L, coll->joint_id_skip, coll->joint_id_only, prev_x, prev_y, x, y);
  }
}

bool mpColl_80046F78(CollData *coll, u32 _);
inline static bool inline0(CollData *coll, int i, bool j)
{
  bool result;
  coll->prev_env_flags = coll->env_flags;
  coll->env_flags = 0;
  if (((coll->ecb.top.y - coll->ecb.bottom.y) < 6.0F) && ((coll->ecb.right.y - coll->ecb.left.y) < 6.0F))
  {
    mpColl_IsEcbTiny = 1;
  }
  else
  {
    mpColl_IsEcbTiny = 0;
  }
  result = mpColl_80043754(mpColl_80046904, coll, i);
  mpCollEnd(coll, result, j);
  return result;
}

inline static bool inline4(CollData *coll, int i)
{
  bool result;
  coll->prev_env_flags = coll->env_flags;
  coll->env_flags = 0;
  if (((coll->ecb.top.y - coll->ecb.bottom.y) < 6.0F) && ((coll->ecb.right.y - coll->ecb.left.y) < 6.0F))
  {
    mpColl_IsEcbTiny = 1;
  }
  else
  {
    mpColl_IsEcbTiny = 0;
  }
  result = mpColl_80043754(mpColl_80046F78, coll, i);
  mpCollEnd(coll, result, 1);
  return result;
}

inline static bool inline2(CollData *coll, int i)
{
  bool result;
  coll->prev_env_flags = coll->env_flags;
  coll->env_flags = 0;
  if (((coll->ecb.top.y - coll->ecb.bottom.y) < 6.0F) && ((coll->ecb.right.y - coll->ecb.left.y) < 6.0F))
  {
    mpColl_IsEcbTiny = 1;
  }
  else
  {
    mpColl_IsEcbTiny = 0;
  }
  result = mpColl_80043754((void *) mpColl_8004ACE4, coll, i);
  mpCollEnd(coll, result, 0);
  return result;
}

inline static bool inline3(CollData *coll, int i)
{
  bool result;
  coll->prev_env_flags = coll->env_flags;
  coll->env_flags = 0;
  if (((coll->ecb.top.y - coll->ecb.bottom.y) < 6.0F) && ((coll->ecb.right.y - coll->ecb.left.y) < 6.0F))
  {
    mpColl_IsEcbTiny = 1;
  }
  else
  {
    mpColl_IsEcbTiny = 0;
  }
  result = mpColl_80043754(mpColl_8004C534, coll, i);
  mpCollEnd(coll, result, 0);
  return result;
}

inline static bool inline1(CollData *coll, int i, bool (*floor_cb)(Fighter_GObj *, int), Fighter_GObj *gobj)
{
  bool result;
  coll->prev_env_flags = coll->env_flags;
  coll->env_flags = 0;
  if (((coll->ecb.top.y - coll->ecb.bottom.y) < 6.0F) && ((coll->ecb.right.y - coll->ecb.left.y) < 6.0F))
  {
    mpColl_IsEcbTiny = 1;
  }
  else
  {
    mpColl_IsEcbTiny = 0;
  }
  mpColl_804D64A0 = floor_cb;
  mpColl_804D64A4 = gobj;
  result = mpColl_80043754(mpColl_80046904, coll, i);
  mpCollEnd(coll, result, 1);
  return result;
}

bool mpColl_800471F8(CollData *coll);
bool mpColl_8004730C(CollData *coll, ftCollisionBox *arg1);
bool mpColl_800473CC(CollData *coll);
bool mpColl_800474E0(CollData *coll);
bool mpColl_800475F4(CollData *coll, ftCollisionBox *arg1);
bool mpColl_800476B4(CollData *coll, bool (*arg1)(Fighter_GObj *, enum_t), Fighter_GObj *gobj);
bool mpColl_800477E0(CollData *coll);
bool mpColl_800478F4(CollData *coll);
bool mpColl_80047A08(CollData *coll, ftCollisionBox *arg1);
bool mpColl_80047AC8(CollData *coll, bool (*arg1)(Fighter_GObj *, int), Fighter_GObj *arg2);
bool mpColl_80047BF4(CollData *coll, bool (*arg1)(Fighter_GObj *, int), Fighter_GObj *arg2);
bool mpColl_80047D20(CollData *coll, bool (*arg1)(Fighter_GObj *, int), Fighter_GObj *arg2);
bool mpColl_80047E14(CollData *coll, bool (*arg1)(Fighter_GObj *, int), Fighter_GObj *arg2);
bool mpColl_80047F40(CollData *coll, bool (*arg1)(Fighter_GObj *, int), Fighter_GObj *arg2);
bool mpColl_8004806C(CollData *coll, bool (*arg1)(Fighter_GObj *, int), Fighter_GObj *arg2);
bool mpColl_80048160(CollData *coll);
bool mpColl_80048274(CollData *coll);
bool mpColl_80048388(CollData *coll);
bool mpColl_80048464(CollData *coll);
bool mpColl_80048578(CollData *coll);
bool mpColl_80048654(CollData *coll);
bool mpColl_80048768(CollData *coll);
bool mpColl_80048844(CollData *coll, f32 arg1);
bool mpColl_800488F4(CollData *coll);
bool mpColl_80048AB0_RightWall(CollData *coll);
bool mpColl_800491C8_RightWall(CollData *coll);
bool mpColl_80049778_LeftWall(CollData *coll);
bool mpColl_80049EAC_LeftWall(CollData *coll);
bool mpColl_8004A45C_Floor(CollData *coll, int line_id);
bool mpColl_8004A678_Floor(CollData *coll, int line_id);
bool mpColl_8004A908_Floor(CollData *coll, int line_id);
bool mpColl_8004AB80(CollData *coll);
bool mpColl_8004ACE4(CollData *coll, int flags);
bool mpColl_8004B108(CollData *coll);
bool mpColl_8004B21C(CollData *coll, ftCollisionBox *arg1);
bool mpColl_8004B2DC(CollData *coll);
bool mpColl_8004B3F0(CollData *coll, ftCollisionBox *arg1);
bool mpColl_8004B4B0(CollData *coll);
bool mpColl_8004B5C4(CollData *coll);
bool mpColl_8004B6D8(CollData *coll);
bool mpColl_8004B894_RightWall(CollData *coll);
bool mpColl_8004BDD4_LeftWall(CollData *coll);
bool mpColl_8004C328_Ceiling(CollData *coll, int line_id);
bool mpColl_8004C534(CollData *coll, u32 flags);
bool mpColl_8004C750(CollData *coll);
#pragma push
#pragma dont_inline on
void mpCollSqueezeHorizontal(CollData *coll, bool airborne, float left, float right);
void mpCollSqueezeVertical(CollData *coll, bool airborne, float top, float bottom);
#pragma pop
float mpColl_8004CA6C(CollData *coll);
bool mpCollGetSpeedCeiling(CollData *coll, Vec3 *speed);
bool mpCollGetSpeedLeftWall(CollData *coll, Vec3 *speed);
bool mpCollGetSpeedRightWall(CollData *coll, Vec3 *speed);
bool mpCollGetSpeedFloor(CollData *coll, Vec3 *speed);
bool mpColl_IsOnPlatform(CollData *coll);
void mpUpdateFloorSkip(CollData *coll);
void mpClearFloorSkip(CollData *coll);
void mpCopyCollData(CollData *src, CollData *dst, int arg2);
bool mpColl_8004D024(Vec3 *arg0);
