<Qucs Schematic 26.1.1>
<Properties>
  <View=0,0,1200,700,1,0,0>
  <Grid=10,10,1>
  <DataSet=04-diode-rectifier.dat>
  <DataDisplay=04-diode-rectifier.dpl>
  <OpenDisplay=0>
  <Script=04-diode-rectifier.m>
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
  <S4Q_V V1 1 100 200 18 -26 0 1 "SIN(0 10 1k)" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 100 260 0 0 0 0>
  <DIODE_SPICE D1 1 200 140 -26 15 0 0 "DVAL" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "D" 0>
  <R_SPICE RL 1 300 200 15 -26 0 1 "1k" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "R" 0>
  <GND * 1 300 260 0 0 0 0>
  <SpiceModel SpiceModel1 1 80 330 -27 16 0 0 ".model DVAL D(IS=1e-14 N=1 RS=0 CJO=0)" 1 "" 0 "" 0 "" 0 "Line_5=" 0>
  <.TR TR1 1 80 400 0 65 0 0 "lin" 1 "0" 1 "2 ms" 1 "2001" 0 "Trapezoidal" 0 "2" 0 "1 ns" 0 "1e-16" 0 "150" 0 "0.001" 0 "1 pA" 0 "1 uV" 0 "26.85" 0 "1e-3" 0 "1e-6" 0 "1" 0 "CroutLU" 0 "no" 0 "yes" 0 "0" 0>
</Components>
<Wires>
  <100 230 100 260 "" 0 0 0 "">
  <100 140 100 170 "" 0 0 0 "">
  <100 140 170 140 "in" 120 100 20 "">
  <230 140 300 140 "out" 260 100 30 "">
  <300 140 300 170 "" 0 0 0 "">
  <300 230 300 260 "" 0 0 0 "">
</Wires>
<Diagrams>
  <Rect 460 420 560 320 3 #c0c0c0 1 00 1 0 0.0002 0.002 1 -11 2 11 1 -1 0.5 1 315 0 225 1 0 0 "time (s)" "" "">
	<"ngspice/tran.v(out)" #0000ff 2 3 0 0 0>
	<"ngspice/tran.v(in)" #ff0000 1 3 0 0 0>
  </Rect>
</Diagrams>
<Paintings>
  <Text 80 20 12 #000000 0 "04-diode-rectifier: half-wave rectifier, Shockley diode IS=1e-14 N=1">
</Paintings>
