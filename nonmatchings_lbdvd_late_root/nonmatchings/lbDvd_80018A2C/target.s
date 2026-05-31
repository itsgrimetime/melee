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
.fn lbDvd_80018A2C, global
/* 80018A2C 0001560C  7C 08 02 A6 */	mflr r0
/* 80018A30 00015610  90 01 00 04 */	stw r0, 0x4(r1)
/* 80018A34 00015614  94 21 FF E8 */	stwu r1, -0x18(r1)
/* 80018A38 00015618  93 E1 00 14 */	stw r31, 0x14(r1)
/* 80018A3C 0001561C  3B E0 00 00 */	li r31, 0x0
/* 80018A40 00015620  93 C1 00 10 */	stw r30, 0x10(r1)
/* 80018A44 00015624  3B C3 00 00 */	addi r30, r3, 0x0
/* 80018A48 00015628  48 32 E9 1D */	bl OSDisableInterrupts
/* 80018A4C 0001562C  3C 80 80 43 */	lis r4, preloadCache@ha
/* 80018A50 00015630  38 A4 20 78 */	addi r5, r4, preloadCache@l
/* 80018A54 00015634  38 85 00 00 */	addi r4, r5, 0x0
/* 80018A58 00015638  57 C0 06 3E */	clrlwi r0, r30, 24
/* 80018A5C 0001563C  38 E0 00 00 */	li r7, 0x0
.L_80018A60:
/* 80018A60 00015640  89 04 00 AC */	lbz r8, 0xac(r4)
/* 80018A64 00015644  38 C4 00 AC */	addi r6, r4, 0xac
/* 80018A68 00015648  7D 08 07 75 */	extsb. r8, r8
/* 80018A6C 0001564C  41 82 01 90 */	beq .L_80018BFC
/* 80018A70 00015650  A9 06 00 08 */	lha r8, 0x8(r6)
/* 80018A74 00015654  2C 08 00 00 */	cmpwi r8, 0x0
/* 80018A78 00015658  40 81 01 84 */	ble .L_80018BFC
/* 80018A7C 0001565C  89 06 00 04 */	lbz r8, 0x4(r6)
/* 80018A80 00015660  7D 08 00 39 */	and. r8, r8, r0
/* 80018A84 00015664  41 82 01 78 */	beq .L_80018BFC
/* 80018A88 00015668  89 26 00 02 */	lbz r9, 0x2(r6)
/* 80018A8C 0001566C  81 05 09 6C */	lwz r8, 0x96c(r5)
/* 80018A90 00015670  7D 29 07 74 */	extsb r9, r9
/* 80018A94 00015674  7C 09 40 00 */	cmpw r9, r8
/* 80018A98 00015678  40 82 00 0C */	bne .L_80018AA4
/* 80018A9C 0001567C  3B E0 00 01 */	li r31, 0x1
/* 80018AA0 00015680  48 00 01 6C */	b .L_80018C0C
.L_80018AA4:
/* 80018AA4 00015684  89 06 00 00 */	lbz r8, 0x0(r6)
/* 80018AA8 00015688  7D 08 07 74 */	extsb r8, r8
/* 80018AAC 0001568C  2C 08 00 03 */	cmpwi r8, 0x3
/* 80018AB0 00015690  41 82 00 28 */	beq .L_80018AD8
/* 80018AB4 00015694  40 80 00 10 */	bge .L_80018AC4
/* 80018AB8 00015698  2C 08 00 01 */	cmpwi r8, 0x1
/* 80018ABC 0001569C  40 80 00 14 */	bge .L_80018AD0
/* 80018AC0 000156A0  48 00 01 3C */	b .L_80018BFC
.L_80018AC4:
/* 80018AC4 000156A4  2C 08 00 05 */	cmpwi r8, 0x5
/* 80018AC8 000156A8  40 80 01 34 */	bge .L_80018BFC
/* 80018ACC 000156AC  48 00 01 2C */	b .L_80018BF8
.L_80018AD0:
/* 80018AD0 000156B0  3B E0 00 01 */	li r31, 0x1
/* 80018AD4 000156B4  48 00 01 38 */	b .L_80018C0C
.L_80018AD8:
/* 80018AD8 000156B8  39 00 00 28 */	li r8, 0x28
/* 80018ADC 000156BC  7D 09 03 A6 */	mtctr r8
/* 80018AE0 000156C0  39 45 00 00 */	addi r10, r5, 0x0
/* 80018AE4 000156C4  3B C0 00 00 */	li r30, 0x0
/* 80018AE8 000156C8  3B E0 00 00 */	li r31, 0x0
/* 80018AEC 000156CC  39 80 00 00 */	li r12, 0x0
.L_80018AF0:
/* 80018AF0 000156D0  89 0A 00 AC */	lbz r8, 0xac(r10)
/* 80018AF4 000156D4  39 6A 00 AC */	addi r11, r10, 0xac
/* 80018AF8 000156D8  2C 08 00 01 */	cmpwi r8, 0x1
/* 80018AFC 000156DC  40 82 00 24 */	bne .L_80018B20
/* 80018B00 000156E0  89 0B 00 02 */	lbz r8, 0x2(r11)
/* 80018B04 000156E4  7D 08 07 74 */	extsb r8, r8
/* 80018B08 000156E8  7C 08 48 00 */	cmpw r8, r9
/* 80018B0C 000156EC  40 82 00 14 */	bne .L_80018B20
/* 80018B10 000156F0  A9 0B 00 08 */	lha r8, 0x8(r11)
/* 80018B14 000156F4  2C 08 00 00 */	cmpwi r8, 0x0
/* 80018B18 000156F8  40 81 00 08 */	ble .L_80018B20
/* 80018B1C 000156FC  3B E0 00 01 */	li r31, 0x1
.L_80018B20:
/* 80018B20 00015700  89 0B 00 00 */	lbz r8, 0x0(r11)
/* 80018B24 00015704  7D 08 07 74 */	extsb r8, r8
/* 80018B28 00015708  2C 08 00 02 */	cmpwi r8, 0x2
/* 80018B2C 0001570C  41 82 00 0C */	beq .L_80018B38
/* 80018B30 00015710  2C 08 00 03 */	cmpwi r8, 0x3
/* 80018B34 00015714  40 82 00 24 */	bne .L_80018B58
.L_80018B38:
/* 80018B38 00015718  89 0B 00 02 */	lbz r8, 0x2(r11)
/* 80018B3C 0001571C  7D 08 07 74 */	extsb r8, r8
/* 80018B40 00015720  7C 08 48 00 */	cmpw r8, r9
/* 80018B44 00015724  40 82 00 14 */	bne .L_80018B58
/* 80018B48 00015728  A9 0B 00 08 */	lha r8, 0x8(r11)
/* 80018B4C 0001572C  2C 08 00 00 */	cmpwi r8, 0x0
/* 80018B50 00015730  40 80 00 08 */	bge .L_80018B58
/* 80018B54 00015734  3B C0 00 01 */	li r30, 0x1
.L_80018B58:
/* 80018B58 00015738  89 0A 00 C8 */	lbz r8, 0xc8(r10)
/* 80018B5C 0001573C  39 6A 00 C8 */	addi r11, r10, 0xc8
/* 80018B60 00015740  39 4A 00 1C */	addi r10, r10, 0x1c
/* 80018B64 00015744  2C 08 00 01 */	cmpwi r8, 0x1
/* 80018B68 00015748  40 82 00 24 */	bne .L_80018B8C
/* 80018B6C 0001574C  89 0B 00 02 */	lbz r8, 0x2(r11)
/* 80018B70 00015750  7D 08 07 74 */	extsb r8, r8
/* 80018B74 00015754  7C 08 48 00 */	cmpw r8, r9
/* 80018B78 00015758  40 82 00 14 */	bne .L_80018B8C
/* 80018B7C 0001575C  A9 0B 00 08 */	lha r8, 0x8(r11)
/* 80018B80 00015760  2C 08 00 00 */	cmpwi r8, 0x0
/* 80018B84 00015764  40 81 00 08 */	ble .L_80018B8C
/* 80018B88 00015768  3B E0 00 01 */	li r31, 0x1
.L_80018B8C:
/* 80018B8C 0001576C  89 0B 00 00 */	lbz r8, 0x0(r11)
/* 80018B90 00015770  7D 08 07 74 */	extsb r8, r8
/* 80018B94 00015774  2C 08 00 02 */	cmpwi r8, 0x2
/* 80018B98 00015778  41 82 00 0C */	beq .L_80018BA4
/* 80018B9C 0001577C  2C 08 00 03 */	cmpwi r8, 0x3
/* 80018BA0 00015780  40 82 00 24 */	bne .L_80018BC4
.L_80018BA4:
/* 80018BA4 00015784  89 0B 00 02 */	lbz r8, 0x2(r11)
/* 80018BA8 00015788  7D 08 07 74 */	extsb r8, r8
/* 80018BAC 0001578C  7C 08 48 00 */	cmpw r8, r9
/* 80018BB0 00015790  40 82 00 14 */	bne .L_80018BC4
/* 80018BB4 00015794  A9 0B 00 08 */	lha r8, 0x8(r11)
/* 80018BB8 00015798  2C 08 00 00 */	cmpwi r8, 0x0
/* 80018BBC 0001579C  40 80 00 08 */	bge .L_80018BC4
/* 80018BC0 000157A0  3B C0 00 01 */	li r30, 0x1
.L_80018BC4:
/* 80018BC4 000157A4  39 4A 00 1C */	addi r10, r10, 0x1c
/* 80018BC8 000157A8  39 8C 00 01 */	addi r12, r12, 0x1
/* 80018BCC 000157AC  42 00 FF 24 */	bdnz .L_80018AF0
/* 80018BD0 000157B0  2C 1F 00 00 */	cmpwi r31, 0x0
/* 80018BD4 000157B4  41 82 00 14 */	beq .L_80018BE8
/* 80018BD8 000157B8  2C 1E 00 00 */	cmpwi r30, 0x0
/* 80018BDC 000157BC  41 82 00 0C */	beq .L_80018BE8
/* 80018BE0 000157C0  3B E0 00 01 */	li r31, 0x1
/* 80018BE4 000157C4  48 00 00 28 */	b .L_80018C0C
.L_80018BE8:
/* 80018BE8 000157C8  39 00 00 04 */	li r8, 0x4
/* 80018BEC 000157CC  99 06 00 00 */	stb r8, 0x0(r6)
/* 80018BF0 000157D0  39 00 27 0F */	li r8, 0x270f
/* 80018BF4 000157D4  B1 06 00 08 */	sth r8, 0x8(r6)
.L_80018BF8:
/* 80018BF8 000157D8  3B E0 00 02 */	li r31, 0x2
.L_80018BFC:
/* 80018BFC 000157DC  38 E7 00 01 */	addi r7, r7, 0x1
/* 80018C00 000157E0  2C 07 00 50 */	cmpwi r7, 0x50
/* 80018C04 000157E4  38 84 00 1C */	addi r4, r4, 0x1c
/* 80018C08 000157E8  41 80 FE 58 */	blt .L_80018A60
.L_80018C0C:
/* 80018C0C 000157EC  48 32 E7 81 */	bl OSRestoreInterrupts
/* 80018C10 000157F0  7F E3 FB 78 */	mr r3, r31
/* 80018C14 000157F4  80 01 00 1C */	lwz r0, 0x1c(r1)
/* 80018C18 000157F8  83 E1 00 14 */	lwz r31, 0x14(r1)
/* 80018C1C 000157FC  83 C1 00 10 */	lwz r30, 0x10(r1)
/* 80018C20 00015800  38 21 00 18 */	addi r1, r1, 0x18
/* 80018C24 00015804  7C 08 03 A6 */	mtlr r0
/* 80018C28 00015808  4E 80 00 20 */	blr
.endfn lbDvd_80018A2C
