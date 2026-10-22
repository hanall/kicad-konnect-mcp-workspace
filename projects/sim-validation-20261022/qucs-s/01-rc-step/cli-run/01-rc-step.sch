<Qucs Schematic 26.1.1>
<Properties>
  <View=0,0,1200,700,1,0,0>
  <Grid=10,10,1>
  <DataSet=01-rc-step.dat>
  <DataDisplay=01-rc-step.dpl>
  <OpenDisplay=0>
  <Script=01-rc-step.m>
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
  <S4Q_V V1 1 100 200 18 -26 0 1 "PULSE(0 5 0 1n 1n 10m 20m)" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 100 260 0 0 0 0>
  <R_SPICE R1 1 200 140 -26 15 0 0 "1k" 1 "" 0 "" 0 "" 0 "" 0 "2" 1 "R" 1>
  <C_SPICE C1 1 300 200 17 -26 0 1 "1u" 1 "" 0 "" 0 "" 0 "" 0 "2" 1 "C" 1>
  <GND * 1 300 260 0 0 0 0>
  <.TR TR1 1 80 330 0 65 0 0 "lin" 1 "0" 1 "5 ms" 1 "5001" 0 "Trapezoidal" 0 "2" 0 "1 ns" 0 "1e-16" 0 "150" 0 "0.001" 0 "1 pA" 0 "1 uV" 0 "26.85" 0 "1e-3" 0 "1e-6" 0 "1" 0 "CroutLU" 0 "no" 0 "yes" 0 "0" 0>
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
  <Rect 460 380 500 300 3 #c0c0c0 1 00 1 0 0.001 0.005 1 -0.5 1 5.5 1 -1 0.5 1 315 0 225 1 0 0 "time (s)" "" "">
	<"ngspice/tran.v(out)" #0000ff 2 3 0 0 0>
	<"ngspice/tran.v(in)" #ff0000 1 3 0 0 0>
  </Rect>
</Diagrams>
<Paintings>
  <Text 80 20 12 #000000 0 "01-rc-step: RC step response (tau = 1 ms), spec netlist_body as SPICE components">
</Paintings>
