# Hindcast summary

Each past dry season at the pilot site is flagged water-short by the engine rule or by a rainfall-only baseline.
The engine flags a season when the water ratio A is below 0.8.
The baseline flags a season when crop-period rain is below the average of all tested seasons.
Both are compared with the El Nino seasons from the NOAA index.
A hit is a flagged El Nino season, a miss is an unflagged El Nino season, and a false alarm is a flagged season that is not El Nino.

| Crop | Rule | Seasons | El Nino | Flagged | Hits | Misses | False alarms | El Nino caught | Non-El Nino flagged |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rice | engine | 45 | 15 | 38 | 14 | 1 | 24 | 93% | 80% |
| rice | baseline | 45 | 15 | 31 | 14 | 1 | 17 | 93% | 57% |
| mungbean | engine | 45 | 15 | 16 | 7 | 8 | 9 | 47% | 30% |
| mungbean | baseline | 45 | 15 | 33 | 14 | 1 | 19 | 93% | 63% |
| soybean | engine | 45 | 15 | 29 | 14 | 1 | 15 | 93% | 50% |
| soybean | baseline | 45 | 15 | 31 | 14 | 1 | 17 | 93% | 57% |

Limits: one pilot point, no yield data, and a flagged season is not a crop failure.
A season whose crop period runs past the last full weather row is left out and shows in the season count.
The thresholds are reviewer placeholders in `engine/params.py` and were not tuned to these results.
