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
.fn gm_80173EEC, global
/* 80173EEC 00170ACC  7C 08 02 A6 */	mflr r0
/* 80173EF0 00170AD0  90 01 00 04 */	stw r0, 0x4(r1)
/* 80173EF4 00170AD4  94 21 FF E8 */	stwu r1, -0x18(r1)
/* 80173EF8 00170AD8  93 E1 00 14 */	stw r31, 0x14(r1)
/* 80173EFC 00170ADC  3B E0 00 00 */	li r31, 0x0
/* 80173F00 00170AE0  93 C1 00 10 */	stw r30, 0x10(r1)
/* 80173F04 00170AE4  3B C0 00 00 */	li r30, 0x0
/* 80173F08 00170AE8  93 A1 00 0C */	stw r29, 0xc(r1)
/* 80173F0C 00170AEC  93 81 00 08 */	stw r28, 0x8(r1)
.L_80173F10:
/* 80173F10 00170AF0  4B FE AE AD */	bl gmMainLib_8015EDBC
/* 80173F14 00170AF4  3B BE 00 18 */	addi r29, r30, 0x18
/* 80173F18 00170AF8  7F A3 EA 14 */	add r29, r3, r29
/* 80173F1C 00170AFC  A0 1D 00 00 */	lhz r0, 0x0(r29)
/* 80173F20 00170B00  28 00 00 64 */	cmplwi r0, 0x64
/* 80173F24 00170B04  41 80 00 58 */	blt .L_80173F7C
/* 80173F28 00170B08  57 E3 06 3E */	clrlwi r3, r31, 24
/* 80173F2C 00170B0C  4B FF 00 E1 */	bl gm_8016400C
/* 80173F30 00170B10  3B 83 00 00 */	addi r28, r3, 0x0
/* 80173F34 00170B14  54 63 06 3E */	clrlwi r3, r3, 24
/* 80173F38 00170B18  38 80 00 03 */	li r4, 0x3
/* 80173F3C 00170B1C  4B FE C5 39 */	bl gm_80160474
/* 80173F40 00170B20  4B FF ED 39 */	bl fn_80172C78
/* 80173F44 00170B24  57 80 06 3E */	clrlwi r0, r28, 24
/* 80173F48 00170B28  28 00 00 12 */	cmplwi r0, 0x12
/* 80173F4C 00170B2C  40 82 00 14 */	bne .L_80173F60
/* 80173F50 00170B30  38 60 00 13 */	li r3, 0x13
/* 80173F54 00170B34  38 80 00 03 */	li r4, 0x3
/* 80173F58 00170B38  4B FE C5 1D */	bl gm_80160474
/* 80173F5C 00170B3C  4B FF ED 1D */	bl fn_80172C78
.L_80173F60:
/* 80173F60 00170B40  57 80 06 3E */	clrlwi r0, r28, 24
/* 80173F64 00170B44  28 00 00 13 */	cmplwi r0, 0x13
/* 80173F68 00170B48  40 82 00 14 */	bne .L_80173F7C
/* 80173F6C 00170B4C  38 60 00 12 */	li r3, 0x12
/* 80173F70 00170B50  38 80 00 03 */	li r4, 0x3
/* 80173F74 00170B54  4B FE C5 01 */	bl gm_80160474
/* 80173F78 00170B58  4B FF ED 01 */	bl fn_80172C78
.L_80173F7C:
/* 80173F7C 00170B5C  A0 1D 00 00 */	lhz r0, 0x0(r29)
/* 80173F80 00170B60  28 00 00 C8 */	cmplwi r0, 0xc8
/* 80173F84 00170B64  41 80 00 58 */	blt .L_80173FDC
/* 80173F88 00170B68  57 E3 06 3E */	clrlwi r3, r31, 24
/* 80173F8C 00170B6C  4B FF 00 81 */	bl gm_8016400C
/* 80173F90 00170B70  3B 83 00 00 */	addi r28, r3, 0x0
/* 80173F94 00170B74  54 63 06 3E */	clrlwi r3, r3, 24
/* 80173F98 00170B78  38 80 00 04 */	li r4, 0x4
/* 80173F9C 00170B7C  4B FE C4 D9 */	bl gm_80160474
/* 80173FA0 00170B80  4B FF EC D9 */	bl fn_80172C78
/* 80173FA4 00170B84  57 80 06 3E */	clrlwi r0, r28, 24
/* 80173FA8 00170B88  28 00 00 12 */	cmplwi r0, 0x12
/* 80173FAC 00170B8C  40 82 00 14 */	bne .L_80173FC0
/* 80173FB0 00170B90  38 60 00 13 */	li r3, 0x13
/* 80173FB4 00170B94  38 80 00 04 */	li r4, 0x4
/* 80173FB8 00170B98  4B FE C4 BD */	bl gm_80160474
/* 80173FBC 00170B9C  4B FF EC BD */	bl fn_80172C78
.L_80173FC0:
/* 80173FC0 00170BA0  57 80 06 3E */	clrlwi r0, r28, 24
/* 80173FC4 00170BA4  28 00 00 13 */	cmplwi r0, 0x13
/* 80173FC8 00170BA8  40 82 00 14 */	bne .L_80173FDC
/* 80173FCC 00170BAC  38 60 00 12 */	li r3, 0x12
/* 80173FD0 00170BB0  38 80 00 04 */	li r4, 0x4
/* 80173FD4 00170BB4  4B FE C4 A1 */	bl gm_80160474
/* 80173FD8 00170BB8  4B FF EC A1 */	bl fn_80172C78
.L_80173FDC:
/* 80173FDC 00170BBC  A0 1D 00 00 */	lhz r0, 0x0(r29)
/* 80173FE0 00170BC0  28 00 01 2C */	cmplwi r0, 0x12c
/* 80173FE4 00170BC4  41 80 00 58 */	blt .L_8017403C
/* 80173FE8 00170BC8  57 E3 06 3E */	clrlwi r3, r31, 24
/* 80173FEC 00170BCC  4B FF 00 21 */	bl gm_8016400C
/* 80173FF0 00170BD0  3B A3 00 00 */	addi r29, r3, 0x0
/* 80173FF4 00170BD4  54 63 06 3E */	clrlwi r3, r3, 24
/* 80173FF8 00170BD8  38 80 00 05 */	li r4, 0x5
/* 80173FFC 00170BDC  4B FE C4 79 */	bl gm_80160474
/* 80174000 00170BE0  4B FF EC 79 */	bl fn_80172C78
/* 80174004 00170BE4  57 A0 06 3E */	clrlwi r0, r29, 24
/* 80174008 00170BE8  28 00 00 12 */	cmplwi r0, 0x12
/* 8017400C 00170BEC  40 82 00 14 */	bne .L_80174020
/* 80174010 00170BF0  38 60 00 13 */	li r3, 0x13
/* 80174014 00170BF4  38 80 00 05 */	li r4, 0x5
/* 80174018 00170BF8  4B FE C4 5D */	bl gm_80160474
/* 8017401C 00170BFC  4B FF EC 5D */	bl fn_80172C78
.L_80174020:
/* 80174020 00170C00  57 A0 06 3E */	clrlwi r0, r29, 24
/* 80174024 00170C04  28 00 00 13 */	cmplwi r0, 0x13
/* 80174028 00170C08  40 82 00 14 */	bne .L_8017403C
/* 8017402C 00170C0C  38 60 00 12 */	li r3, 0x12
/* 80174030 00170C10  38 80 00 05 */	li r4, 0x5
/* 80174034 00170C14  4B FE C4 41 */	bl gm_80160474
/* 80174038 00170C18  4B FF EC 41 */	bl fn_80172C78
.L_8017403C:
/* 8017403C 00170C1C  3B FF 00 01 */	addi r31, r31, 0x1
/* 80174040 00170C20  2C 1F 00 19 */	cmpwi r31, 0x19
/* 80174044 00170C24  3B DE 00 02 */	addi r30, r30, 0x2
/* 80174048 00170C28  41 80 FE C8 */	blt .L_80173F10
/* 8017404C 00170C2C  4B FF 0A FD */	bl fn_80164B48
/* 80174050 00170C30  2C 03 00 00 */	cmpwi r3, 0x0
/* 80174054 00170C34  41 82 00 0C */	beq .L_80174060
/* 80174058 00170C38  38 60 00 A0 */	li r3, 0xa0
/* 8017405C 00170C3C  4B FF EC 1D */	bl fn_80172C78
.L_80174060:
/* 80174060 00170C40  4B FF 0A 5D */	bl gm_80164ABC
/* 80174064 00170C44  2C 03 00 00 */	cmpwi r3, 0x0
/* 80174068 00170C48  41 82 00 0C */	beq .L_80174074
/* 8017406C 00170C4C  38 60 00 9F */	li r3, 0x9f
/* 80174070 00170C50  4B FF EC 09 */	bl fn_80172C78
.L_80174074:
/* 80174074 00170C54  4B FE AE 1D */	bl gmMainLib_8015EE90
/* 80174078 00170C58  2C 03 00 00 */	cmpwi r3, 0x0
/* 8017407C 00170C5C  41 82 00 0C */	beq .L_80174088
/* 80174080 00170C60  38 60 00 DC */	li r3, 0xdc
/* 80174084 00170C64  4B FF EB F5 */	bl fn_80172C78
.L_80174088:
/* 80174088 00170C68  4B FE AD 35 */	bl gmMainLib_8015EDBC
/* 8017408C 00170C6C  80 03 00 14 */	lwz r0, 0x14(r3)
/* 80174090 00170C70  28 00 27 10 */	cmplwi r0, 0x2710
/* 80174094 00170C74  41 80 00 0C */	blt .L_801740A0
/* 80174098 00170C78  38 60 01 0C */	li r3, 0x10c
/* 8017409C 00170C7C  4B FF EB DD */	bl fn_80172C78
.L_801740A0:
/* 801740A0 00170C80  38 60 00 1A */	li r3, 0x1a
/* 801740A4 00170C84  4B FE 98 A9 */	bl gmMainLib_8015D94C
/* 801740A8 00170C88  2C 03 00 00 */	cmpwi r3, 0x0
/* 801740AC 00170C8C  41 82 00 0C */	beq .L_801740B8
/* 801740B0 00170C90  38 60 00 96 */	li r3, 0x96
/* 801740B4 00170C94  4B FF EB C5 */	bl fn_80172C78
.L_801740B8:
/* 801740B8 00170C98  48 19 04 E9 */	bl un_803045A0
/* 801740BC 00170C9C  2C 03 00 00 */	cmpwi r3, 0x0
/* 801740C0 00170CA0  41 82 00 0C */	beq .L_801740CC
/* 801740C4 00170CA4  38 60 01 16 */	li r3, 0x116
/* 801740C8 00170CA8  4B FF EB B1 */	bl fn_80172C78
.L_801740CC:
/* 801740CC 00170CAC  48 19 05 C5 */	bl un_80304690
/* 801740D0 00170CB0  2C 03 00 00 */	cmpwi r3, 0x0
/* 801740D4 00170CB4  41 82 00 0C */	beq .L_801740E0
/* 801740D8 00170CB8  38 60 00 AF */	li r3, 0xaf
/* 801740DC 00170CBC  4B FF EB 9D */	bl fn_80172C78
.L_801740E0:
/* 801740E0 00170CC0  48 19 06 A1 */	bl un_80304780
/* 801740E4 00170CC4  2C 03 00 00 */	cmpwi r3, 0x0
/* 801740E8 00170CC8  41 82 00 0C */	beq .L_801740F4
/* 801740EC 00170CCC  38 60 01 00 */	li r3, 0x100
/* 801740F0 00170CD0  4B FF EB 89 */	bl fn_80172C78
.L_801740F4:
/* 801740F4 00170CD4  3B A0 00 01 */	li r29, 0x1
/* 801740F8 00170CD8  3B 80 00 00 */	li r28, 0x0
.L_801740FC:
/* 801740FC 00170CDC  2C 1C 00 29 */	cmpwi r28, 0x29
/* 80174100 00170CE0  41 82 00 44 */	beq .L_80174144
/* 80174104 00170CE4  38 1C FF BE */	subi r0, r28, 0x42
/* 80174108 00170CE8  28 00 00 01 */	cmplwi r0, 0x1
/* 8017410C 00170CEC  40 81 00 38 */	ble .L_80174144
/* 80174110 00170CF0  2C 1C 00 B9 */	cmpwi r28, 0xb9
/* 80174114 00170CF4  41 82 00 30 */	beq .L_80174144
/* 80174118 00170CF8  38 1C FF 37 */	subi r0, r28, 0xc9
/* 8017411C 00170CFC  28 00 00 01 */	cmplwi r0, 0x1
/* 80174120 00170D00  40 81 00 24 */	ble .L_80174144
/* 80174124 00170D04  2C 1C 00 09 */	cmpwi r28, 0x9
/* 80174128 00170D08  41 82 00 1C */	beq .L_80174144
/* 8017412C 00170D0C  7F 83 E3 78 */	mr r3, r28
/* 80174130 00170D10  4B FE 99 AD */	bl gmMainLib_8015DADC
/* 80174134 00170D14  2C 03 00 00 */	cmpwi r3, 0x0
/* 80174138 00170D18  40 82 00 0C */	bne .L_80174144
/* 8017413C 00170D1C  3B A0 00 00 */	li r29, 0x0
/* 80174140 00170D20  48 00 00 10 */	b .L_80174150
.L_80174144:
/* 80174144 00170D24  3B 9C 00 01 */	addi r28, r28, 0x1
/* 80174148 00170D28  2C 1C 01 00 */	cmpwi r28, 0x100
/* 8017414C 00170D2C  41 80 FF B0 */	blt .L_801740FC
.L_80174150:
/* 80174150 00170D30  2C 1D 00 00 */	cmpwi r29, 0x0
/* 80174154 00170D34  41 82 00 0C */	beq .L_80174160
/* 80174158 00170D38  38 60 01 23 */	li r3, 0x123
/* 8017415C 00170D3C  4B FF EB 1D */	bl fn_80172C78
.L_80174160:
/* 80174160 00170D40  80 01 00 1C */	lwz r0, 0x1c(r1)
/* 80174164 00170D44  83 E1 00 14 */	lwz r31, 0x14(r1)
/* 80174168 00170D48  83 C1 00 10 */	lwz r30, 0x10(r1)
/* 8017416C 00170D4C  83 A1 00 0C */	lwz r29, 0xc(r1)
/* 80174170 00170D50  83 81 00 08 */	lwz r28, 0x8(r1)
/* 80174174 00170D54  38 21 00 18 */	addi r1, r1, 0x18
/* 80174178 00170D58  7C 08 03 A6 */	mtlr r0
/* 8017417C 00170D5C  4E 80 00 20 */	blr
.endfn gm_80173EEC