"""The C export of a control scheme: an engine-generated control law in portable C99 (also
C++), and the replay that proves it steps as the simulation does.

- `writer.generate`: a compiled scheme as `motionsim_ctrl.h` and `motionsim_ctrl.c`;
- `support.check`: the refusal, by name, of what the export does not cover yet;
- `replay`: the run's sampled inputs and the engine's every wire, the harness that feeds the
  one to the C and compares it with the other, and its compilation on the host;
- `bundle`: the zip handed over, with its README.

No language model is involved: the C is written from the blocks' own figures.
"""

from motionsim.control.codegen.support import KINDS, SCHEMES, check
from motionsim.control.codegen.writer import Generated, generate

__all__ = ["KINDS", "SCHEMES", "Generated", "check", "generate"]
