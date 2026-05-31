# General Purpose Registers (GPRs)
.set r0, 0
.set r1, 1
.set r2, 2
.set r3, 3
.set r4, 4
.set r5, 5
.set r6, 6
.set r7, 7
.set r8, 8
.set r9, 9
.set r10, 10
.set r11, 11
.set r12, 12
.set r13, 13
.set r14, 14
.set r15, 15
.set r16, 16
.set r17, 17
.set r18, 18
.set r19, 19
.set r20, 20
.set r21, 21
.set r22, 22
.set r23, 23
.set r24, 24
.set r25, 25
.set r26, 26
.set r27, 27
.set r28, 28
.set r29, 29
.set r30, 30
.set r31, 31

# Floating Point Registers (FPRs)
.set f0, 0
.set f1, 1
.set f2, 2
.set f3, 3
.set f4, 4
.set f5, 5
.set f6, 6
.set f7, 7
.set f8, 8
.set f9, 9
.set f10, 10
.set f11, 11
.set f12, 12
.set f13, 13
.set f14, 14
.set f15, 15
.set f16, 16
.set f17, 17
.set f18, 18
.set f19, 19
.set f20, 20
.set f21, 21
.set f22, 22
.set f23, 23
.set f24, 24
.set f25, 25
.set f26, 26
.set f27, 27
.set f28, 28
.set f29, 29
.set f30, 30
.set f31, 31

# Graphics Quantization Registers (GQRs)
.set qr0, 0
.set qr1, 1
.set qr2, 2
.set qr3, 3
.set qr4, 4
.set qr5, 5
.set qr6, 6
.set qr7, 7

# Special Purpose Registers (SPRs)
.set XER, 1
.set LR, 8
.set CTR, 9
.set DSISR, 18
.set DAR, 19
.set DEC, 22
.set SDR1, 25
.set SRR0, 26
.set SRR1, 27
.set SPRG0, 272
.set SPRG1, 273
.set SPRG2, 274
.set SPRG3, 275
.set EAR, 282
.set PVR, 287
.set IBAT0U, 528
.set IBAT0L, 529
.set IBAT1U, 530
.set IBAT1L, 531
.set IBAT2U, 532
.set IBAT2L, 533
.set IBAT3U, 534
.set IBAT3L, 535
.set DBAT0U, 536
.set DBAT0L, 537
.set DBAT1U, 538
.set DBAT1L, 539
.set DBAT2U, 540
.set DBAT2L, 541
.set DBAT3U, 542
.set DBAT3L, 543
.set GQR0, 912
.set GQR1, 913
.set GQR2, 914
.set GQR3, 915
.set GQR4, 916
.set GQR5, 917
.set GQR6, 918
.set GQR7, 919
.set HID2, 920
.set WPAR, 921
.set DMA_U, 922
.set DMA_L, 923
.set UMMCR0, 936
.set UPMC1, 937
.set UPMC2, 938
.set USIA, 939
.set UMMCR1, 940
.set UPMC3, 941
.set UPMC4, 942
.set USDA, 943
.set MMCR0, 952
.set PMC1, 953
.set PMC2, 954
.set SIA, 955
.set MMCR1, 956
.set PMC3, 957
.set PMC4, 958
.set SDA, 959
.set HID0, 1008
.set HID1, 1009
.set IABR, 1010
.set DABR, 1013
.set L2CR, 1017
.set ICTC, 1019
.set THRM1, 1020
.set THRM2, 1021
.set THRM3, 1022

# Condition Register (CR) bits
.set cr0lt, 0
.set cr0gt, 1
.set cr0eq, 2
.set cr0un, 3
.set cr1lt, 4
.set cr1gt, 5
.set cr1eq, 6
.set cr1un, 7
.set cr2lt, 8
.set cr2gt, 9
.set cr2eq, 10
.set cr2un, 11
.set cr3lt, 12
.set cr3gt, 13
.set cr3eq, 14
.set cr3un, 15
.set cr4lt, 16
.set cr4gt, 17
.set cr4eq, 18
.set cr4un, 19
.set cr5lt, 20
.set cr5gt, 21
.set cr5eq, 22
.set cr5un, 23
.set cr6lt, 24
.set cr6gt, 25
.set cr6eq, 26
.set cr6un, 27
.set cr7lt, 28
.set cr7gt, 29
.set cr7eq, 30
.set cr7un, 31

# Defines a sized symbol with function type.
# Usage:
# .fn my_function, local
# /* asm here */
# .endfn my_function
.macro .fn name, visibility=global
.\visibility "\name"
.type "\name", @function
"\name":
.endm

.macro .endfn name
.size "\name", . - "\name"
.endm

# Defines a sized symbol with object type.
# Usage:
# .obj my_object, local
# /* data here */
# .endobj my_object
.macro .obj name, visibility=global
.\visibility "\name"
.type "\name", @object
"\name":
.endm

.macro .endobj name
.size "\name", . - "\name"
.endm

# Defines a sized symbol without a type.
# Usage:
# .sym my_sym, local
# /* anything here */
# .endsym my_sym
.macro .sym name, visibility=global
.\visibility "\name"
"\name":
.endm

.macro .endsym name
.size "\name", . - "\name"
.endm

# Generates a relative relocation against a symbol.
# Usage:
# .rel my_function, .L_label
.macro .rel name, label
.4byte "\name" + ("\label" - "\name")
.endm
.fn grVenom_80204284, global
/* 80204284 00200E64  7C 08 02 A6 */	mflr r0
/* 80204288 00200E68  90 01 00 04 */	stw r0, 0x4(r1)
/* 8020428C 00200E6C  94 21 FF C0 */	stwu r1, -0x40(r1)
/* 80204290 00200E70  93 E1 00 3C */	stw r31, 0x3c(r1)
/* 80204294 00200E74  93 C1 00 38 */	stw r30, 0x38(r1)
/* 80204298 00200E78  7C 7E 1B 78 */	mr r30, r3
/* 8020429C 00200E7C  93 A1 00 34 */	stw r29, 0x34(r1)
/* 802042A0 00200E80  93 81 00 30 */	stw r28, 0x30(r1)
/* 802042A4 00200E84  83 E3 00 2C */	lwz r31, 0x2c(r3)
/* 802042A8 00200E88  83 A3 00 28 */	lwz r29, 0x28(r3)
/* 802042AC 00200E8C  80 7F 00 C4 */	lwz r3, 0xc4(r31)
/* 802042B0 00200E90  28 1D 00 00 */	cmplwi r29, 0x0
/* 802042B4 00200E94  83 83 00 28 */	lwz r28, 0x28(r3)
/* 802042B8 00200E98  40 82 00 14 */	bne .L_802042CC
/* 802042BC 00200E9C  38 6D 91 20 */	li r3, grVe_804D47C0@sda21
/* 802042C0 00200EA0  38 80 03 D3 */	li r4, 0x3d3
/* 802042C4 00200EA4  38 AD 91 28 */	li r5, grVe_804D47C8@sda21
/* 802042C8 00200EA8  48 18 3F 59 */	bl __assert
.L_802042CC:
/* 802042CC 00200EAC  80 7D 00 38 */	lwz r3, 0x38(r29)
/* 802042D0 00200EB0  28 1C 00 00 */	cmplwi r28, 0x0
/* 802042D4 00200EB4  80 1D 00 3C */	lwz r0, 0x3c(r29)
/* 802042D8 00200EB8  90 61 00 1C */	stw r3, 0x1c(r1)
/* 802042DC 00200EBC  90 01 00 20 */	stw r0, 0x20(r1)
/* 802042E0 00200EC0  80 1D 00 40 */	lwz r0, 0x40(r29)
/* 802042E4 00200EC4  90 01 00 24 */	stw r0, 0x24(r1)
/* 802042E8 00200EC8  40 82 00 14 */	bne .L_802042FC
/* 802042EC 00200ECC  38 6D 91 20 */	li r3, grVe_804D47C0@sda21
/* 802042F0 00200ED0  38 80 03 94 */	li r4, 0x394
/* 802042F4 00200ED4  38 AD 91 28 */	li r5, grVe_804D47C8@sda21
/* 802042F8 00200ED8  48 18 3F 29 */	bl __assert
.L_802042FC:
/* 802042FC 00200EDC  80 61 00 1C */	lwz r3, 0x1c(r1)
/* 80204300 00200EE0  80 01 00 20 */	lwz r0, 0x20(r1)
/* 80204304 00200EE4  90 7C 00 38 */	stw r3, 0x38(r28)
/* 80204308 00200EE8  90 1C 00 3C */	stw r0, 0x3c(r28)
/* 8020430C 00200EEC  80 01 00 24 */	lwz r0, 0x24(r1)
/* 80204310 00200EF0  90 1C 00 40 */	stw r0, 0x40(r28)
/* 80204314 00200EF4  80 1C 00 14 */	lwz r0, 0x14(r28)
/* 80204318 00200EF8  54 00 01 8D */	rlwinm. r0, r0, 0, 6, 6
/* 8020431C 00200EFC  40 82 00 4C */	bne .L_80204368
/* 80204320 00200F00  28 1C 00 00 */	cmplwi r28, 0x0
/* 80204324 00200F04  41 82 00 44 */	beq .L_80204368
/* 80204328 00200F08  40 82 00 14 */	bne .L_8020433C
/* 8020432C 00200F0C  38 6D 91 20 */	li r3, grVe_804D47C0@sda21
/* 80204330 00200F10  38 80 02 34 */	li r4, 0x234
/* 80204334 00200F14  38 AD 91 28 */	li r5, grVe_804D47C8@sda21
/* 80204338 00200F18  48 18 3E E9 */	bl __assert
.L_8020433C:
/* 8020433C 00200F1C  80 9C 00 14 */	lwz r4, 0x14(r28)
/* 80204340 00200F20  38 60 00 00 */	li r3, 0x0
/* 80204344 00200F24  54 80 02 11 */	rlwinm. r0, r4, 0, 8, 8
/* 80204348 00200F28  40 82 00 10 */	bne .L_80204358
/* 8020434C 00200F2C  54 80 06 73 */	rlwinm. r0, r4, 0, 25, 25
/* 80204350 00200F30  41 82 00 08 */	beq .L_80204358
/* 80204354 00200F34  38 60 00 01 */	li r3, 0x1
.L_80204358:
/* 80204358 00200F38  2C 03 00 00 */	cmpwi r3, 0x0
/* 8020435C 00200F3C  40 82 00 0C */	bne .L_80204368
/* 80204360 00200F40  7F 83 E3 78 */	mr r3, r28
/* 80204364 00200F44  48 16 EF 85 */	bl HSD_JObjSetMtxDirtySub
.L_80204368:
/* 80204368 00200F48  4B FB F6 59 */	bl Ground_801C39C0
/* 8020436C 00200F4C  4B FB F8 49 */	bl Ground_801C3BB4
/* 80204370 00200F50  80 7F 00 C8 */	lwz r3, 0xc8(r31)
/* 80204374 00200F54  2C 03 00 00 */	cmpwi r3, 0x0
/* 80204378 00200F58  40 81 00 7C */	ble .L_802043F4
/* 8020437C 00200F5C  38 03 00 01 */	addi r0, r3, 0x1
/* 80204380 00200F60  90 1F 00 C8 */	stw r0, 0xc8(r31)
/* 80204384 00200F64  80 1F 00 C8 */	lwz r0, 0xc8(r31)
/* 80204388 00200F68  2C 00 00 3C */	cmpwi r0, 0x3c
/* 8020438C 00200F6C  41 80 00 68 */	blt .L_802043F4
/* 80204390 00200F70  40 82 00 3C */	bne .L_802043CC
/* 80204394 00200F74  48 0F 25 05 */	bl ifStatus_802F6898
/* 80204398 00200F78  48 0F B1 D9 */	bl un_802FF570
/* 8020439C 00200F7C  38 60 00 01 */	li r3, 0x1
/* 802043A0 00200F80  4B FF FB 0D */	bl grVenom_80203EAC
/* 802043A4 00200F84  28 03 00 00 */	cmplwi r3, 0x0
/* 802043A8 00200F88  41 82 00 4C */	beq .L_802043F4
/* 802043AC 00200F8C  80 83 00 2C */	lwz r4, 0x2c(r3)
/* 802043B0 00200F90  3C A0 00 07 */	lis r5, 0x7
/* 802043B4 00200F94  38 E5 B6 CC */	subi r7, r5, 0x4934
/* 802043B8 00200F98  38 84 00 C4 */	addi r4, r4, 0xc4
/* 802043BC 00200F9C  38 A0 00 04 */	li r5, 0x4
/* 802043C0 00200FA0  38 C0 00 06 */	li r6, 0x6
/* 802043C4 00200FA4  4B FD E2 01 */	bl grCorneria_801E25C4
/* 802043C8 00200FA8  48 00 00 2C */	b .L_802043F4
.L_802043CC:
/* 802043CC 00200FAC  48 0F 24 CD */	bl ifStatus_802F6898
/* 802043D0 00200FB0  48 0F B1 A1 */	bl un_802FF570
/* 802043D4 00200FB4  38 60 00 01 */	li r3, 0x1
/* 802043D8 00200FB8  4B FB E7 CD */	bl Ground_801C2BA4
/* 802043DC 00200FBC  28 03 00 00 */	cmplwi r3, 0x0
/* 802043E0 00200FC0  40 82 00 14 */	bne .L_802043F4
/* 802043E4 00200FC4  48 0F 25 0D */	bl ifStatus_802F68F0
/* 802043E8 00200FC8  48 0F B2 39 */	bl un_802FF620
/* 802043EC 00200FCC  38 00 FF FF */	li r0, -0x1
/* 802043F0 00200FD0  90 1F 00 C8 */	stw r0, 0xc8(r31)
.L_802043F4:
/* 802043F4 00200FD4  4B E0 D2 01 */	bl lb_800115F4
/* 802043F8 00200FD8  4B FF F2 35 */	bl grVenom_8020362C
/* 802043FC 00200FDC  7F C3 F3 78 */	mr r3, r30
/* 80204400 00200FE0  4B FB EB E1 */	bl Ground_801C2FE0
/* 80204404 00200FE4  80 01 00 44 */	lwz r0, 0x44(r1)
/* 80204408 00200FE8  83 E1 00 3C */	lwz r31, 0x3c(r1)
/* 8020440C 00200FEC  83 C1 00 38 */	lwz r30, 0x38(r1)
/* 80204410 00200FF0  83 A1 00 34 */	lwz r29, 0x34(r1)
/* 80204414 00200FF4  83 81 00 30 */	lwz r28, 0x30(r1)
/* 80204418 00200FF8  38 21 00 40 */	addi r1, r1, 0x40
/* 8020441C 00200FFC  7C 08 03 A6 */	mtlr r0
/* 80204420 00201000  4E 80 00 20 */	blr
.endfn grVenom_80204284