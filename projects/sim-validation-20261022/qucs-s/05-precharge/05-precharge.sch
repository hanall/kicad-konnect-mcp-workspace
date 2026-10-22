<Qucs Schematic 26.1.1>
<Properties>
  <View=0,0,1300,700,1,0,0>
  <Grid=10,10,1>
  <DataSet=05-precharge.dat>
  <DataDisplay=05-precharge.dpl>
  <OpenDisplay=0>
  <Script=05-precharge.m>
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
  <S4Q_V V1 1 100 200 18 -26 0 1 "PULSE(0 48 0 1u 1u 10 20)" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 100 260 0 0 0 0>
  <R_SPICE RPRE 1 200 140 -26 15 0 0 "47" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "R" 0>
  <C_SPICE CBUS 1 300 200 17 -26 0 1 "4700u" 1 "" 0 "" 0 "" 0 "" 0 "2" 0 "C" 0>
  <GND * 1 300 260 0 0 0 0>
  <src_eqndef B1 1 440 200 18 -26 0 1 "i(V1)*i(V1)*47" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 440 260 0 0 0 0>
  <src_eqndef B2 1 600 200 18 -26 0 1 "-i(V1)" 1 "" 0 "" 0 "" 0 "" 0>
  <GND * 1 600 260 0 0 0 0>
  <.TR TR1 1 80 330 0 65 0 0 "lin" 1 "0" 1 "3 s" 1 "30001" 0 "Trapezoidal" 0 "2" 0 "1 ns" 0 "1e-16" 0 "150" 0 "0.001" 0 "1 pA" 0 "1 uV" 0 "26.85" 0 "1e-3" 0 "1e-6" 0 "1" 0 "CroutLU" 0 "no" 0 "yes" 0 "0" 0>
</Components>
<Wires>
  <100 230 100 260 "" 0 0 0 "">
  <100 140 100 170 "" 0 0 0 "">
  <100 140 170 140 "in" 120 100 20 "">
  <230 140 300 140 "bus" 260 100 30 "">
  <300 140 300 170 "" 0 0 0 "">
  <300 230 300 260 "" 0 0 0 "">
  <440 140 440 170 "p" 460 120 0 "">
  <440 230 440 260 "" 0 0 0 "">
  <600 140 600 170 "ia" 620 120 0 "">
  <600 230 600 260 "" 0 0 0 "">
</Wires>
<Diagrams>
  <Rect 760 420 480 320 3 #c0c0c0 1 00 1 0 0.5 3 1 -5 10 55 1 -1 0.5 1 315 0 225 1 0 0 "time (s)" "" "">
	<"ngspice/tran.v(bus)" #0000ff 2 3 0 0 0>
	<"ngspice/tran.v(p)" #ff0000 2 3 0 0 0>
	<"ngspice/tran.v(ia)" #00aa00 2 3 0 0 0>
  </Rect>
</Diagrams>
<Paintings>
  <Text 80 20 12 #000000 0 "05-precharge: 48 V precharge through 47 Ohm into 4700 uF (tau = 0.2209 s); B1 = resistor power, B2 = inrush current">
</Paintings>
