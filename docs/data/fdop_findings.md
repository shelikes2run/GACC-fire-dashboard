# FDOP review — findings by forest (running log)

What was loaded from each forest's current FDOP into the FDOP Workbench / season tracking / map popup,
and anything that needs the forest's attention. Values are class upper breakpoints.

## San Bernardino NF (BDF) — 2023 FDOP Vol. 1
- Loaded: FDRAs 660/673/694 BI-X staffing/dispatch; 670/692 BI-Y; preparedness ERC-Y (all five); large fire 30 ac.
- FDOP Table 18 / 26e put 670 and 692 on **BI-Y** (660, 673, 694 on BI-X). Forest staff say X is the accurate model — the 670/692 tables need X-scale values if they have switched.
- 670: BI-Y 47 and 55 are never reached at the 3 FDOP stations (2016–2025) — SL4/SL5 cannot occur on Y.
- Adjective tables are images in the FDOP (not loaded).

## Sierra South (STF, SNF, SQF) — Interagency FDOP signed 2023-03-20 (v. 2023-05-05)
- Loaded: STF-348/370, SNF-528/532/533, SQF-435/438/440/445 (manager + FFP bins, tools).
- STF-348: manager ERC-Y 67/75 sit at the 99th/100th percentile — top classes almost never occur.
- SNF-532: FDOP SIG is weighted 30/30/10/30; the Workbench averages stations equally.
- SNF-528: climatology May 1–Nov 30, but Table A6.1 lists Jun 15–Oct 1 for thresholds.
- SQF-445: 90th/97th averaged across stations.
- SQF-435: an outside-NF piece's Y station had been averaged into the X data — fixed (separate unit).
- SQF-435 (Sequoia/Kings Canyon): fuel model is mixed in the FDOP — Table 3 lists pocket card and adjective on ERC FM-Y, dispatch on ERC FM-X and staffing on BI FM-X, while Appendix 9 (Table A9.1) bases the decision thresholds on ERC FM-Y (stations' 90th/97th 61/66 and 69/72). The 2026 sheet / our season tracking default to X; the Workbench starts on ERC-Y 20/35 (and BI 25/45). Needs one answer from the forest/park.
- Sequoia's current FDOP is still this 2023 Sierra South plan (the SQF file provided is the identical PDF). Inyo has since issued its own April 2026 FDOP; STF/SNF/SQF have not.

## Angeles NF (ANF) — FDOP Vol. 3 (2022-07-29)
- Loaded: FDRA-average BI-X and ERC-X breakpoints (Tables 2–4) for Front Country, High Country, Saugus.
- Five values per station in the FDOP; first four used as class tops, fifth kept as "top".

## Eldorado NF (ENF) — FDOP 2026
- Loaded: one year-round FDRA 335 (replaces peak/non-peak); SIG Beaver, Bald Mtn, Hellhole, Owens Camp, Steely Fork (Y).
- Staffing ERC-Y 15/31/50/60; dispatch BI-Y 10/20/29 (Smoke Check/Low/Medium/High); large fire 5 ac; MFD 2+.
- FDOP SIG 90th/97th ERC-Y 57/61, BI-Y 30/32 — ours 57.6/62.5 and 30.3/33.0 (agree).
- Includes the 2025 R5 PAL matrix (ERC 32/40/43/48/51, IC 17/27/36/41/49) — Workbench PAL check updated.
- Robbs and Granite Springs RAWS planned for a future high-elevation FDRA.

## Cleveland NF (CNF) — San Diego Interagency FEMS Transition Amendment (signed Sept–Oct 2025) to the Jan 2022 FDOP
- Loaded: Inland and Mountain BI-X staffing/adjective (52/105/211/239; 46/94/188/212), dispatch (119/188; 111/167), seasonal ERC-X (61+; 65+); 2013–2022, calendar year, large fire 1 ac.
- Amendment 90th/97th (Inland 211/239, Mountain 188/212) agree with ours (207/235, 185/211).
- The 2022 FDOP PDF is scanned (no text) — station SIGs taken from the 2026 thresholds sheet; need confirmation.
- CNF-Inland / CNF-Mountain had no station rows in the membership file — fixed.
- 2024 interagency FDRA shapefile (Coastal and Mountain) available; map still uses the sheet boundaries.
- Full FDOP rewrite planned for 2026 (Coastal/Desert FDRAs, Mountain North, other fuel models).

## Inyo NF (INF) — FDOP April 2026
- Loaded: 460 Mono BI-Y 14/25/33/37; 461 Owens BI-Y 31/37/48/53; 443 Plateau ERC-Y 25/35/49/54 (FFP bins, not manager-modified); 2005–2025 Jan–Dec.
- Values unchanged from the Sierra South FDOP; SIGs and sources updated.
- **FDRA 460 had RAWS 44709 instead of Crestview 043709** — fixed (membership, polygon, hosted layer).
- Large-fire and multi-fire-day definitions only in FFP graphics — not loaded (defaults used).
- Confirms the Aug 2025 R5 PAL table.

## Klamath NF (KNF) — FDOP 2026 (PDF portfolio)
- Loaded: KNF West (200/202/204/208) and KNF East (214/220) dispatch-area thresholds — staffing BI-Y 12/17/22/27 and 15/21/26/30; response BI-Y 28/35 and 16/25; adjective ERC-Y 22/34/42/52 and 20/33/40/48; 2016–2025, May–Nov; large fire 50 ac (West) / 10 ac (East); MFD 2.
- Per-FDRA SIGs (Tables 5–8) match our membership; Workbench starts from the dispatch-area SIG.
- **FDRA 210 (CAL FIRE DPA) had the nearest RAWS (40247); FDOP SIG is Weed Airport 40228 + Brazie Ranch 40242** — fixed.
- Appendix K header for KNF East lists 40237/40239; names and Table 9 say Juanita 40240 / Van Bremmer 40243 (used).

## Lassen NF / Lassen Volcanic NP (LNF) — Interagency FDOP v2 (signed 2024-07-03)
- Loaded: one FDRA, 5-station SIG (Bogard, Chester, Gordon, Ladder Butte, Manzanita Lake), Y. Staffing BI-Y 9/16/22/31; adjective/dispatch BI-Y 9/16/24/31; ERC-Y 16/30/42/57; IC-Y 12/21/31/44; 2010–2023, May–Oct, large fire 30 ac.
- **Membership had Blacks Mountain 40731 instead of Gordon 40730** — fixed.
- BI → dispatch level differs between Table 11 (10–16 = DL2) and Table 14 (10–16 = DL1).
- Live popup cannot show IC level (live RAWS layer has no IC); season tracking does.

## Modoc NF / MIFA (MDF) — FDOP April 2026 DRAFT
- Loaded: MDF-258, SIG 8 RAWS; staffing BI-Z 20/41/83/93; dispatch BI 47/81 ("proposed change, under review"); large fire 100 ac; MFD 5; 2016–2025; Jun–Sep.
- **Lower Klamath 40310 missing from our SIG** — added.
- Fuel model conflict: staffing text says BI fuel model Z, FFP table lists Y — breakpoints only fit Z (BI-Z 90th/97th 89/101 vs BI-Y 97th ~39).
- Table 2 lists Blue Mountain twice; adjective matrix IC columns skip 21–30; response-plan note says "ERC Y" while thresholds are BI.

## Mendocino NF (MNF) — 2026 FDOP Vols. 1–4 (Vol. 1 final draft .docx; Vol. 2 Apr 2026; Vol. 3 Jun 2026; Vol. 4 RAWS analysis Apr 2023)
- Loaded: 162 West (BI-Z / ERC-Z), 165 High Country (BI-Z / ERC-Z), 170 East (BI-Y / ERC-Y) — staffing 39/59/71/91, 37/56/69/91, 22/28/34/43; dispatch Low/High at 72+, 70+, 35+; adjective ERC 57/74/91/110, 61/84/101/109, 28/39/51/61 (FDOP lists class starts; converted to class tops).
- **Our membership did not match the FDOP SIGs (Tables 9–11) and had the fuel models reversed** — fixed in membership, polygons and hosted layer:
  - 162 West: Eel River 41005 + Soda Creek 41406, fuel model Z (we had 4 stations, Y).
  - 165 High Country: Alder Springs 41101 + Mendocino Pass 41018, Z (we had a typo station "411018", Y).
  - 170 East: Eagle Peak 40802, High Glade Lookout 41402, Stonyford 41503, Y (we had 40816 added, Z).
- 165 dispatch: Table 14/17 high at BI 70+ (Grindstone, Table 15), but Table 15 also lists 165 at 72+ under Upperlake/Covelo.
- Analysis years, season and large-fire size are not stated in the text (in FFP graphics) — Workbench defaults used.
- Severity triggers in Vol. 2 still reference ERC fuel model G (1978) for PSAs NC02/NC05 in places, alongside fuel model Y elsewhere.

## Plumas NF + Tahoe NF (PNF/TNF) — Plumas-Tahoe Zone Interagency FDOP, signed 2026-06-09
- New structure: three zone FDRAs (North, East, West) whose SIGs cross the two forests; fuel model Y; staffing from 2005–2022 FEMS gap-filled data, May 1–Oct 31; dispatch from 2005–2022 weather with 2014–2023 fire history.
  - North (Quincy, Pierce, Cashman): staffing BI-Y 18/25/30/38; dispatch 18/25.
  - East (Laufman, Denten Creek, Coyote, Stampede, Rice Canyon): staffing 14/22/28/34; dispatch 19/29.
  - West (Saddleback, Pike County LO, White Cloud, Duncan, Seed Orchard): staffing 11/23/32/38; dispatch 19/29.
- **New zone boundaries are only a map image in the FDOP** — our six older polygons (PNF West/Central/East, TNF 350/354/380) are mapped to the zones by station (Central→North; PNF-East, TNF-380→East; PNF-West, TNF-350, TNF-354→West) and given the zone SIG and thresholds. Need the zone FDRA shapefile to replace them.
- East/West dispatch: main section and summary boxes say 0-19 / 20-29 / 30+; the appendix analysis text derives 0-24.9 / 25-31.9 / 32+. Both loaded; forest should confirm.
- East SIG: Table 3 and staffing table use Coyote (40917); the East dispatch analysis lists Dog Valley (41302) instead.
- West fire summary: "Lightning caused (3215)" of 940 fires — typo; and the period is given as both 2005–2022 and 2014–2023.
- Adjective rating is an ERC-Y × BI-Y matrix (I–V) per zone — not charted as a single tool (axes in the notes).
- Large-fire size not stated in the text.
- Old 2026-sheet TNF value (BI 22/30, "index assumed") retired.

## Shasta-Trinity NF (SHF) — 2026 FDOP, FINAL signed (May 2026)
- Loaded: FDRAs 230, 238, 240, 241, 243 — staffing BI-Y (SL4 = 90th, SL5 = 97th; SL2/SL3 at ¼ and ½ the 90th): 7.43/14.85/29.7/32.9, 7.08/14.15/28.3/30.9, 7.6/15.2/30.4/33.4, 8.8/17.6/35.2/38.2, 7.28/14.55/29.1/32.0; dispatch BI-Y 20/26, 22/31, 19/26, 22/31, 20/27.
- SIGs match our membership exactly (no station fixes needed).
- Percentiles from gap-filled FEMS 2005–2022, Jan–Dec; dispatch from 2011–2025 fire occurrence (5+ ac large fire days, 2+ multi-fire days); FFP large fire 10 ac.
- FDRA staffing is tracked, but the Forest-level staffing (all RAWS, 7.43/14.85/29.7/31.7) sets actual staffing — Forest-level SIG not mapped as its own FDRA.
- Typos: FFP parameter table header "FDRA 2380" (= 230); FDRA 243 Ash Creek data years blank and its 90th (25/27) below the 1–12 value pattern of the other stations.
- Pocket-card large fire changed from 5 to 10 acres.

## Six Rivers NF / Redwood NP (SRF/RWP) — 2026 FDOP, DRAFT for signature V2 (Jun 2026)
- Loaded (FDOP name → our FDRA): SRNRA → SRF-110, ORD-HIA-LTRD → SRF-112-115, MR → SRF-130, Ukonom → SRF-201, RWP → SRF-RWP; SIGs match our membership.
  - Staffing BI-Y: 6/14/30/33, 6/14/29/32, 5/11/23/25, 7/15/31/33; RWP staffing ERC-Y 14/24/35/40 (2015–2025).
  - Dispatch BI-Y: 14/22, 11/21, 12/19, 15/24 (from 2005–2022 fire history); RWP has no dispatch levels.
- Still a draft (not signed). FDRA names in the FDOP (SRNRA, ORD-HIA-LTRD, MR, Ukonom, RWP) differ from the 2026 sheet numbers (110, 112-115, 130, 201).
- Dataset years: text says 2005–2022 gap-filled; the staffing table says 2005–2025.
- RWP: only 3 large-fire days (5 ac+) in 2015–2024 — FDOP notes the sample is too small for statistical inference.
- Old 2026-sheet SRF values (BI 90th/97th 31.1/34.7 etc.) retired.

## Cross-forest
- 2025 R5 PAL matrix now in the Workbench PAL check.
- Breakpoint convention made consistent: a breakpoint is the top of its class everywhere (popup, tracking, Workbench).
