ENSO labels for Philippine dry seasons (AgriChat, handoff 02)

Accessed: 2026-11-14 (UTC 23:34 for the data file, 23:35 for the reference page)
Source file: https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt (NOAA Climate Prediction Center)
Reference table: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/oni/v6/
Latest season in the file: ASO 2026. Seasons from the last 12 months are provisional and may change.

Which ONI this is
The file matches the CPC ONI table based on ERSST version 6 (all 921 values agree with the v6 table to one decimal).
It does not match the older ERSST v5 table, and it is not the Relative ONI (RONI) that CPC now uses for official monitoring (NWS Public Information Statement 26-05).
Columns: SEAS (season), YR, TOTAL (Nino 3.4 SST, degrees C), ANOM (the ONI, degrees C).

Meaning of YR
YR is the calendar year of the CENTER month of the three-month season.
DJF 1998 is Dec 1997 to Feb 1998, centered on Jan 1998.
NDJ 1997 is Nov 1997 to Jan 1998, centered on Dec 1997.
So center_month runs DJF=1 up to NDJ=12 and center_date is YR-center_month-01.
Check: peak of the 1997-98 event is NDJ 1997 = 2.37 and of the 2015-16 event is NDJ 2015 = 2.59, matching the reference table (2.4 and 2.6).

Episode flags (oni_seasonal.csv)
An El Nino episode is 5 or more consecutive overlapping seasons with ONI at or above +0.5.
A La Nina episode is 5 or more consecutive overlapping seasons with ONI at or below -0.5.
Every season inside such a run gets the flag.
Thresholds are applied to the two-decimal values in the file.
The +/-0.5 threshold and the 5-season rule are fixed.

Dry-season labeling rule (enso_dry_seasons.csv), default, fixed before the hindcast
Dry season Y runs from November Y to April Y+1 and is labeled by its start year.
djf_oni is the ONI of the DJF season centered on January Y+1.
phase is el_nino if that DJF season is inside an El Nino episode, la_nina if it is inside a La Nina episode, otherwise neutral.
el_nino is 1 when phase is el_nino, otherwise 0.
peak_oni is the value with the largest absolute size among OND (year Y), NDJ (year Y), DJF, JFM and FMA (year Y+1), sign kept.
strength is empty for neutral.
For el_nino and la_nina it comes from the absolute value of peak_oni: weak below 1.0 (from 0.5), moderate 1.0 up to below 1.5, strong 1.5 up to below 2.0, very_strong 2.0 or more.
The bands are applied continuously to the two-decimal values, so a peak of 1.99 is strong.
provisional is 1 if any season used (OND Y through FMA Y+1) is centered within 12 months of the latest season in the file, that is after 2025-09-01.
Rows run from 1981 to 2025, the latest dry season with all of its seasons in the file.
The dry season starting November 2026 is not in the table because DJF 2027 does not exist yet.
Do not change this rule after looking at hindcast results.
