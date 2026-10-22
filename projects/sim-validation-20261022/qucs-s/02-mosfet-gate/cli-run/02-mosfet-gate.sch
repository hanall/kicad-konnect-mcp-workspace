<Qucs Schematic 26.1.1>
<Properties>
  <View=0,0,1300,700,1,0,0>
  <Grid=10,10,1>
  <DataSet=02-mosfet-gate.dat>
  <DataDisplay=02-mosfet-gate.dpl>
  <OpenDisplay=0>
  <Script=02-mosfet-gate.m>
  <RunScript=0>
  <showFrame=0>
  <FrameText0=Title>
  <FrameText1=Drawn By:>
  <FrameText2=Date:>
  <FrameText3=Revision:>
</Properties>
<Symbol>
</Symbol>
<Components>
  <S4Q_V VG 1 160 360 18 -26 0 1 "PULSE(0 10 0 1n 1n 50u 100u)" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 160 420 0 0 0 0>
  <R_SPICE RG 1 240 300 -26 15 0 0 "100" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "R" 0>
  <C_SPICE CG 1 340 360 17 -26 0 1 "10n" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "C" 0>
  <GND * 1 340 420 0 0 0 0>
  <NMOS_SPICE M1 1 440 300 30 10 0 0 "NM1 W=100u L=100u" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 440 360 0 0 0 0>
  <GND * 1 490 360 0 0 0 0>
  <R_SPICE RL 1 440 180 15 -26 0 1 "100" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "R" 0>
  <S4Q_V VDD 1 560 200 18 -26 0 1 "DC 12" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 560 260 0 0 0 0>
  <SpiceModel SpiceModel1 1 100 470 -27 16 0 0 ".model NM1 NMOS(LEVEL=1 VTO=2 KP=0.5 LAMBDA=0 TOX=1e-7 CGSO=0 CGDO=0 CBD=0 CBS=0)" 1 "" 0 "" 0 "" 0 "Line_5=" 0>
  <.TR TR1 1 100 540 0 65 0 0 "lin" 1 "0" 1 "20 us" 1 "20001" 0 "Trapezoidal" 0 "2" 0 "1 ns" 0 "1e-16" 0 "150" 0 "0.001" 0 "1 pA" 0 "1 uV" 0 "26.85" 0 "1e-3" 0 "1e-6" 0 "1" 0 "CroutLU" 0 "no" 0 "yes" 0 "0" 0>
</Components>
<Wires>
  <160 390 160 420 "" 0 0 0 "">
  <160 300 160 330 "" 0 0 0 "">
  <160 300 210 300 "gsrc" 170 260 20 "">
  <270 300 340 300 "g" 300 260 30 "">
  <340 300 340 330 "" 0 0 0 "">
  <340 390 340 420 "" 0 0 0 "">
  <340 300 410 300 "" 0 0 0 "">
  <440 330 440 360 "" 0 0 0 "">
  <460 300 490 300 "" 0 0 0 "">
  <490 300 490 360 "" 0 0 0 "">
  <440 210 440 270 "d" 400 220 30 "">
  <440 120 440 150 "" 0 0 0 "">
  <440 120 560 120 "vdd" 490 90 50 "">
  <560 120 560 170 "" 0 0 0 "">
  <560 230 560 260 "" 0 0 0 "">
</Wires>
<Diagrams>
  <Rect 660 460 560 340 3 #c0c0c0 1 00 1 0 2e-06 2e-05 1 -1 2 13 1 -1 0.5 1 315 0 225 1 0 0 "time (s)" "" "">
	<"ngspice/tran.v(g)" #0000ff 2 3 0 0 0>
	<"ngspice/tran.v(d)" #ff0000 2 3 0 0 0>
	<"ngspice/tran.v(gsrc)" #00aa00 1 3 0 0 0>
  </Rect>
</Diagrams>
<Paintings>
  <Text 80 20 12 #000000 0 "02-mosfet-gate: NMOS level 1 gate-drive switching (RG*CG = 1 us)">
</Paintings>
