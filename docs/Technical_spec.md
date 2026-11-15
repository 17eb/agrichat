# AgriChat - Technical spec

Nov 15, 2026

This is the build document for developers.
The problem, findings, validation plan, open decisions and sources are in `Project_overview.md`.
The short data handoff is `README.md`.

## Architecture

A text is acknowledged at once, handled by a background worker, and answered from precomputed tables; NASA data is fetched and processed before the demo, not per message.

&#91;embedded content: AgriChat architecture · message path, worker services, offline builds\]

The rotation engine is the core: it ranks crops from the indicator tables, and the language model only reads the incoming text and words the reply.

AgriChat is deployed as one website.
The same server process answers SMS webhooks, serves the public pages and serves the admin panel.
Farmers still use SMS; the website is how judges, technicians and the team reach the service.

| Surface | Who uses it | What it does |
| --- | --- | --- |
| SMS | Farmers on keypad phones | `REG`, `LAST`, `PLANT`, `WHY` through the gateway phone |
| Public website | Judges and the public, no login | Explains the service, runs the SMS simulator, shows the hindcast chart, data sources and limits |
| Admin panel | The team and municipal technicians, login required | Shows registered profiles, message log, indicators, knowledge base and system health |

### Tech stack

| Layer | Choice | Reason |
| --- | --- | --- |
| Language | Python 3.13 | Already used by the data scripts |
| Web framework | FastAPI on Uvicorn, one process | Background tasks keep running after the 200 response; one app serves API, website and admin |
| Web pages | Server-rendered Jinja2 templates, plain CSS, a small vanilla JavaScript file for the simulator | No frontend build step and no second deployment |
| Chart | Chart.js, loaded from a pinned CDN version | One chart; no chart backend |
| Database | SQLite through the standard `sqlite3` module, one file, WAL mode | Enough for one municipality; no setup time |
| Engine and pipeline | Plain Python (`csv`, `math`, `statistics`), no model call | Deterministic and testable; 16,753 daily rows need no dataframe library |
| Data collection | `requests`, `pymupdf`, `trafilatura` | Already used by `scripts/` |
| Retrieval | `sentence-transformers` with a multilingual model, vectors in `numpy`, cosine search | Chunks are in English, Filipino and Cebuano; 181 usable chunks need no vector database |
| Language model | Small Azure OpenAI chat model through the `openai` SDK, name set in config | The planned gpt-4o-mini version is listed as retired; pick what deploys today |
| SMS gateway | httpSMS on a dedicated Android phone with a prepaid SIM | No telco approval needed; webhooks for received messages |
| Admin login | One shared password, stored as an Argon2 hash, with a signed session cookie | One team; no user table to build |
| Hosting | One VPS, Caddy as reverse proxy, the app as a systemd service | Automatic HTTPS and restart on failure |
| Tests | `pytest`, with FastAPI's test client | Covers parser, engine, templates and routes |

The embedding model and the Chart.js version are proposals; record the exact names and versions in `AI_USE.md` and the citations list once installed.

### Requirements

- The webhook returns 200 within 1 second.
- A reply is sent within about 30 seconds of the incoming text.
- With the model disabled, every keyword command still works.
- No NASA or other external data call is made while handling a message, except the model call.
- Every public page opens without a login and works on a phone screen.
- Every admin page and admin action requires a valid session.
- The whole site is served over HTTPS only.

## SMS interface

A keyword parser handles every command without the language model.
The model is called only when the parser fails.

### Commands

| Command | Filipino alias | What it does |
| --- | --- | --- |
| `REG` + barangay + water source | `REHISTRO` | Creates or updates the farmer profile. Water source is `ULAN` (rainfed), `PATUBIG` (canal) or `BOMBA` (pump). |
| `LAST` + crop | `HULI` | Stores the last crop, for example `LAST PALAY`. |
| `PRIO` + `TUBIG` or `KITA` | `UNA` | Stores the priority: save water or steady income. |
| `PLANT` | `TANIM` | Returns the top recommendation with one number. |
| `WHY` | `BAKIT` | Returns the reason and sources for the last recommendation. |
| `HELP` | `TULONG` | Lists the commands. |
| `STOP` | `HINTO` | Deletes the profile and message history. |

### Parsing order

1. Normalize: trim, uppercase, collapse spaces, strip punctuation.
2. Match the first word against commands and aliases.
3. No match: send the text to the model for intent extraction (see the LLM section).
4. Still no intent, or low confidence: reply with the fallback template.

### Reply rules

- 150 characters or fewer, one message per reply.
- GSM 7-bit characters only.
  Replace the peso sign with `P`.
  Strip curly quotes, long dashes, emoji and markdown symbols.
- Filipino by default, plain words.
- One recommendation, one number, one next command.
- Every reply is built from a template ID and reason codes, so it can be traced and tested.
- A `validate_sms(text)` function checks length and character set before every send.
  A failed check sends the plain template instead.

### Templates

| ID | Text |
| --- | --- |
| `T_REG_OK` | Rehistrado ka sa Brgy {brgy}, {tubig}. I-text ang LAST at huling tanim mo. Hal: LAST PALAY |
| `T_LAST_OK` | Naitala: {crop} ang huling tanim. I-text ang PLANT para sa payo sa susunod na tanim. |
| `T_PLANT` | Payo: {crop1}. Sapat ang tubig sa {a} sa {n} nakaraang tag-araw dito; {crop2}, {b} sa {n}. I-text ang WHY para sa dahilan. |
| `T_PLANT_BORDER` | Alanganin: halos pantay ang {crop1} at {crop2} sa tubig dito. Kumonsulta sa agri office ng munisipyo bago magtanim. |
| `T_WHY` | Dahilan: {reason1}; {reason2}. Batayan: {sources}. Di sakop: presyo, peste. |
| `T_NO_DATA` | Wala pa kaming datos para sa Brgy {brgy}. Kumonsulta muna sa agri office ng munisipyo. |
| `T_REFER` | Hindi namin masasagot iyan. Para sa pataba, gamot o peste, kumonsulta sa agri office ng munisipyo. |
| `T_HELP` | AgriChat: REG brgy ULAN, LAST PALAY, PLANT, WHY, STOP. Hal: REG SAN JOSE ULAN |
| `T_FALLBACK` | Di ko naintindihan. I-text ang HELP para sa listahan ng utos. |

Check each filled template against the 150-character limit with the longest barangay and crop names.

### Guards

- **Deduplicate** on the gateway message ID, since webhooks can be delivered twice.
- **Ignore non-mobile senders** such as short codes and alphanumeric names.
  Replying to telco promos creates loops and burns load.
- **Rate-limit** each number, for example 10 messages per hour.
- **Session memory** is the last 3 messages per number, used only so `WHY` can refer to the last `PLANT`.

## Datasets

Four datasets are collected, cleaned and checked.
A fifth, SMAP Level 4 root-zone soil moisture, is in the build and still to fetch (handoff 07).
All paths are relative to the repository root.

**Pilot point:** Batac, Ilocos Norte, rainfed.
LAT 18.06, LON 120.56, hand-set.
Every barangay in Batac shares one NASA POWER grid cell, so `barangay_code` is `BATAC` everywhere.

### Shared conventions

- Raw downloads stay unchanged in `data/<name>/raw/`.
  Cleaned CSVs are in `data/<name>/`.
- CSVs are UTF-8, comma-separated, one header row, `snake_case` columns, dates as `YYYY-MM-DD`.
- An empty cell means missing.
  There is no `-999`, `NaN` or `N/A` anywhere.
- No value was typed from memory; every value comes from a saved source page or file.
- `data/provenance.csv` has one row per output file: `dataset, file, source_url, accessed_utc, license_or_terms, script, notes`.
  Copy it into `PROVENANCE.md` for the public repo.

### Inventory

| Dataset | File | Rows | Built by | Use it for |
| --- | --- | --- | --- | --- |
| NASA POWER | `data/power/power_daily_1981_2025.csv` | 16,436 | `scripts/fetch_power.py` | Water budget and risk indicators |
| NASA POWER | `data/power/power_daily_2026.csv` | 317 | `scripts/fetch_power.py` | "Conditions now", and the Jan to Apr 2026 end of the 2025 dry season |
| NASA SMAP L4 | `data/smap/smap_l4_daily.csv` | to fetch | `scripts/fetch_smap.py` | `soilwet_pct`: root-zone soil moisture now against the same dates since 2015 |
| NASA SMAP L4 | `data/smap/smap_now.csv` | to fetch | `scripts/fetch_smap.py` | The latest SMAP day and its percentile |
| NASA SMAP L4 | `data/smap/smap_vs_power.csv` | to fetch | `scripts/fetch_smap.py` | Agreement with POWER `gwetroot`, 2015 to 2025, for the data page |
| NASA POWER | `data/power/power_metadata.csv` | 9 | `scripts/fetch_power.py` | Units, valid dates, grid elevation and request URLs per parameter |
| NOAA ONI | `data/oni/oni_seasonal.csv` | 921 | `scripts/build_oni.py` | Full ONI series with episode flags; not read by the engine |
| NOAA ONI | `data/oni/enso_dry_seasons.csv` | 45 | `scripts/build_oni.py` | El Niño flag per dry season |
| NOAA ONI | `data/oni/README_rule.txt` | - | `scripts/build_oni.py` | The fixed labeling rule |
| FAO-56 crops | `data/crops/crops_engine.csv` | 5 | `scripts/build_crops.py` | Kc values, days and legume flag per crop |
| FAO-56 crops | `data/crops/fao56_stage_lengths.csv` | 15 | `scripts/build_crops.py` | Stage lengths for the Kc curve (rows with `suggested` = 1) |
| FAO-56 crops | `data/crops/method_constants.csv` | 4 | `scripts/build_crops.py` | Hargreaves ET0, Ra formula, Ra unit factor, effective-rain table |
| FAO-56 crops | `data/crops/fao56_kc.csv` | 5 | `scripts/build_crops.py` | Table 12 rows as printed, with Kc end ranges and footnotes |
| FAO-56 crops | `data/crops/fao56_root_depletion.csv` | 5 | `scripts/build_crops.py` | Table 22 root depth and depletion fraction; reference for the reviewer |
| FAO-56 crops | `data/crops/fao56_soil_water.csv` | 9 | `scripts/build_crops.py` | Table 19 soil water by texture; reference for the water-capacity number |
| FAO-56 crops | `data/crops/da_durations.csv` | 12 | `scripts/build_crops.py` | DA and PhilRice days to maturity behind the `days` column |
| FAO-56 crops | `data/crops/verification_vs_spec.csv` | 14 | `scripts/build_crops.py` | Draft spec values compared with the source |
| DA knowledge base | `data/kb/kb_sources.csv` | 19 | `scripts/kb_build.py` | Source tags, links and file hashes for `WHY` and the citations list |
| DA knowledge base | `data/kb/kb_chunks.csv` | 243 | `scripts/kb_chunk.py`, `scripts/kb_build.py` | `WHY` retrieval; only rows with `restricted` = 0 |
| DA knowledge base | `data/kb/kb_durations.csv` | 41 | `scripts/kb_build.py` | Variety-level days to maturity, hand-transcribed |
| DA knowledge base | `data/kb/kb_candidates.csv` | 191 | `scripts/kb_build.py` | Every link considered, with `selected` and the reason |
| DA knowledge base | `data/kb/kb_audit_sample.csv` | 40 | `scripts/kb_build.py` | Random usable chunks for the teammate audit |

### NASA POWER daily

One point request per file to the daily API, `community=AG`, default local solar time.
The request URLs are in `power_metadata.csv`.

| Column | POWER parameter | Unit | Notes |
| --- | --- | --- | --- |
| `barangay_code` | - | - | Always `BATAC` |
| `date`, `year`, `month`, `day_of_year` | - | - | One row per day |
| `prectotcorr_mm` | `PRECTOTCORR` | mm/day | Bias-corrected precipitation |
| `t2m_max_c`, `t2m_min_c`, `t2m_mean_c` | `T2M_MAX`, `T2M_MIN`, `T2M` | °C | Inputs to Hargreaves ET0 and the heat indicator |
| `rh2m_pct` | `RH2M` | % | Not used by the engine |
| `ws2m_ms` | `WS2M` | m/s | Not used by the engine |
| `allsky_sw_mj_m2` | `ALLSKY_SFC_SW_DWN` | MJ/m²/day | Empty for 1981 to 1983 (1,095 rows) and the last 5 days of 2026; not used by the engine |
| `gwetroot` | `GWETROOT` | fraction 0 to 1 | Root-zone soil wetness; starting soil water in the hindcast, and `soilwet_pct` when SMAP is missing or stale |
| `gwettop` | `GWETTOP` | fraction 0 to 1 | Surface soil wetness; not used by the engine |

- The history file runs 1981-01-01 to 2025-12-31 with no gaps in any column the engine uses.
- The 2026 file runs 2026-01-01 to 2026-11-13.
  Its last two rows (12 and 13 Nov) are empty; the latest full row is 2026-11-11.
- The grid cell elevation is 263.86 m.
- The source model list in the response is `MERRA2|SRB|SYN1DEG|POWER`.
- Check: `python3 scripts/check_power.py`.
  Mean annual rain 1981 to 2025 is 2,024.5 mm; the driest dry season is 1994/1995 with 30.9 mm and the wettest is 2020/2021 with 1,662.2 mm.

### NASA SMAP Level 4 soil moisture

Status: in the build, not fetched yet.
The full fetch procedure is in `07/07_smap_l4.md`.

- **Product:** SMAP L4 Global 3-hourly 9 km EASE-Grid Surface and Root Zone Soil Moisture, `SPL4SMGP` Version 8.
  The record begins 31 March 2015.
- **Access:** one point task through the NASA AppEEARS API for LAT 18.06, LON 120.56, returning CSV.
  No HDF5 granules are downloaded.
- **Login:** a NASA Earthdata account, passed only to the fetch script through `EARTHDATA_USER` and `EARTHDATA_PASS`.
  The credentials are never written to a file, a log or the repo, and the deployed app does not need them.
- **Processing:** convert UTC to PHT, average the 3-hourly values to daily means, and rank each day's root-zone moisture against every other year within ±15 days of the same day of year.

`smap_l4_daily.csv` columns: `barangay_code, date, sm_rootzone_m3m3, sm_surface_m3m3, sm_rootzone_wetness, sm_rootzone_pctl_product, n_obs, soilwet_pct`.

`smap_now.csv` has one row: `barangay_code, latest_date, sm_rootzone_m3m3, soilwet_pct, years_in_baseline, days_since_latest`.

- **Role:** SMAP gives `soilwet_pct`, the "conditions now" soil-moisture indicator.
  It does not replace `gwetroot` as starting soil water in the hindcast, because SMAP starts in 2015 and the hindcast needs all 45 seasons from one source.
- **Fallback:** if `smap_now.csv` is missing or `days_since_latest` is more than 7, `soilwet_pct` comes from POWER `gwetroot`.
  The indicator row records which source was used.
  SMAP and POWER values are never blended.
- Check: `python3 scripts/check_smap.py`.
  Dates run from 2015-03-31 with gaps listed; soil moisture stays between 0 and 0.9 m³/m³ and wetness between 0 and 1; February to April is drier than July to September on average; the latest date is within about a week of the fetch.

### NOAA Oceanic Niño Index

The raw file is the NOAA CPC `oni.ascii.txt`, which matches the ERSST v6 reference table.
It is not the older v5 table and not the Relative ONI.

`enso_dry_seasons.csv` has one row per dry season, 1981 to 2025.

| Column | Meaning |
| --- | --- |
| `dry_season_start_year` | Year Y: the season runs November Y to April Y+1 |
| `djf_oni` | ONI of the Dec to Feb season centered on January Y+1 |
| `peak_oni` | Largest absolute value among the five seasons from Oct-Dec Y to Feb-Apr Y+1, sign kept |
| `phase` | `el_nino`, `la_nina` or `neutral`, from whether that Dec to Feb season is inside an episode |
| `strength` | `weak`, `moderate`, `strong` or `very_strong` from the size of `peak_oni`; empty for neutral |
| `el_nino` | 1 when `phase` is `el_nino` |
| `provisional` | 1 when a season used is within 12 months of the latest season in the file |

- An episode is 5 or more consecutive overlapping seasons at or beyond +0.5 or -0.5.
- 15 of the 45 dry seasons are El Niño: 1982, 1986, 1987, 1991, 1994, 1997, 2002, 2004, 2006, 2009, 2014, 2015, 2018, 2019 and 2023.
- The 2025 row is provisional.
- The dry season starting November 2026 is not in the table, because the Dec to Feb value does not exist yet.
  The latest season in `oni_seasonal.csv` is Aug to Oct 2026 at +2.46, inside an El Niño episode.
  Set the current-season flag by hand from that value and say so on the project page.
- The full rule is in `data/oni/README_rule.txt`.
  It is fixed; do not change it after seeing hindcast results.
- Check: `python3 scripts/check_oni.py`.
  All 921 values agree with the reference table to within 0.05.

### FAO-56 crop tables

`crops_engine.csv` is the table the engine reads.
Use rice, mungbean and soybean.
Ignore corn and peanut: no DA duration was found for either.

| Crop | `kc_ini` | `kc_mid` | `kc_end` | `days` | `is_legume` | Source of `days` |
| --- | --- | --- | --- | --- | --- | --- |
| rice | 1.05 | 1.20 | 0.75 | 108 | 0 | Midpoint of the DA range 102 to 114 |
| mungbean | 0.40 | 1.05 | 0.475 | 65 | 1 | Midpoint of the DA range 60 to 70 |
| soybean | 0.40 | 1.15 | 0.50 | 95 | 1 | Midpoint of the DA range 90 to 100 |
| corn (not used) | 0.30 | 1.20 | 0.475 | 125 | 0 | FAO-56 Table 11, no DA figure |
| peanut (not used) | 0.40 | 1.15 | 0.60 | 130 | 1 | FAO-56 Table 11, no DA figure |

- Kc values are from FAO-56 Table 12.
  Mungbean is the "Green Gram and Cowpeas" row.
- `kc_ini` for mungbean, soybean, corn and peanut is the group value on the Table 12 header row; the crop row is blank.
- `kc_end` is the midpoint of the Table 12 range: rice 0.6 to 0.9, mungbean 0.35 to 0.6.
  The reviewer chooses between the midpoint and the harvested-dry value.
- `income_flag` is empty for the reviewer to fill.
- All 12 draft Kc values and the Hargreaves equation match the source (`verification_vs_spec.csv`).

Stage lengths for the Kc curve come from the `suggested` = 1 rows of `fao56_stage_lengths.csv`.

| Crop | Initial | Development | Mid | Late | FAO total | DA `days` |
| --- | --- | --- | --- | --- | --- | --- |
| rice (Dec, Tropics) | 30 | 30 | 60 | 30 | 150 | 108 |
| mungbean (March, Mediterranean) | 20 | 30 | 30 | 20 | 100 (source prints 110) | 65 |
| soybean (Dec, Tropics) | 15 | 15 | 40 | 15 | 85 | 95 |

The FAO totals do not match the DA durations.
Scaling the four stage proportions to `days` is the proposed default; confirm it with the reviewer before the hindcast.
The mungbean row is a Mediterranean stand-in, the only one FAO gives.

`method_constants.csv` holds the formulas:

| Name | Content | Source |
| --- | --- | --- |
| `hargreaves_eto` | `ETo = 0.0023 * (Tmean + 17.8) * (Tmax - Tmin)^0.5 * Ra`, Ra in mm/day | FAO-56 Eq. 52, verified |
| `extraterrestrial_radiation_ra` | Ra from latitude and day of year, in MJ/m²/day, `Gsc = 0.0820` | FAO-56 Eq. 21, transcribed from the page image |
| `ra_to_mm_per_day` | Multiply Ra in MJ/m²/day by 0.408 | FAO-56 Eq. 20 |
| `effective_rainfall_monthly` | 26 pairs of monthly rain and effective rain, 0 to 250 mm | FAO Training Manual 3, Table 6; no formula in the source |

### DA knowledge base

19 documents were selected from 191 candidate links: 15 from PinoyRice, 2 from DA-HVCDP and 2 from BSWM.
`kb_sources.csv` columns: `doc_id, title, publisher, year, url, access_date, reuse_terms, source_tag, language, crop, topic, file_name, sha256, pages, ocr`.

`kb_chunks.csv` columns: `chunk_id, doc_id, source_tag, title, year, url, page, heading, crop, topic, language, text, char_count, from_table, restricted, restricted_reason, text_hash`.

| Crop tag | Chunks | Usable (`restricted` = 0) | Restricted |
| --- | --- | --- | --- |
| rice | 159 | 128 | 31 |
| general | 38 | 28 | 10 |
| mungbean | 29 | 13 | 16 |
| soybean | 17 | 12 | 5 |
| **Total** | **243** | **181** | **62** |

- Languages: 143 English, 83 Filipino, 17 Cebuano (the soybean guide).
- Topics: water 68, soil 48, drought 29, rotation 28, other 27, timing 22, harvest 15, duration 6.
- Chunks are split by heading and keep the source wording.
  Table sentences rewritten by hand are flagged `from_table` = 1.
- A chunk is restricted when it matches a pattern for chemical rates, fertilizer names or grades, pesticide terms, spray mixing or pest control.
  `restricted_reason` names the pattern.
- There are no corn chunks.
- Check: `python3 scripts/kb_check.py`.
  No restricted pattern appears in a usable chunk, and no phone number, email or URL appears in any chunk text.
  Mungbean and soybean are below the 15-chunk floor.
- Raw PDFs and pages are in `data/kb/raw/` and `data/crops/raw/da/`.
  Both are in `.gitignore` because the documents show no reuse statement.

### Not collected

| Skipped | Replacement in the build |
| --- | --- |
| Barangay reference (handoff 05) | Hand-type `data/barangays/barangays.csv`: one row for Batac (code `BATAC`, lat 18.06, lon 120.56) plus 5 to 10 barangay names as aliases so `REG` matches them |
| BSWM soil series (handoff 04) | No soil filter. Leave `soil_class` empty and skip the "soil unsuitable" rule. Root-zone water capacity is one assumed number from the reviewer |
| GPM IMERG, MODIS | None; listed as next steps |
| PSA crop statistics | None; the hindcast compares against El Niño seasons and the rainfall-only baseline |

List BSWM soil, IMERG and MODIS under "next steps" on the project page, not as data used.

## NASA data pipeline

The fetch is done.
The remaining scripts compute a water budget for every crop in every past dry season and write a small indicators table.
No NASA call happens when a text arrives.

### Step 1: fetch (POWER done, SMAP to do)

`scripts/fetch_smap.py` follows handoff 07: submit the AppEEARS point task first, because the queue can take hours, and build the POWER-based steps while it runs.

`scripts/fetch_power.py` made one point request for the history and one for the current year, and saved the raw JSON beside the cleaned CSVs.

```text
https://power.larc.nasa.gov/api/temporal/daily/point
  ?parameters=PRECTOTCORR,T2M,T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,GWETROOT,GWETTOP
  &community=AG&longitude=120.56&latitude=18.06
  &start=19810101&end=20251231&format=JSON
```

- The fill value -999 is already converted to an empty cell.
- The pipeline reads the CSVs, never the API.
- A dry season spans two calendar years.
  The 2025 season (Nov 2025 to Apr 2026) needs both files; the history file alone gives 44 complete seasons.

### Step 2: reference evapotranspiration

Use the Hargreaves method (FAO-56 Eq. 52), which needs only temperature and latitude.
Ra is extraterrestrial radiation, computed from latitude and day of year with FAO-56 Eq. 21 in MJ/m²/day and multiplied by 0.408 to get mm per day.
All three are in `data/crops/method_constants.csv`.

```latex
ET_0 = 0.0023\,(T_{mean} + 17.8)\,\sqrt{T_{max} - T_{min}}\;R_a
```

Use `t2m_mean_c` for the mean temperature.
FAO Kc values are designed for Penman-Monteith ET0; state the Hargreaves choice as a limit.

### Step 3: water budget per crop, year and sowing window

```latex
A = \frac{\text{effective rain} + \text{starting soil water} + \text{irrigation allowance}}{\sum_{days} K_c \cdot ET_0}
```

- **Crop demand:** daily Kc times ET0, summed over the crop's `days`.
  Kc follows the FAO stage curve: flat at `kc_ini`, rising through development, flat at `kc_mid`, falling to `kc_end`.
  Stage lengths are the suggested FAO rows scaled to `days`, once the reviewer confirms.
- **Effective rain:** look up monthly rain in FAO Training Manual 3, Table 6, with linear interpolation between rows.
  Cite the table, not a formula.
  The table stops at 250 mm a month; continuing its last slope above that is an assumption to state.
- **Starting soil water:** `gwetroot` on the sowing date times one root-zone water capacity in mm, set by the reviewer.
  This is a simplification; state it.
- **Irrigation allowance:** zero for `ULAN`.
  For `PATUBIG` and `BOMBA`, do not compute a budget in the pilot; reply with the dryness indicators and a referral.
- **Rice extra demand:** add a fixed allowance for land soaking and seepage, set by the reviewer.
- **Adequate season:** A at or above 0.8.
  This threshold is a placeholder; fix it with the reviewer before running the hindcast.

### Step 4: indicators written to the database

One row per crop and sowing window, for `barangay_code` = `BATAC`.

| Field | Meaning |
| --- | --- |
| `n_years`, `n_adequate` | Past seasons tested (up to 45), and seasons with enough water |
| `n_elnino`, `n_adequate_elnino` | The same counts for El Niño seasons only (up to 15), joined on `dry_season_start_year` |
| `median_ratio` | Median of A across years |
| `heat_freq` | Share of years with `t2m_max_c` at or above 35 °C during flowering |
| `harvest_rain_freq` | Share of years with a day of 50 mm rain or more in the last two weeks before harvest |
| `rain30_pct` | Where the last 30 days of POWER rain rank against the same dates in history |
| `soilwet_pct`, `soilwet_source`, `soilwet_date` | Where the latest root-zone soil moisture ranks against the same dates in history; `smap` or `power`; the date of that value |

- The 35 °C and 50 mm thresholds are placeholders for the reviewer to confirm.
- `rain30_pct` is not a column in the POWER CSVs; compute it from the daily rows, ending at the latest non-empty row (2026-11-11).
- `soilwet_pct` is copied from `smap_now.csv` with `soilwet_source` = `smap`.
  When SMAP is missing or more than 7 days old, compute it from POWER `gwetroot` the same way as `rain30_pct` and set `soilwet_source` = `power`.
- A sowing window whose harvest falls after the last full POWER row cannot be scored for the 2025 season; drop that year for that window and let `n_years` show it.

### Later additions

Not in the build.

- **GPM IMERG:** compare seasonal rain totals with POWER for the pilot site and report the difference.

## Rotation engine

The engine is a pure function: the same profile and indicators always return the same ranked crops and reason codes.
It contains no model call.

### Inputs

- Farmer profile: barangay, last crop, water source, priority.
- Indicators for `BATAC` and the current sowing window.
- Crop table: the rice, mungbean and soybean rows of `crops_engine.csv`.
- Season flag: El Niño or not.
  Past seasons come from `enso_dry_seasons.csv`; the current season is a config value set by hand from the latest ONI.

### Steps

1. **Filter.**
   Drop a crop when its sowing window is closed or when it has no indicator row.
   There is no soil filter in the pilot.
2. **Score** each remaining crop from 0 to 100.
3. **Rank** and attach reason codes.
4. **Check for a borderline result.**
   If the top two are within 10 points, or the top crop's water reliability is between 40% and 60%, return the borderline template.

### Scoring

The weights are starting values.
Fix them with the reviewer before the hindcast, then do not tune them to the results.

| Component | Weight | How it is computed |
| --- | --- | --- |
| Water reliability | 50 | `n_adequate / n_years`. In an El Niño season use `n_adequate_elnino / n_elnino`. |
| Rotation benefit | 20 | Full marks for a legume after rice; zero for the same crop back to back; half otherwise. |
| Timing risk | 20 | One minus the larger of `heat_freq` and `harvest_rain_freq`. |
| Farmer priority | 10 | `TUBIG`: favors the lower seasonal water demand. `KITA`: the reviewer-set `income_flag` per crop; there is no price data. |

### Reason codes

| Code | Filipino phrase for the reply |
| --- | --- |
| `R_WATER_OK` | sapat ang tubig sa karamihan ng nakaraang tag-araw |
| `R_WATER_SHORT` | madalas kulang ang tubig para dito |
| `R_LESS_WATER` | mas kaunti ang tubig na kailangan |
| `R_LEGUME` | tumutulong ito sa lupa pagkatapos ng palay |
| `R_SAME_CROP` | sunod-sunod na parehong tanim |
| `R_HEAT` | may panganib ng matinding init sa pamumulaklak |
| `R_HARVEST_RAIN` | may panganib ng malakas na ulan sa anihan |

### Sketch

```python
def recommend(profile, indicators, crops, season):
    candidates = [c for c in crops if passes_filters(c, profile, indicators)]
    if not candidates:
        return Result(template="T_NO_DATA")
    scored = sorted(
        (score(c, profile, indicators[c.name], season) for c in candidates),
        key=lambda s: s.total, reverse=True)
    best, second = scored[0], scored[1] if len(scored) > 1 else None
    if is_borderline(best, second):
        return Result(template="T_PLANT_BORDER", crops=[best, second])
    return Result(template="T_PLANT", crops=[best, second],
                  reasons=best.reason_codes)
```

### Tests

- Same input twice gives the same output.
- A rice-after-rice profile never gets full rotation marks.
- Missing indicators return `T_NO_DATA`, never a guess.
- Every reason code has a phrase, and every filled template passes `validate_sms`.

## Knowledge base and retrieval

The knowledge base is 19 hand-picked DA and PhilRice documents, not a web scrape.
It supplies the wording and source for `WHY` replies; it never supplies the water numbers.
The files and counts are in the Datasets section.

### Sources

| Source tag | Documents | Use | Reuse terms found |
| --- | --- | --- | --- |
| `PinoyRice` ([site](https://www.pinoyrice.com/)) | 15 | Rice: water, timing, harvest, drought and rotation | None stated; a Creative Commons icon in the footer names no licence |
| `DA-HVCDP` ([site](https://hvcdp.da.gov.ph/production-manuals/)) | 2 | Mungbean Production Guide (MIMAROPA); soybean guide in Cebuano (Caraga) | None stated |
| `BSWM` ([site](https://www.bswm.da.gov.ph/lists/)) | 2 | Legume inoculant; sustainable land management and drought | None stated on the documents |

### Ingestion steps (done)

1. **Log** each document: title, publisher, year, URL, access date, reuse terms, file hash (`kb_sources.csv`).
2. **Extract** text with `pymupdf` for PDFs and `trafilatura` for web pages (`scripts/kb_extract.py`).
3. **Normalize:** fix encoding, rejoin hyphenated words, remove page headers and numbers.
4. **Tables:** the few that matter are rewritten by hand as short sentences (`scripts/kb_curation.py`).
5. **Deduplicate** by paragraph hash.
6. **Restrict:** tag any chunk with chemical rates, fertilizer, pesticide or pest-control content as `restricted`.
   Restricted chunks are never retrieved.
7. **Chunk by heading**, keeping the crop name and units inside each chunk (`scripts/kb_chunk.py`).
8. **Tag** each chunk: source, title, year, crop, topic, language, URL.

### Still to do

- **Audit:** a teammate reads the 40 chunks in `kb_audit_sample.csv` and fills `clean_or_dirty`.
  Fix and repeat.
- **Embed** the 181 usable chunks and store the vectors.
- **Reviewer sign-off** on the document list.

### Retrieval

- Load only rows with `restricted` = 0.
- Embed chunks once and store vectors locally.
  A plain cosine search over 181 chunks is enough; no vector database is needed.
- Filter by crop before searching; include `general` chunks with every crop.
- Take the top 3.
  If the best score is below the threshold, return `T_REFER`.
- The `WHY` reply names the source by its `source_tag`.
- Mungbean and soybean have only 13 and 12 usable chunks, and the soybean chunks are in Cebuano.
  `WHY` for those crops uses the fixed reason phrases plus the source tag, not retrieved wording.

### Checks to report

- Chunk audit: share of the 40 sampled chunks marked clean.
- Retrieval test: 20 to 30 farmer questions, share with the correct passage in the top 3.
- Reviewer sign-off on the document list.

## LLM usage and guardrails

The model has one required job, reading free text into a command, and one optional job, smoothing the wording of a reply.
The system must work with the model switched off.

### Call 1: intent extraction

Used only when the keyword parser fails.
Temperature 0, JSON output only.

```text
System: You convert a Filipino or English SMS from a farmer into JSON.
Allowed intents: REG, LAST, PRIO, PLANT, WHY, HELP, STOP, OTHER.
Return only: {"intent": ..., "barangay": ..., "water": ..., "crop": ...,
"priority": ..., "confidence": 0-1}
Do not answer the farmer. Do not add farming advice.
```

- Confidence below 0.7, or intent `OTHER`: send `T_FALLBACK`, or `T_REFER` if the text mentions fertilizer, chemicals or pests.
- Validate the JSON against a schema.
  Invalid output counts as a failed parse.

### Call 2: wording (optional)

The model receives the filled template and may rephrase it for natural Filipino.
Skip this call for the hackathon unless there is spare time; the templates are enough.

A rephrased reply is sent only if all of these pass.
Otherwise the template is sent.

- Every number in the reply appears in the engine output, and no other digits appear.
- The recommended crop name is unchanged.
- No chemical units or product names.
- `validate_sms` passes: 150 characters, GSM 7-bit.

### Operating rules

- The model name, endpoint and key come from environment variables.
- Timeout of 8 seconds, one retry, then fall back to keyword and template behavior.
- Log every prompt and output with the template ID.
  This log is the source for the AI-use disclosure on the project page.
- The model never sees phone numbers.

## Data model and API

One SQLite file holds everything.
Phone numbers are stored only as a salted hash.

### Tables

| Table | Columns | Loaded from |
| --- | --- | --- |
| `farmers` | `phone_hash` (key), `barangay_code`, `water_source`, `last_crop`, `priority`, `created_at` | Messages |
| `messages` | `id`, `phone_hash`, `direction`, `text`, `intent`, `template_id`, `created_at`. Keep the last 3 per number. | Messages |
| `processed_events` | `event_id` (key), `received_at`. Used to drop duplicate webhooks. | Webhooks |
| `indicators` | `barangay_code`, `crop`, `sow_window`, plus the fields in the pipeline section, `updated_at` | `build_indicators.py` |
| `crops` | `crop`, `kc_ini`, `kc_mid`, `kc_end`, `days`, `is_legume`, `income_flag`, `source` | `data/crops/crops_engine.csv` (rice, mungbean, soybean) |
| `barangays` | `barangay_code`, `name`, `aliases`, `lat`, `lon`, `soil_class` | `data/barangays/barangays.csv`, hand-typed; `soil_class` empty |
| `kb_chunks` | `chunk_id`, `doc_id`, `source_tag`, `title`, `year`, `url`, `crop`, `topic`, `language`, `text`, `vector` | `data/kb/kb_chunks.csv`, rows with `restricted` = 0 only |

- `phone_hash` is HMAC-SHA256 of the number with a secret from the environment.
- The raw number exists only in memory, long enough to send the reply.
- `STOP` deletes the farmer row and that number's messages.
- Restricted chunks are not loaded into the database at all.

### Endpoints

| Method and path | Access | Purpose |
| --- | --- | --- |
| `POST /webhook/httpsms` | Shared secret | Receives gateway events. Checks the secret, records the event ID, returns 200 at once, and hands the message to a background task. |
| `POST /simulate` | Public, rate-limited | Body: `from` and `text`. Runs the same handler synchronously and returns the reply as JSON. Used by the web simulator. |
| `GET /indicators/{barangay_code}` | Public | Returns the indicator rows as JSON for the chart. |
| `GET /health` | Public | Liveness check. |
| `GET /` | Public | Home page: what AgriChat is, the simulator and the hindcast chart. |
| `GET /data` | Public | Datasets, sources, limits and AI use. |
| `GET /admin/login`, `POST /admin/login`, `POST /admin/logout` | Public form, then session | Admin sign-in and sign-out. |
| `GET /admin` | Session | Dashboard: counts and system health. |
| `GET /admin/farmers`, `POST /admin/farmers/{phone_hash}/delete` | Session | Registered profiles; delete one profile and its messages. |
| `GET /admin/messages` | Session | Message log with intent and template ID. |
| `GET /admin/indicators` | Session | Indicator rows and the reviewer-set thresholds, read-only. |
| `GET /admin/kb` | Session | Knowledge-base documents and usable chunks, read-only. |

### Gateway contract

- **Inbound:** handle only the `message.phone.received` event.
  Read the sender, the content and the message ID from the event body.
- **Outbound:** call the httpSMS send endpoint with the API key header, the gateway number as sender, the farmer's number and the reply text.
- Log the first real webhook and copy the field names from it and from the [httpSMS docs](https://docs.httpsms.com/webhooks/introduction).
  Do not code them from memory.

### Handler flow

1. Drop duplicates and non-mobile senders; apply the rate limit.
2. Parse the text by keyword, then by model if needed.
3. Load or create the profile; apply `REG`, `LAST`, `PRIO` or `STOP`.
4. For `PLANT`: run the engine and fill the template.
5. For `WHY`: load the last recommendation, retrieve passages, fill `T_WHY`.
6. Validate, send, and store the message pair.

### Configuration

`HTTPSMS_API_KEY`, `HTTPSMS_FROM`, `WEBHOOK_SECRET`, `PHONE_HASH_SECRET`, `LLM_ENDPOINT`, `LLM_KEY`, `LLM_MODEL`, `LLM_ENABLED`, `DB_PATH`, `SEASON_EL_NINO`, `ADMIN_PASSWORD_HASH`, `SESSION_SECRET`.
None of these go in the repo.

## Website and admin panel

The website is the deployed product: one public URL, served by the same FastAPI process that handles SMS.
The admin panel is a planned part of it and is the first web feature to cut if time runs short.

### Public pages

| Page | Content |
| --- | --- |
| Home (`/`) | One-paragraph explanation, the SMS simulator, and the chart of the three rotations in normal and El Niño years |
| Data (`/data`) | NASA POWER and SMAP and their roles, the SMAP-versus-POWER comparison, other data with terms, limits, AI use, and links to the repo |

- The simulator is a phone-style chat box that posts to `/simulate` and shows the reply with its character count.
- The simulator uses a throwaway sender ID kept in the browser session, never a real phone number.
- Filipino replies show an English translation beside them, because the project page must be in English.
- The chart reads `/indicators/BATAC`.
  Show it only as the data comes out.

### Admin panel

| Page | Shows | Actions |
| --- | --- | --- |
| Dashboard | Profiles registered, messages in the last 24 hours, share answered by template or by model, last gateway event, date of the latest POWER row and SMAP day, and the current `soilwet_source` | None |
| Farmers | `phone_hash` (shortened), barangay, water source, last crop, priority, date registered | Delete a profile and its messages |
| Messages | Direction, text, intent, template ID, time | Filter by intent or template |
| Indicators | Every indicator row, plus the thresholds and weights the reviewer fixed | None; read-only |
| Knowledge base | The 19 documents with source tag and link; usable chunks by crop and topic | None; read-only |

- Thresholds, weights and the ENSO rule are not editable in the panel.
  They are fixed before the hindcast and changed only in the repo, with a commit.
- The panel never shows a phone number, because none is stored.
- Restricted chunks are not in the database, so the panel cannot show them.

### Access and security

- One shared admin password.
  Only its Argon2 hash is in the environment (`ADMIN_PASSWORD_HASH`).
- A successful login sets a session cookie signed with `SESSION_SECRET`, marked `HttpOnly`, `Secure` and `SameSite=Lax`, expiring after 8 hours.
- Every admin route checks the session through one FastAPI dependency.
  A request without a valid session is redirected to the login page.
- Every state-changing admin form carries a CSRF token tied to the session.
- Login attempts are rate-limited per IP address, for example 5 per 15 minutes.
- `/simulate` is rate-limited per IP address, so the public page cannot be used to run up model costs.
- Templates escape all output by default.
  Message text from farmers is never rendered as HTML.
- Admin pages send `Cache-Control: no-store` and are excluded from search engines.
- Caddy terminates HTTPS and redirects HTTP to HTTPS.
  The app listens on localhost only.

### Deployment

1. Point a domain or subdomain at the VPS.
2. Install the app in a virtual environment and load the SQLite tables from `data/`.
3. Run Uvicorn as a systemd service bound to `127.0.0.1`, with the configuration in an environment file readable only by the service user.
4. Put Caddy in front as a reverse proxy; it obtains the certificate automatically.
5. Set the httpSMS webhook URL to `https://<domain>/webhook/httpsms`.
6. Open the public URL in a private window and run the five end-to-end exchanges.

### Repo layout

In the repo today:

```text
README.md                 data handoff: pilot, files to use, build order
Project_overview.md       problem, findings, datasets, decisions
Technical_spec.md         this file
00_README_run_order.md    run order for the dataset handoffs
01/ .. 07/                one fetch handoff per dataset
scripts/                  fetch_power.py, check_power.py, build_oni.py, check_oni.py,
                          build_crops.py, kb_http.py, kb_docs.py, kb_extract.py,
                          kb_curation.py, kb_chunk.py, kb_build.py, kb_check.py
data/
  power/                  POWER daily CSVs, metadata, raw/ JSON
  oni/                    ONI series, dry-season labels, rule, raw/
  crops/                  engine crop table, FAO-56 tables, DA durations, raw/
  kb/                     sources, chunks, durations, candidates, audit sample
  provenance.csv          source, access time, terms and script per file
```

To build:

```text
app/         main.py, handler.py, parser.py, templates.py, sms.py, llm.py, db.py
engine/      rotation.py, reason_codes.py
scripts/     fetch_smap.py, check_smap.py
pipeline/    et0.py, budget.py, build_indicators.py
kb/          retrieve.py
validation/  hindcast.py, retrieval_test.py, results/
web/         public.py, admin.py, auth.py
             templates/  base, home, data, admin pages (Jinja2)
             static/     site.css, simulator.js
deploy/      Caddyfile, agrichat.service, .env.example
data/        barangays/barangays.csv, indicators.csv, smap/
tests/
requirements.txt, LICENSE, PROVENANCE.md, AI_USE.md
```

## Testing, build plan and submission

The data is in place as of Sunday 08:20.
Features freeze at 12:00 Sunday and submission is by 21:30.
Times are PHT.

### Tests

- **Unit:** parser commands and aliases, `validate_sms`, engine determinism, template lengths.
- **Data:** `check_power.py`, `check_oni.py`, `check_smap.py` and `kb_check.py` pass.
- **Fallback:** with `smap_now.csv` removed or older than 7 days, `build_indicators.py` writes `soilwet_source` = `power` and the reply still goes out.
- **Pipeline:** ET0 values fall in a plausible range for the site; budgets rerun to the same numbers.
- **Validation scripts:** `hindcast.py` and `retrieval_test.py` write result tables into the repo.
- **Web:** public pages return 200 without a session; every admin route redirects to login without one; a wrong password is rejected; a state-changing form without a CSRF token is rejected.
- **End to end:** five full exchanges on a real keypad phone, and the same five through the simulator on the deployed site, checked on a phone screen and a laptop.

### Build plan

**Done by Sunday 08:20**

- [x] Pilot chosen: Batac, Ilocos Norte
- [x] POWER fetched and checked for the pilot point
- [x] ENSO dry-season labels built and checked, rule fixed
- [x] Crop table built from FAO-56 and DA durations, draft values verified
- [x] Knowledge base: 19 documents logged, 243 chunks tagged, restricted content flagged

**Carried over, no code in the repo yet**

- [ ] Reviewer decisions written down with the time (list in `Project_overview.md`)
- [ ] `data/barangays/barangays.csv` typed in
- [ ] Backend: webhook, send call and a template reply working through the gateway phone
- [ ] Chunk audit marked by a teammate
- [ ] LICENSE (Apache-2.0), `PROVENANCE.md` and `AI_USE.md`

**Sunday, before 12:00, in this order**

- [ ] SMAP AppEEARS task submitted first; `fetch_smap.py` and `check_smap.py` run once it is done
- [ ] `et0.py`, then `budget.py`, then `build_indicators.py`, writing `indicators.csv`
- [ ] `hindcast.py`: hits, misses and false alarms against the rainfall-only baseline
- [ ] Engine and the `PLANT` and `WHY` templates wired to the indicators
- [ ] Website deployed on the VPS over HTTPS: home page with the simulator and chart, and the data page
- [ ] Admin panel: login, dashboard, farmers, messages
- [ ] Reviewer marks the sample replies

**Sunday 12:00: feature freeze**

**Sunday 12:00 to 17:00**

- [ ] Project page text, including limitations and AI use
- [ ] Demo deck or video, with one recorded exchange on a real keypad phone
- [ ] Citations and licenses for all data, code, libraries and documents

**Sunday 17:00 to 21:30**

- [ ] Open every link in a private window
- [ ] Fresh-eyes review and fixes
- [ ] Submit by 21:30; the time to 23:59 is buffer only

### What to cut first

1. Model wording (call 2).
2. SMAP, if the AppEEARS task has not finished by 10:00: `soilwet_pct` stays on POWER, and SMAP moves back to next steps on the project page.
3. The admin panel's indicators and knowledge-base pages, then the whole admin panel.
4. `PRIO` and the third rotation (soybean).
5. Retrieval: `WHY` falls back to fixed reason phrases with a source tag.
6. The live gateway: keep the website simulator and the recorded phone video.

The public website is not on this list: it is the submission link.
IMERG and MODIS are already cut.

### Demo

- Public link: the website, whose simulator calls the same backend as the phone.
- The admin panel is shown in the deck or video only, with no login details and no real profiles on screen.
- Recorded: one `PLANT` and `WHY` exchange on a real keypad phone, with numbers hidden.
- One chart: the three rotations in normal years and in El Niño years, from `/indicators`.
  Show it only as the data comes out.

### Submission checklist

The demo limits and AI media rules below are from the 2025 guide.
Confirm them in the 2026 guide.

- [ ] Every member is on the Manila event and none is waitlisted
- [ ] Field Shift is the selected challenge
- [ ] Project page and all linked material are in English; Filipino SMS examples have English translations
- [ ] Demo is within the limit: 7 slides or a 30-second video with English subtitles
- [ ] Every link opens without a login; the admin login is not linked from the project page
- [ ] The admin password and session secret are not in the repo, the deck or any screenshot
- [ ] NASA POWER and SMAP Level 4 listed with their roles; NOAA ONI, FAO-56 and the DA documents listed under other data with their terms, from `data/provenance.csv`
- [ ] SMAP is listed as data used only if `smap_now.csv` was built; otherwise it is under next steps
- [ ] BSWM soil, IMERG and MODIS appear only under next steps
- [ ] No Earthdata credentials in the repo, the deck or any screenshot
- [ ] `data/kb/raw/` and `data/crops/raw/da/` are not in the public repo
- [ ] AI use described, including the model, what it did and what humans verified
- [ ] Any AI-generated image or video carries a visible watermark
- [ ] No phone numbers, names of farmers or faces of minors anywhere
- [ ] No product-pitch or commercial framing
