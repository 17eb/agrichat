# Provenance

Where each data file in `data/` came from, when it was accessed and under which terms.
This file is generated from `data/provenance.csv`.
Edit the CSV, then run `python -m scripts.build_provenance`.
Where a source states no terms, the entry says so and the terms are marked as not verified.

## nasa_power_daily

### `data/power/power_daily_1981_2025.csv`

- Source: https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR%2CT2M%2CT2M_MAX%2CT2M_MIN%2CRH2M%2CWS2M%2CALLSKY_SFC_SW_DWN%2CGWETROOT%2CGWETTOP&community=AG&longitude=120.56&latitude=18.06&format=JSON&start=19810101&end=20251231
- Accessed (UTC): 2026-11-14T23:29:34Z
- Terms: Not stated on the POWER daily API docs page (power.larc.nasa.gov/docs/services/api/temporal/daily/); terms not verified
- Script: scripts/fetch_power.py
- Notes: Batac LAT 18.06 LON 120.56 hand-set pilot point; community=AG; time_standard LST (default); allsky_sw_mj_m2 empty 1981-1983 (source has no data); /api/ is Disallow in robots.txt, documented API used once per request

### `data/power/power_daily_2026.csv`

- Source: https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR%2CT2M%2CT2M_MAX%2CT2M_MIN%2CRH2M%2CWS2M%2CALLSKY_SFC_SW_DWN%2CGWETROOT%2CGWETTOP&community=AG&longitude=120.56&latitude=18.06&format=JSON&start=20260101&end=20261113
- Accessed (UTC): 2026-11-14T23:29:38Z
- Terms: Not stated on the POWER daily API docs page (power.larc.nasa.gov/docs/services/api/temporal/daily/); terms not verified
- Script: scripts/fetch_power.py
- Notes: 2026-01-01 to 2026-11-13; latest days empty or provisional; same point and settings as history file

### `data/power/power_metadata.csv`

- Source: https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR%2CT2M%2CT2M_MAX%2CT2M_MIN%2CRH2M%2CWS2M%2CALLSKY_SFC_SW_DWN%2CGWETROOT%2CGWETTOP&community=AG&longitude=120.56&latitude=18.06&format=JSON&start=19810101&end=20261113
- Accessed (UTC): 2026-11-14T23:29:38Z
- Terms: Not stated on the POWER daily API docs page (power.larc.nasa.gov/docs/services/api/temporal/daily/); terms not verified
- Script: scripts/fetch_power.py
- Notes: built from both responses; source_model is the response header sources list (dataset-level, not per parameter); grid_lat/grid_lon are as returned in geometry.coordinates

## noaa_oni

### `data/oni/oni_seasonal.csv`

- Source: https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
- Accessed (UTC): 2026-11-14T23:34:10Z
- Terms: US Government (NOAA CPC) data; no use terms stated on the file; terms not verified
- Script: scripts/build_oni.py
- Notes: raw file data/oni/raw/oni.ascii.txt downloaded unchanged with curl; ONI on ERSSTv6 (matches v6 reference table); latest season ASO 2026 provisional; episode flags by CPC 5-season rule

### `data/oni/enso_dry_seasons.csv`

- Source: https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
- Accessed (UTC): 2026-11-14T23:34:10Z
- Terms: US Government (NOAA CPC) data; no use terms stated on the file; terms not verified
- Script: scripts/build_oni.py
- Notes: derived from oni_seasonal.csv; dry seasons 1981-2025; rule in data/oni/README_rule.txt; reference page data/oni/raw/oni_v6_reference.html from https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/oni/v6/ accessed 2026-11-14T23:35:17Z

### `data/oni/README_rule.txt`

- Source: https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
- Accessed (UTC): 2026-11-14T23:34:10Z
- Terms: Project-written text; source terms as for the other noaa_oni rows
- Script: scripts/build_oni.py
- Notes: labeling rule and meaning of YR; handoff reference URL origin.cpc.ncep.noaa.gov did not resolve and its ONI_v5.php page says it moved to the v6 page

## fao56_crops

### `data/crops/fao56_kc.csv`

- Source: https://www.fao.org/4/x0490e/x0490e0b.htm
- Accessed (UTC): 2026-11-14T23:57:42Z
- Terms: FAO publication: copyright statement on the FAO-56 front page (x0490e00.htm) requires prior permission of the copyright owner for reproduction; only table rows and formulas extracted, no chapters copied; terms not otherwise verified
- Script: scripts/build_crops.py
- Notes: Table 12 rows for 5 crops; footnote markers read from <SUP> tags; Kc ini taken from the group header row where the crop row is blank (kc_ini_from_group=1); max height split to _min/_max

### `data/crops/fao56_stage_lengths.csv`

- Source: https://www.fao.org/4/x0490e/x0490e0b.htm
- Accessed (UTC): 2026-11-14T23:57:42Z
- Terms: FAO publication: copyright statement on the FAO-56 front page (x0490e00.htm) requires prior permission of the copyright owner for reproduction; only table rows and formulas extracted, no chapters copied; terms not otherwise verified
- Script: scripts/build_crops.py
- Notes: all Table 11 rows for the 5 crops; one suggested row per crop (reason in file); notes column added; source sums differ from total for green gram and one soybean row has Ldev '30/35'

### `data/crops/fao56_root_depletion.csv`

- Source: https://www.fao.org/4/x0490e/x0490e0e.htm
- Accessed (UTC): 2026-11-14T23:57:50Z
- Terms: FAO publication: copyright statement on the FAO-56 front page (x0490e00.htm) requires prior permission of the copyright owner for reproduction; only table rows and formulas extracted, no chapters copied; terms not otherwise verified
- Script: scripts/build_crops.py
- Notes: Table 22 rows for the 5 crops; root depth split to _min/_max

### `data/crops/fao56_soil_water.csv`

- Source: https://www.fao.org/4/x0490e/x0490e0c.htm
- Accessed (UTC): 2026-11-14T23:58:39Z
- Terms: FAO publication: copyright statement on the FAO-56 front page (x0490e00.htm) requires prior permission of the copyright owner for reproduction; only table rows and formulas extracted, no chapters copied; terms not otherwise verified
- Script: scripts/build_crops.py
- Notes: all 9 Table 19 rows (found in Chapter 7, not Chapter 8); extra REW and TEW columns kept; silty clay field capacity prints '0-30 - 0.42' in source, read as 0.30 and noted

### `data/crops/da_durations.csv`

- Source: https://hvcdp.da.gov.ph/wp-content/uploads/2022/05/Mungbean-Production-Guide.pdf ; https://hvcdp.da.gov.ph/wp-content/uploads/2022/05/Giya-sa-Pagpananum-ug-Soybeans.pdf ; https://www.pinoyrice.com/wp-content/uploads/modified-dry-direct-seeding-technology.pdf ; https://www.pinoyrice.com/wp-content/uploads/el-nino-la-nina-at-pagpapalay.pdf
- Accessed (UTC): 2026-11-14T23:46:52Z
- Terms: Government/PhilRice extension material; no use terms stated in the PDFs; terms not verified
- Script: scripts/build_crops.py
- Notes: from DA/PhilRice PDFs downloaded by handoff 06 (copies in data/crops/raw/da/); doc_id is the handoff 06 working id (data/kb/raw/chunks_work.json) and may change when kb_sources.csv is finalised; no corn or peanut duration found; accessed_utc is the PDF file modification time

### `data/crops/method_constants.csv`

- Source: https://www.fao.org/4/x0490e/x0490e07.htm ; https://www.fao.org/4/s2022e/s2022e03.htm ; https://www.fao.org/4/s2022e/s2022e04.htm
- Accessed (UTC): 2026-11-15T00:00:15Z
- Terms: FAO publication: copyright statement on the FAO-56 front page (x0490e00.htm) requires prior permission of the copyright owner for reproduction; only table rows and formulas extracted, no chapters copied; terms not otherwise verified
- Script: scripts/build_crops.py
- Notes: Hargreaves Eq 52 and Ra Eq 20/21 from FAO-56 Chapter 3; effective rainfall rule not stated by source, Table 6 only; notes column added

### `data/crops/verification_vs_spec.csv`

- Source: https://www.fao.org/4/x0490e/x0490e0b.htm ; https://www.fao.org/4/x0490e/x0490e07.htm ; https://www.fao.org/4/s2022e/s2022e03.htm
- Accessed (UTC): 2026-11-14T23:58:14Z
- Terms: FAO publication: copyright statement on the FAO-56 front page (x0490e00.htm) requires prior permission of the copyright owner for reproduction; only table rows and formulas extracted, no chapters copied; terms not otherwise verified
- Script: scripts/build_crops.py
- Notes: 12 Kc draft values plus 2 formulas compared with saved pages

### `data/crops/crops_engine.csv`

- Source: https://www.fao.org/4/x0490e/x0490e0b.htm ; https://www.fao.org/4/x0490e/x0490e0e.htm
- Accessed (UTC): 2026-11-14T23:57:42Z
- Terms: FAO publication: copyright statement on the FAO-56 front page (x0490e00.htm) requires prior permission of the copyright owner for reproduction; only table rows and formulas extracted, no chapters copied; terms not otherwise verified
- Script: scripts/build_crops.py
- Notes: kc_end is midpoint of Table 12 range; days from DA range midpoint when found (rice, mungbean, soybean) else Table 11 suggested row (corn, peanut); income_flag left empty for the reviewer

## da_kb

### `data/kb/kb_candidates.csv`

- Source: https://www.pinoyrice.com/ ; https://hvcdp.da.gov.ph/production-manuals/ ; https://www.bswm.da.gov.ph/lists/
- Accessed (UTC): 2026-11-15T00:10:04Z
- Terms: none stated on PinoyRice, HVCDP or BSWM; only short passages with source and link are stored; raw downloads are not for the public repo
- Script: scripts/kb_http.py; scripts/kb_extract.py; scripts/kb_chunk.py; scripts/kb_build.py
- Notes: 191 rows; links read from the source and listing pages (two links deep); 4 corn candidates found by web search are logged unselected and were not downloaded

### `data/kb/kb_sources.csv`

- Source: https://www.pinoyrice.com/ ; https://hvcdp.da.gov.ph/production-manuals/ ; https://www.bswm.da.gov.ph/lists/
- Accessed (UTC): 2026-11-15T00:10:04Z
- Terms: none stated on PinoyRice, HVCDP or BSWM; only short passages with source and link are stored; raw downloads are not for the public repo
- Script: scripts/kb_http.py; scripts/kb_extract.py; scripts/kb_chunk.py; scripts/kb_build.py
- Notes: 19 selected documents; sha256 of each raw download; title/publisher/year as printed, empty when not printed or not extractable

### `data/kb/kb_chunks.csv`

- Source: https://www.pinoyrice.com/ ; https://hvcdp.da.gov.ph/production-manuals/ ; https://www.bswm.da.gov.ph/lists/
- Accessed (UTC): 2026-11-15T00:10:04Z
- Terms: none stated on PinoyRice, HVCDP or BSWM; only short passages with source and link are stored; raw downloads are not for the public repo
- Script: scripts/kb_http.py; scripts/kb_extract.py; scripts/kb_chunk.py; scripts/kb_build.py
- Notes: 243 chunks (heading-based, source wording, hand-rewritten table sentences flagged from_table=1); restricted chunks kept for audit only

### `data/kb/kb_durations.csv`

- Source: https://www.pinoyrice.com/ ; https://hvcdp.da.gov.ph/production-manuals/ ; https://www.bswm.da.gov.ph/lists/
- Accessed (UTC): 2026-11-15T00:10:04Z
- Terms: none stated on PinoyRice, HVCDP or BSWM; only short passages with source and link are stored; raw downloads are not for the public repo
- Script: scripts/kb_http.py; scripts/kb_extract.py; scripts/kb_chunk.py; scripts/kb_build.py
- Notes: 41 rows hand-transcribed from variety tables; every range cross-checked against the page text or OCR text; D10/D11 tables are scanned pages

### `data/kb/kb_audit_sample.csv`

- Source: https://www.pinoyrice.com/ ; https://hvcdp.da.gov.ph/production-manuals/ ; https://www.bswm.da.gov.ph/lists/
- Accessed (UTC): 2026-11-15T00:10:04Z
- Terms: none stated on PinoyRice, HVCDP or BSWM; only short passages with source and link are stored; raw downloads are not for the public repo
- Script: scripts/kb_http.py; scripts/kb_extract.py; scripts/kb_chunk.py; scripts/kb_build.py
- Notes: 40 random unrestricted chunks (seed 2026), clean_or_dirty left empty for a teammate

## batac_barangays

### `data/barangays/barangays.csv`

- Source: https://www.batac.gov.ph/barangays/
- Accessed (UTC): 2026-11-15T07:29:15Z
- Terms: Public municipal directory; terms not verified
- Notes: Hand-transcribed eight aliases; saved extract data/barangays/source.txt; pilot coordinates from technical spec and POWER provenance; pipe-separated aliases; empty soil_class
