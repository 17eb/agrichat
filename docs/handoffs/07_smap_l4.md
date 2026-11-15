# Handoff 07 — SMAP Level 4 root-zone soil moisture (9 km)

## Goal

Extract the SMAP Level 4 soil-moisture time series for the pilot barangay and save it as daily CSV. AgriChat, an SMS crop-rotation advisor, uses it for one indicator: how wet the root zone is now compared with the same dates in past years (`soilwet_pct`). It is an add-on. Nothing else waits on it, and the NASA POWER value (`GWETROOT`) stays as the fallback.

This is an API extraction through NASA AppEEARS, which returns a CSV for a point so no HDF5 files need handling. Requests are queued and can take from minutes to hours: submit first, then do other work.

## Inputs to fill in

- `LAT`, `LON`, `BARANGAY_CODE` (from handoff 05)
- A NASA Earthdata Login account (free, `https://urs.earthdata.nasa.gov`). A team member must create it. Pass the username and password or token through environment variables `EARTHDATA_USER`, `EARTHDATA_PASS`. Never write them to a file, log or the repo.

## Source

- Product: SMAP L4 Global 3-hourly 9 km EASE-Grid Surface and Root Zone Soil Moisture Geophysical Data, `SPL4SMGP`, Version 8. Record begins 31 March 2015.
- AppEEARS site and API: `https://appeears.earthdatacloud.nasa.gov/` and `https://appeears.earthdatacloud.nasa.gov/api/`

Read the API docs before coding and confirm each call below; the docs win where they differ.

## API flow

1. **Log in.** `POST /api/login` with HTTP basic auth (Earthdata username and password). The response contains a bearer token. Send `Authorization: Bearer <token>` on every later call.
2. **List layers.** `GET /api/product/SPL4SMGP.008`. Save the response. Pick the exact layer names for the variables below; do not guess them.
3. **Submit a point task.** `POST /api/task` with a JSON body like this:

```json
{
  "task_type": "point",
  "task_name": "agrichat_smap_pilot",
  "params": {
    "dates": [{"startDate": "03-31-2015", "endDate": "MM-DD-YYYY"}],
    "layers": [
      {"product": "SPL4SMGP.008", "layer": "<root-zone soil moisture layer>"},
      {"product": "SPL4SMGP.008", "layer": "<surface soil moisture layer>"},
      {"product": "SPL4SMGP.008", "layer": "<root-zone wetness layer>"}
    ],
    "coordinates": [
      {"id": "pilot", "category": "barangay", "latitude": LAT, "longitude": LON}
    ]
  }
}
```

   Dates are `MM-DD-YYYY`. Use today's date as the end date.

4. **Poll.** `GET /api/task/<task_id>` every 60 seconds until the status is `done`. Stop and report after 3 hours.
5. **List and download.** `GET /api/bundle/<task_id>` lists the files; download each with `GET /api/bundle/<task_id>/<file_id>` into `data/smap/raw/`. Keep the results CSV, the request JSON and the metadata files.
6. **Log out.** `POST /api/logout`.

Variables wanted:

| Variable | Meaning | Unit |
| --- | --- | --- |
| Root-zone soil moisture | 0 to 100 cm | m³/m³ |
| Surface soil moisture | 0 to 5 cm | m³/m³ |
| Root-zone wetness | Relative saturation | 0 to 1 |
| Root-zone percentile, if the product lists it | Against the product's own climatology | percent |

## Fallbacks

- If the 11-year request is rejected or stalls, split it by year and join.
- If AppEEARS is unavailable, the same product is in Google Earth Engine as `NASA/SMAP/SPL4SMGP/008` (bands `sm_rootzone`, `sm_surface`, `sm_rootzone_wetness`). This needs an Earth Engine account; ask the team before going this route.
- If neither works within the time box, stop. Report it and leave `soilwet_pct` on POWER.

## Processing steps

1. Read the results CSV. Identify the date-time column, the value column for each layer, and any fill value or quality columns from the metadata. Replace fill values with empty cells.
2. Convert timestamps from UTC to Philippine time (UTC+8) before grouping by day.
3. Aggregate the 3-hourly values to daily means. Keep `n_obs` (expect 8 per day).
4. Compute the percentile for each day: rank that day's root-zone soil moisture against all values within ±15 days of the same day of year in every other year of the record. Express as 0 to 100.
5. Write the "now" row: the latest date with data and its percentile.
6. Compare with POWER if `data/power/power_daily_1981_2025.csv` exists: correlation between SMAP root-zone wetness and POWER `gwetroot` over 2015 to 2025, and the mean difference.

## Outputs

**`data/smap/smap_l4_daily.csv`**

| Column | Notes |
| --- | --- |
| `barangay_code` | Text |
| `date` | Philippine local date |
| `sm_rootzone_m3m3`, `sm_surface_m3m3` | Daily mean |
| `sm_rootzone_wetness` | 0 to 1 |
| `sm_rootzone_pctl_product` | If the product layer exists, else empty |
| `n_obs` | 3-hourly values in the mean |
| `soilwet_pct` | Computed in step 4 |

**`data/smap/smap_now.csv`** — one row: `barangay_code, latest_date, sm_rootzone_m3m3, soilwet_pct, years_in_baseline, days_since_latest`

**`data/smap/smap_vs_power.csv`** — `n_days, pearson_r, mean_diff, note`

**`data/smap/smap_metadata.csv`** — `product, version, layer, unit, fill_value, pixel_lat, pixel_lon, first_date, last_date, task_id, accessed_utc`

## Checks

- Dates run from 2015-03-31 with no missing days; list any gaps.
- Soil moisture stays between 0 and 0.9 m³/m³ and wetness between 0 and 1.
- Most days have `n_obs = 8`; report the share that do not.
- The dry months (February to April) show lower root-zone moisture than the wet months (July to September) on average. If not, the point or the timestamps are wrong.
- The latest date is within about a week of today; report the lag.

## Limits to write into the metadata notes

- The record starts in 2015, so the percentile baseline is about 11 years, and it contains few El Niño dry seasons.
- A 9 km pixel is a model-assimilated estimate. It does not see canal irrigation or a single field.
- The product is model-only during two SMAP instrument outages (mid-2019 and Aug to Sep 2022); flag those dates if the metadata identifies them.

## Do not

- Do not store or print credentials.
- Do not download global HDF5 granules; one point through AppEEARS is enough.
- Do not fill gaps or blend SMAP with POWER values.
- Do not spend more than the agreed time box on this handoff; it is optional.

## Report back

Task ID, layer names used, pixel coordinates returned, date range, gap count, the "now" percentile, and the SMAP-versus-POWER comparison.
