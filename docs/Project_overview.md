# AgriChat - Project Overview, Findings and Datasets

Nov 15, 2026 · @GNS-KarlDevC++

## Summary

AgriChat is an SMS service that tells a Filipino rice farmer on a keypad phone which crop to plant after rice this dry season, and why, using NASA weather and soil-wetness records for their municipality.

- **Challenge:** Field Shift: Adapting Farms with NASA Data, NASA Space Apps 2026, Manila local event.
- **Users:** smallholder rice farmers without smartphones or internet.
  Municipal agricultural technicians are the second user and the escalation point.
- **Decision supported:** after the wet-season rice harvest, plant rice again or shift to a lower-water crop, and when to sow.
- **What is new:** a side-by-side comparison of rotations, with a track record tested against past seasons, delivered in one text of 150 characters or fewer.
- **How NASA data drives it:** 45 dry seasons of daily NASA POWER records (1981 to 2025) are replayed for the pilot site to count how often each rotation would have had enough water.
  SMAP Level 4 adds how wet the root zone is right now at 9 km, with POWER as the fallback.
- **Delivery:** farmers use SMS; the deployed product is one website with a public simulator and hindcast chart, plus a planned admin panel for the team and technicians.
- **Pilot:** Batac, Ilocos Norte, rainfed fields.
  The POWER point is latitude 18.06, longitude 120.56.
- **Status on 15 Nov (data handoff at 08:20):** the pilot is chosen and four datasets are collected, cleaned and checked: NASA POWER, the NOAA Oceanic Niño Index, the FAO-56 crop tables and the DA knowledge base.
  SMAP Level 4 is in the build and still to fetch.
  The water budget, indicators, hindcast, engine and SMS loop are not built yet.
- **Deadline:** submission closes Sunday 15 Nov at 23:59 PHT.
  Feature freeze is 12:00 and the internal submission target is 21:30.

The build document for developers is `Technical_spec.md`.
The file-by-file data handoff is `README.md`.

## Findings

The dry-season crop choice is the right problem: farmers are deciding it this month, during an El Niño, and water is the factor NASA data measures best.

### The problem in the Philippines

| Finding | Figure | Source |
| --- | --- | --- |
| El Niño farm losses so far | ₱9.99 billion; 324,327 farmers; 323,419 ha; 16 regions (DA, reported 11 Nov 2026) | [Daily Tribune](https://tribune.net.ph/2026/11/11/el-niño-wipes-out-p999b-in-farm-output) |
| How long the dry spell may last | DA expects it to persist into the first half of 2027 | [Daily Tribune](https://tribune.net.ph/2026/10/04/da-steps-up-preps-as-super-el-niño-threatens-phl) |
| Drought exposure of Luzon rice land | Of 1.58 million ha, about 301,000 ha are highly and 280,000 ha moderately susceptible | [PhilRice](https://www.philrice.gov.ph/farmers-advised-to-consider-early-maturing-drought-tolerant-rice-as-el-nino-nears/) |
| 2026 palay output | About 1 million MT below 2025 on current estimates; late planting, irrigation limits and risk-aversion are cited | [AgNavigator](https://www.agnavigator.com/Article/2026/11/10/philippine-q3-rice-output-slumps-18-but-el-ninos-biggest-impact-is-yet-to-hit/) |
| Fertilizer cost | World urea prices nearly doubled from February to April 2026; the country imports about 90% of its fertilizer | [Eco-Business](https://www.eco-business.com/news/from-hormuz-to-rice-fields-how-middle-east-conflict-could-worsen-philippines-next-el-nino-food-shock/) |
| Storm damage in 2026 | ₱4.38 billion; nearly 100,000 farmers and fisherfolk | [Manila Times via Newswav](https://newswav.com/article/final-tally-of-agri-damage-p4-38b-A2609_rxXhk2) |
| Why few farmers diversify | Land suitability, irrigation and drainage, and perishability; PhilRice asks for updated advisories specific to place and season | [PhilRice](https://www.philrice.gov.ph/crop-diversification-mitigates-climate-change-impacts) |
| Government direction | DA El Niño measures include adjusted planting schedules and crop diversification | [Milling MEA](https://millingmea.com/?p=2042224) |

### What already exists

- **Project SARAI (UPLB, funded by DOST-PCAARRD)** gives site-specific advisories for nine crops and guides what and when to plant from climate forecasts and expected water deficits.
  It has a mobile app, Bantay SARAI.
  Sources: [DEPDev](https://depdev.gov.ph/?p=39910), [DOST-PCAARRD](https://newport.pcaarrd.dost.gov.ph/index.php/quick-information-dispatch-qid-articles/sarai-phase-2-continues-to-provide-solutions-to-farmers-for-a-smarter-agriculture).
- **Consequence:** AgriChat must not claim to be the first satellite crop advisory.
- **The gap AgriChat fills:** reach on keypad phones by SMS, a comparison of rotations instead of a single-crop advisory, and a published hindcast with stated limits in every reply.
- **Open question:** PhilRice is believed to run an SMS helpline (the PhilRice Text Center).
  This is still not verified.
  Check it and state how AgriChat differs.

### What past Space Apps results tell us

These come from the team research file dated 7 Nov.

- In 2025, 11,511 projects produced about 1,290 Global Nominees (roughly 11%) and 10 winners.
  Local nomination is the first gate.
- Manila 2025 had 24 teams and 2 nominees.
  Both were quantitative Earth-data projects; one became a Global Finalist and one an Honorable Mention.
- 20 of 30 winner pages from 2023 to 2025 report no quantitative validation, so a tested result is a way to stand out.
- Chat-style projects have won when tied to a defined user and NASA data (Team I.O. in 2024, Twisters in 2025).
- On 7 Nov, Field Shift had 1,308 registered teams and Manila had 91.

### Technical findings

Rows marked 15 Nov come from the data collection and replace the 14 Nov desk findings.

| Topic | Finding | Consequence |
| --- | --- | --- |
| Language model | Microsoft lists gpt-4o-mini (2024-07-18) on Azure with a retirement date of 1 Oct 2026 ([Microsoft Learn](https://learn.microsoft.com/en-sg/Azure/foundry/concepts/model-lifecycle-retirement)) | Check what you can deploy today; keep the model name in config |
| NASA POWER coverage (15 Nov) | The Batac point returned 16,436 daily rows for 1981 to 2025 with no gaps in rain, temperature, humidity, wind or soil wetness | It is the backbone, as planned |
| NASA POWER solar radiation (15 Nov) | `ALLSKY_SFC_SW_DWN` is empty for 1981 to 1983; the source has no data before 1984 | Hargreaves ET0 does not need it, so all 45 seasons stay usable |
| NASA POWER latest days (15 Nov) | The last two days of the 2026 file (12 and 13 Nov) are empty; the latest full row is 11 Nov | "Conditions now" uses the latest non-empty row |
| Scale (15 Nov) | The POWER cell is about 50 km and its mean elevation is 264 m; every barangay in Batac shares it, and Batac rice land is lower and slightly warmer | Advice is at municipality scale, not per plot |
| Irrigation | Satellites do not see canal allocation | The pilot is rainfed; canal and pump farmers get a referral |
| ENSO labels (15 Nov) | The NOAA CPC file is the ONI on ERSST v6; 15 of the 45 dry seasons from 1981 to 2025 are El Niño by the fixed rule | Enough El Niño seasons for a separate count; cite the v6 version |
| Current season (15 Nov) | The dry season starting Nov 2026 is not in the label table because the Dec to Feb value does not exist yet; the latest season in the file (Aug to Oct 2026) is +2.46 and inside an El Niño episode, provisional | The El Niño flag for this season is set by hand from that value |
| Crop coefficients (15 Nov) | FAO-56 Table 12 confirms all 12 draft Kc values; mungbean is the "Green Gram and Cowpeas" row | The bean stand-in is no longer needed |
| Crop durations (15 Nov) | DA and PhilRice guides give rice 102 to 114 days, mungbean 60 to 70 and soybean 90 to 100; no corn or peanut duration was found | Rotation set is rice, mungbean and soybean; corn and peanut are dropped |
| Effective rain (15 Nov) | FAO Training Manual 3 gives Table 6 only, with no formula; the draft rule reproduces 26 of 26 table values to within 0.5 mm | Use and cite the table, not a formula |
| ET0 method (15 Nov) | The Hargreaves equation matches FAO-56 Equation 52; FAO Kc values are designed for Penman-Monteith ET0 | State the mismatch as a limit |
| Knowledge base: PinoyRice (15 Nov) | 15 documents selected; the footer shows a Creative Commons icon but names no licence | Store short passages with source and link; do not republish whole documents |
| Knowledge base: HVCDP (15 Nov) | The Mungbean Production Guide (MIMAROPA) and a Cebuano soybean guide (Caraga) were selected; no corn manual; no reuse statement | Only 13 mungbean and 12 soybean passages are usable, so `WHY` for those crops uses fixed reason phrases plus the source tag |
| Knowledge base: BSWM (15 Nov) | Two documents selected (legume inoculant, sustainable land management); the soil series shapefile was not processed | No soil filter in the pilot |
| Knowledge base: restricted content (15 Nov) | 62 of 243 passages (26%) mention chemical rates, fertilizer or pest control and are flagged restricted | They are never retrieved |
| SMS gateway | httpSMS posts webhooks for received, sent, delivered, failed and expired messages ([httpSMS docs](https://docs.httpsms.com/webhooks/introduction)) | Fits the planned flow |
| SMS encoding | The letter ñ is in the standard GSM 7-bit alphabet; the peso sign, curly quotes, long dashes and emoji are not, and they cut a message to 70 characters | Filter those characters; this note is still unverified against the GSM standard |

## Solution

A farmer registers once, tells AgriChat their last crop, and gets a ranked recommendation with a reason in one text.

1. **Register** the barangay and water source: `REG SAN JOSE ULAN`.
2. **Report the last crop:** `LAST PALAY`.
3. **Ask what to plant:** `PLANT`.
4. **Ask for the reason:** `WHY`.

### Example exchange

The counts X and Y are placeholders until the engine runs.
The 45 is the number of dry seasons in the record; the real count depends on the sowing window.
The barangay name is illustrative until the Batac barangay list is typed in.
A native speaker on the team should polish the Filipino wording.

| Farmer texts | AgriChat replies |
| --- | --- |
| `REG SAN JOSE ULAN` | Rehistrado ka sa Brgy San Jose, sahod-ulan. I-text ang LAST at huling tanim mo. Hal: LAST PALAY |
| `LAST PALAY` | Naitala: palay ang huling tanim. I-text ang PLANT para sa payo sa susunod na tanim. |
| `PLANT` | Payo: MUNGGO. Sapat ang tubig sa X sa 45 nakaraang tag-araw dito; palay ulit, Y sa 45. I-text ang WHY para sa dahilan. |
| `WHY` | Dahilan: mas kaunti ang tubig na kailangan ng munggo at tumutulong ito sa lupa. Batayan: NASA POWER, DA-HVCDP. Di sakop: presyo, peste. |

The `PLANT` reply carries a number from the NASA record, which is what separates it from generic advice.
The team's draft reply ("consider mung bean if soil and water conditions are suitable") has no data in it and should be replaced by this form.

### Delivery and tech stack

AgriChat is deployed as one website on a single server.
The same process answers the SMS gateway, serves the public pages and serves the admin panel.

| Surface | Who uses it | What it does |
| --- | --- | --- |
| SMS | Farmers on keypad phones | Register, report the last crop, ask what to plant and why |
| Public website | Judges and the public, no login | Explains the service, lets anyone try the SMS exchange in a simulator, and shows the hindcast chart, data sources and limits |
| Admin panel | The team and municipal technicians, password login | Shows registered profiles, the message log, indicators, the knowledge base and system health |

The admin panel is planned and is the first web feature to cut if time runs short.
It is read-only except for deleting a farmer profile; thresholds and weights cannot be edited there, so results cannot be tuned after the hindcast.

| Layer | Choice |
| --- | --- |
| Backend and website | Python 3.13, FastAPI on Uvicorn, server-rendered Jinja2 pages |
| Database | SQLite, one file |
| Engine and data pipeline | Plain Python rules over the NASA POWER, ONI and FAO-56 tables |
| Retrieval | Local multilingual embeddings with a cosine search |
| Language model | A small Azure OpenAI chat model, for reading free text only |
| SMS gateway | httpSMS on a dedicated Android phone |
| Hosting | One VPS, Caddy for HTTPS, the app as a systemd service |

The full stack table, routes and security rules are in `Technical_spec.md`.

### Hackathon scope

| In | Later, after rotation works | Out |
| --- | --- | --- |
| One municipality: Batac, Ilocos Norte, rainfed | Weather and heat alerts | Free-form AI chat |
| One rice-based rotation set: rice, mungbean, soybean | Pest guidance from verified sources only | Livestock and labor heat stress |
| `PLANT` and `WHY` with reasons | Subscriptions and pushed alerts | Fertilizer dilution or any chemical dose |
| A small reviewed knowledge base | More municipalities, corn and peanut | Unverified pest advice |
| A public website with the simulator and hindcast chart | BSWM soil series | Canal and pump water budgets |
| An admin panel, if time allows | Per-technician admin accounts | Editing thresholds from the admin panel |
| SMAP root-zone soil moisture for "conditions now", POWER as fallback | | |

## NASA data

Two NASA datasets are in the build.
NASA POWER produces the core result on its own.
SMAP Level 4 gives a sharper reading of current soil moisture; if it is missing or more than 7 days old, POWER `GWETROOT` is used and the indicator records which source it came from.

| Dataset | What we take from it | Role in the advice | Status on 15 Nov |
| --- | --- | --- | --- |
| NASA POWER daily (point API, `community=AG`) | Rainfall, max, min and mean temperature, humidity, wind, solar radiation, root-zone and surface soil wetness, 1 Jan 1981 to 11 Nov 2026 | Replays every past dry season to count water-adequate seasons per crop; gives heat and harvest-rain risk and "conditions now" | Collected and checked |
| SMAP Level 4 root-zone soil moisture (`SPL4SMGP` v8, AppEEARS point) | Daily root-zone and surface soil moisture at 9 km, 31 Mar 2015 to the latest day | `soilwet_pct`: how wet the root zone is now against the same dates since 2015; not used in the hindcast | In the build; to fetch (handoff 07, Earthdata login needed). POWER `GWETROOT` is the fallback |
| GPM IMERG | Rainfall at about 10 km | Cross-check of POWER rainfall for the pilot site | Not collected; next steps |
| MODIS vegetation index | Greenness every 16 days at 250 m | Confirms when fields are actually cropped | Not collected; next steps |
| Landsat | 30 m imagery | None: cloud cover and processing time are too costly | Cut |

Do not list IMERG, MODIS or Landsat as data used on the project page.
List SMAP as data used only once `data/smap/smap_now.csv` is built; if the fetch misses the 10:00 cut, move it back to next steps.

### Other data to declare

These are not NASA data and go in the "Partner and other data" field.

| Dataset | Role | Status on 15 Nov |
| --- | --- | --- |
| NOAA Oceanic Niño Index (CPC, ERSST v6) | Labels which past dry seasons were El Niño seasons | Collected and checked |
| FAO-56 crop tables and FAO Training Manual 3 | Crop coefficients, stage lengths, root depth, soil water, ET0 and effective-rain methods | Collected and checked against the draft values |
| DA and PhilRice guides: crop durations | Days to maturity for rice, mungbean and soybean | Collected |
| DA knowledge-base documents (PinoyRice, DA-HVCDP, BSWM) | Wording and sources for `WHY` replies | Collected; passage audit by a teammate still open |
| BSWM soil series | Soil texture and drainage for the barangay | Not collected; no soil filter in the pilot |
| PSA crop statistics | Provincial dry-season harvests, for validation only | Not collected; the hindcast is checked against El Niño seasons and the rainfall-only baseline unless this is fetched |

### Datasets collected

Every file is under `data/`, with the unchanged download in a `raw/` folder beside it.
Source URL, access time, terms and the script for each file are in `data/provenance.csv`.
Column-level detail is in the Datasets section of `Technical_spec.md`.

| Dataset | Main files | Size | Coverage |
| --- | --- | --- | --- |
| NASA POWER daily | `power/power_daily_1981_2025.csv`, `power/power_daily_2026.csv` | 16,436 and 317 daily rows, 9 parameters | 1 Jan 1981 to 13 Nov 2026 at LAT 18.06, LON 120.56 |
| NOAA ONI | `oni/oni_seasonal.csv`, `oni/enso_dry_seasons.csv` | 921 three-month seasons; 45 dry seasons | 1950 to Aug-Oct 2026; dry seasons 1981 to 2025, 15 El Niño |
| FAO-56 crop tables | `crops/crops_engine.csv` and six supporting tables | 5 crops (3 used) | Kc, stage lengths, root depth, soil water, method constants |
| DA knowledge base | `kb/kb_sources.csv`, `kb/kb_chunks.csv` | 19 documents, 243 passages, 181 usable | Rice 128 usable passages, general 28, mungbean 13, soybean 12 |

Check scripts in `scripts/` were rerun on 15 Nov and pass.
Known gaps are listed under "Limits to state on the project page".

### Notes on access

- **Terms of use** were not stated on the POWER API page or the NOAA file, and are recorded as not verified.
  The FAO-56 front page requires permission to reproduce the publication; only table rows and formulas were extracted.
- **DA documents** show no reuse statement.
  Raw PDFs stay out of the repository (`data/kb/raw/` and `data/crops/raw/da/` are ignored); only short passages with source and link are stored.
- **Planetary Computer** is an access route run by Microsoft.
  It is not used in the build.
- **Meteomatics** is a commercial service.
  It is not used; nothing depends on it.

## Validation and safety

Three checks produce the evidence for the project page.
Set every threshold before looking at results, and report misses as well as hits.

| Check | Method | What we report |
| --- | --- | --- |
| Engine hindcast | Compute water adequacy for each crop in each of the 45 past dry seasons at the pilot site. Compare the seasons flagged water-short with the 15 El Niño seasons (NOAA index). Add provincial dry-season palay harvests (PSA) only if that data is fetched. | Hits, misses and false alarms, against a baseline that uses average rainfall only |
| Retrieval | 20 to 30 real farmer questions, each with its correct source passage. | Share of questions where the right passage is in the top 3 |
| Reply review | The agriculture reviewer (Doc Hazel) marks about 20 sample replies pass or fail. | Pass count and what was fixed |

A random sample of 40 usable knowledge-base passages is in `data/kb/kb_audit_sample.csv`.
A teammate reads each and marks it clean or dirty.
Report that rate.

The ENSO labeling rule is already fixed in `data/oni/README_rule.txt`.
Do not change it after seeing hindcast results.

### Safety rules

- The language model never produces agronomic facts or numbers.
  Numbers come from the engine; facts come from retrieved, tagged passages.
- No chemical concentrations, dilution ratios or application instructions are generated.
  Those questions are referred to the municipal agriculture office.
- If retrieval is weak or data is missing, the reply says so and refers the farmer to a technician.
- Borderline results are stated as borderline.
- The reviewer checks the knowledge base and sample replies before the demo.

### Limits to state on the project page

- Advice is at municipality scale, about 50 km, not per plot.
  The POWER cell averages 264 m elevation; Batac rice land is lower and slightly warmer.
- Canal and pump supply is not visible to satellites.
  The water budget is rain-only and valid for rainfed fields.
- Prices, pests and soil nutrients are outside the data.
- The pilot covers one municipality and one rotation set.
- Crop water figures are FAO reference values, not local field measurements.
- FAO Kc values are designed for Penman-Monteith ET0; AgriChat uses Hargreaves.
- Effective rain comes from FAO Training Manual 3, Table 6.
- There is no soil filter; root-zone water capacity is one assumed number from the reviewer.
- SMAP Level 4 is a 9 km model-assimilated estimate; it does not see canal irrigation or a single field.
  Its record starts in 2015, so the "conditions now" baseline is about 11 years with few El Niño dry seasons, and the hindcast uses POWER soil wetness instead.
- Mungbean and soybean have few usable guide passages, and the soybean guide is in Cebuano.
- The ONI is the ERSST v6 version from NOAA CPC; the 2025 season label is provisional.

## Judging fit

The target award is Local Impact, with Best Use of Data as the second option if the hindcast result is strong.
The criteria below are from the 2025 guide; confirm them against the 2026 guide published on 13 Nov.

| Criterion | Evidence AgriChat will show |
| --- | --- |
| Impact | A named user and decision: a rainfed rice farmer in Batac choosing the dry-season crop during an El Niño, with DA loss figures |
| Creativity | SMS reach on keypad phones plus a rotation comparison, set against SARAI and other existing tools |
| Validity | The hindcast against past El Niño seasons, the retrieval score, the reviewer pass count and a limitations section |
| Relevance | NASA POWER produces the number in every recommendation and SMAP gives current soil moisture; the brief's rotation comparison is answered directly |
| Presentation | One exchange on a real keypad phone, and a normal-year versus El Niño-year comparison of the three rotations |

The engine works for any coordinate because POWER is global.
Say so in one line; it supports a wider-impact claim without widening the build.

## Decisions

### Closed

- [x] **Pilot site.**
  Batac, Ilocos Norte, rainfed, LAT 18.06, LON 120.56.
- [x] **The three rotations.**
  Rice then rice is the baseline; rice then mungbean and rice then soybean are the alternatives.
  Corn and peanut are dropped: no DA duration and no corn guide were found.
- [x] **Data scope.**
  POWER, SMAP Level 4, ONI, FAO-56 and the DA knowledge base.
  SMAP was added on 15 Nov for `soilwet_pct` only, with POWER as the fallback.
  BSWM soil series and the barangay reference scrape are skipped.

### Needed from the reviewer before the hindcast runs

Write the answers down with the time.
Do not change them after seeing results.

- [ ] Sowing window or windows, for example 15 Nov to 15 Dec.
- [ ] Root-zone water capacity in mm (starting soil water is `gwetroot` times this).
- [ ] Adequacy threshold (placeholder: 0.8).
- [ ] `kc_end`: the midpoint (current) or the low value for crops harvested dry (0.35 for mungbean).
- [ ] Rice extra allowance for land soaking and seepage, in mm.
- [ ] Scoring weights (draft: 50, 20, 20, 10) and the 35 °C and 50 mm risk thresholds.
- [ ] How the FAO stage lengths map onto the DA durations.
  The FAO rows total 150 days for rice, 100 for mungbean and 85 for soybean; the DA durations are 108, 65 and 95.
  Scaling the stage proportions to the DA duration is the proposed default.

### Still open

- [ ] **Language model.**
  Check in the Azure portal which small model you can deploy today.
  Put the model name in an environment variable.
  The fallback is no model at all: keyword commands and templates still work.
- [ ] **Hosting and domain.**
  Use FastAPI on the VPS, not a Cloud Function.
  The plan to reply 200 and keep working needs a long-running process.
  Choose the domain or subdomain for the website.
- [ ] **Admin panel.**
  Confirm it is in the build, who gets the password, and whether technicians see it during the hackathon or only the team.
- [ ] **Barangay list.**
  Hand-type `data/barangays/barangays.csv`: one row for Batac plus 5 to 10 barangay names as aliases so `REG` matches them.
- [ ] **PSA validation data.**
  Fetch provincial dry-season palay harvests, or drop that comparison from the page.
- [ ] **Reuse rights for the knowledge base.**
  PinoyRice, HVCDP and BSWM documents show no reuse statement.
  Ask the organizers whether short passages with source and link meet the third-party materials rule.
- [ ] **2026 guides.**
  Read the 2026 Submission and Judging guides.
  Confirm the demo limits, the AI disclosure rules and the project page fields.
- [ ] **Existing SMS services.**
  Check whether the PhilRice Text Center or a similar SMS helpline is running, and write one line on how AgriChat differs.

### Risks

| Risk | Effect | Response |
| --- | --- | --- |
| The chatbot overshadows the data | Low Relevance and Validity scores | Lead the page and demo with the hindcast and the number in each reply |
| SMS plumbing takes too long | No time for validation | One person on SMS; the web simulator uses the same backend |
| Gateway phone loses signal or load during the demo | Live demo fails | Record a real-phone exchange early; the simulator is the public link |
| Model outage or wrong output | Bad advice sent | Templates by default; validator rejects any reply that fails checks |
| Reviewer time runs short | Unchecked agronomy and no fixed thresholds | Get the seven reviewer decisions first; review the 19 documents already selected |
| Phone numbers leak | Breaks the personal-data rule | Hash numbers in storage; none in logs, screenshots or the repo |
| Raw DA documents get committed | Breaks the third-party materials rule | Both raw folders are in `.gitignore`; check before every push |
| The admin panel is exposed or its password leaks | Farmer profiles and messages become readable | Login on every admin route, HTTPS only, hashed password in the environment, no phone numbers stored, no login details in the deck |
| The public simulator is abused | Model cost and a slow site during judging | Rate limit per IP address; the simulator works with the model switched off |

## Sources

Context pages were accessed on 14 Nov 2026.
Data sources were downloaded between 23:29 UTC on 14 Nov and 00:10 UTC on 15 Nov; exact times are in `data/provenance.csv`.
The news figures were read from search-result excerpts, not the full articles; open each link before quoting a figure on the project page.

**Philippine context**

- [El Niño wipes out ₱9.99B in farm output, Daily Tribune](https://tribune.net.ph/2026/11/11/el-niño-wipes-out-p999b-in-farm-output)
- [DA steps up preps as Super El Niño threatens Phl, Daily Tribune](https://tribune.net.ph/2026/10/04/da-steps-up-preps-as-super-el-niño-threatens-phl)
- [Farmers advised to consider early-maturing, drought-tolerant rice, PhilRice](https://www.philrice.gov.ph/farmers-advised-to-consider-early-maturing-drought-tolerant-rice-as-el-nino-nears/)
- [Crop diversification mitigates climate-change impacts, PhilRice](https://www.philrice.gov.ph/crop-diversification-mitigates-climate-change-impacts)
- [Philippine Q3 rice output slumps 18%, AgNavigator](https://www.agnavigator.com/Article/2026/11/10/philippine-q3-rice-output-slumps-18-but-el-ninos-biggest-impact-is-yet-to-hit/)
- [From Hormuz to rice fields, Eco-Business](https://www.eco-business.com/news/from-hormuz-to-rice-fields-how-middle-east-conflict-could-worsen-philippines-next-el-nino-food-shock/)
- [Final tally of agri damage: ₱4.38B, Manila Times via Newswav](https://newswav.com/article/final-tally-of-agri-damage-p4-38b-A2609_rxXhk2)
- [High fertilizer costs, El Niño drag down Philippine rice production, Milling MEA](https://millingmea.com/?p=2042224)

**Existing tools**

- [NEDA explores UPLB remote-sensing technology (Project SARAI), DEPDev](https://depdev.gov.ph/?p=39910)
- [SARAI Phase 2 continues to provide solutions to farmers, DOST-PCAARRD](https://newport.pcaarrd.dost.gov.ph/index.php/quick-information-dispatch-qid-articles/sarai-phase-2-continues-to-provide-solutions-to-farmers-for-a-smarter-agriculture)

**Data and methods**

- [NASA POWER Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- [NOAA CPC Oceanic Niño Index data file](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) and [ERSST v6 reference table](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/oni/v6/)
- [FAO-56, Chapter 3: Hargreaves ET0 (Eq. 52) and extraterrestrial radiation (Eq. 21)](https://www.fao.org/4/x0490e/x0490e07.htm)
- [FAO-56, Chapter 6: stage lengths (Table 11) and crop coefficients (Table 12)](https://www.fao.org/4/x0490e/x0490e0b.htm)
- [FAO-56, Chapter 7: soil water characteristics (Table 19)](https://www.fao.org/4/x0490e/x0490e0c.htm)
- [FAO-56, Chapter 8: root depth and depletion fraction (Table 22)](https://www.fao.org/4/x0490e/x0490e0e.htm)
- [FAO Irrigation Water Management Training Manual 3, Chapter 3: effective rainfall (Table 6)](https://www.fao.org/4/s2022e/s2022e03.htm)

**Knowledge-base sources**

The 19 selected documents, with title, publisher, link and file hash, are listed in `data/kb/kb_sources.csv`.

- [PinoyRice Knowledge Bank](https://www.pinoyrice.com/) (15 documents)
- [DA HVCDP production manuals](https://hvcdp.da.gov.ph/production-manuals/) (2 documents)
- [BSWM downloads](https://www.bswm.da.gov.ph/lists/) (2 documents)

**Tools**

- [httpSMS webhooks documentation](https://docs.httpsms.com/webhooks/introduction)
- [Microsoft Foundry model lifecycle and retirement](https://learn.microsoft.com/en-sg/Azure/foundry/concepts/model-lifecycle-retirement)

**Verification status**

- Verified against the saved FAO pages: the 12 draft Kc values and the Hargreaves equation (`data/crops/verification_vs_spec.csv`).
- Not found in the source: an effective-rain formula.
  FAO gives Table 6 only.
- Still not verified: the GSM character-set note, and the terms of use for NASA POWER and the NOAA ONI file.
- Space Apps rules and statistics come from the team research file of 7 Nov, which used the 2025 guides.
