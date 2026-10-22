<Qucs Schematic 26.1.1>
<Properties>
  <View=0,0,1300,760,1,0,0>
  <Grid=10,10,1>
  <DataSet=03-opamp-noninv.dat>
  <DataDisplay=03-opamp-noninv.dpl>
  <OpenDisplay=0>
  <Script=03-opamp-noninv.m>
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
  <S4Q_V VCC 1 100 200 18 -26 0 1 "DC 15" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 100 260 0 0 0 0>
  <S4Q_V VEE 1 200 200 18 -26 0 1 "DC -15" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 200 260 0 0 0 0>
  <S4Q_V VIN 1 300 380 18 -26 0 1 "DC 0 SIN(0 0.1 1k) AC 1" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 300 440 0 0 0 0>
  <SpLib X1 1 480 300 -19 90 0 0 "kicad_builtin_opamp.lib" 1 "kicad_builtin_opamp" 1 "auto" 0 "POLE=20 GAIN=20k VOFF=0 ROUT=10" 1 "" 0>
  <R_SPICE R1 1 640 330 15 -26 0 1 "1k" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "R" 0>
  <GND * 1 640 380 0 0 0 0>
  <R_SPICE R2 1 720 240 -26 15 0 0 "9k" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "R" 0>
  <.TR TR1 1 80 520 0 65 0 0 "lin" 1 "0" 1 "3 ms" 1 "3001" 0 "Trapezoidal" 0 "2" 0 "1 ns" 0 "1e-16" 0 "150" 0 "0.001" 0 "1 pA" 0 "1 uV" 0 "26.85" 0 "1e-3" 0 "1e-6" 0 "1" 0 "CroutLU" 0 "no" 0 "yes" 0 "0" 0>
  <.AC AC1 1 300 520 0 40 0 0 "log" 1 "1 Hz" 1 "10 MHz" 1 "701" 1 "no" 0>
  <NutmegEq NutmegEq1 1 500 520 -30 18 0 0 "ac" 1 "gain_db=db(v(out))" 1>
</Components>
<Wires>
  <100 230 100 260 "" 0 0 0 "">
  <100 140 100 170 "vcc" 120 110 0 "">
  <200 230 200 260 "" 0 0 0 "">
  <200 140 200 170 "vee" 220 110 0 "">
  <300 410 300 440 "" 0 0 0 "">
  <300 320 300 350 "in" 320 290 0 "">
  <420 240 450 240 "in" 400 200 0 "">
  <510 240 540 240 "inn" 530 200 30 "">
  <420 300 450 300 "vcc" 390 270 0 "">
  <510 300 540 300 "vee" 530 270 30 "">
  <420 360 450 360 "out" 390 330 0 "">
  <640 240 690 240 "inn" 640 200 0 "">
  <640 240 640 300 "" 0 0 0 "">
  <640 360 640 380 "" 0 0 0 "">
  <750 240 800 240 "out" 780 200 50 "">
</Wires>
<Diagrams>
  <Rect 880 330 400 250 3 #c0c0c0 1 00 1 0 0.0005 0.003 1 -1.2 0.5 1.2 1 -1 0.5 1 315 0 225 1 0 0 "time (s)" "" "">
	<"ngspice/tran.v(out)" #0000ff 2 3 0 0 0>
	<"ngspice/tran.v(in)" #ff0000 1 3 0 0 0>
  </Rect>
  <Rect 880 680 400 250 3 #c0c0c0 1 10 1 1 1 1e+07 1 -40 10 25 1 -1 0.5 1 315 0 225 1 0 0 "frequency (Hz)" "gain (dB)" "">
	<"ngspice/ac.gain_db" #0000ff 2 3 0 0 0>
  </Rect>
</Diagrams>
<Paintings>
  <Text 80 20 12 #000000 0 "03-opamp-noninv: non-inverting amp (gain 10) with KiCad built-in single-pole op amp subcircuit (SPICE library device)">
</Paintings>
