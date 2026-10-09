# Disclaimer

MotionSim is an exploratory tool. It estimates losses and temperatures in motor-drive power stages from datasheet values, stated assumptions and simplified models.

**It can be wrong.** Datasheets are read partly by a language model. Missing data is filled with computed or assumed values. The models leave physics out; each result lists some of what it leaves out, not all. The tool has been compared with one vendor simulator on one part, and with no measurement.

**It is not a substitute for engineering judgement, verification or testing.** Do not use its output alone to design, size, select, approve or certify any hardware. Before building or operating anything:

- check every value against the component manufacturer's current datasheet and application notes;
- verify losses and temperatures by measurement on real hardware, under worst-case conditions;
- apply the electrical, thermal and functional safety standards that govern your product and jurisdiction;
- have the design reviewed by a qualified engineer.

**Power electronics is hazardous.** Circuits of the kind this tool describes involve lethal voltages, high currents, stored energy and components that can fail violently. A design error can cause fire, equipment damage, injury or death.

**No warranty, no liability.** The software is provided "as is", without warranty of any kind, express or implied, including fitness for a particular purpose. To the fullest extent permitted by law, the authors and contributors are not liable for any claim, damage, injury, loss or other liability, whether direct or indirect, arising from the software or its use, including any design error or accident. This restates and does not limit sections 7 and 8 of the Apache License 2.0 in `LICENSE`.

By using the software you accept these terms. If you do not, do not use it.
