# Universal ADAM and OMCA ANFDA Report Extractor

The app automatically detects:

1. **ADAM Skid Process Report** using `PROCESS CYCLE`, `CYCLE RECORD`, full date-time rows, and ADAM instrument families such as `LSICR`, `PICR`, `TA`, `TLP`, and `RLS`.
2. **OMCA ANFDA Drying Report** using `ANFD-2 PROCESS SYSTEM`, `TT-01`, `TT-02`, `PT-01`, `Filter_Pos`, `Agit_Rpm`, `Agit_Pos`, and `PROGRESSIVE` markers.

If detection is inconclusive, the app presents a manual fallback selector. Data is normalized and bifurcated by instrument tag. No Excel or CSV is stored.
