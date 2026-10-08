# 4NextLuas

Alexa skill that tells you when the next Dublin Luas trams are due at a stop, using the
NTA GTFS-Realtime API. Sibling of [4NextBus](https://github.com/ZarleyLtd/4NextBus).
Invocation name: **four next luas**.

- "Alexa, ask four next luas from Dundrum northbound"
- "Alexa, ask four next luas from Sandyford towards the city"
- "Alexa, ask four next luas to set my favourite stop to Heuston eastbound"
- "Alexa, ask four next luas for my favourite stop"
- "Alexa, ask four next luas" (uses your favourite)

A favourite is **one platform** (one direction at a named station). You can also ask for
any stop by name.

## Layout

```
src/common/        GTFS time handling, predictions, realtime fetch, speech, DynamoDB, station matching
src/skill/         Lambda handler (ask-sdk-core)
ingest/            daily timetable build (DuckDB over the TFI GTFS zip -> DynamoDB)
tools/             local proof-of-concept and helper scripts
skill-package/     Alexa skill manifest and en-GB interaction model
tests/             pytest
template.yaml      CloudFormation: DynamoDB table, Lambda, role, SSM parameter
```

## Voice model

Canonical files:

- Interaction model: [`skill-package/interactionModels/custom/en-GB.json`](skill-package/interactionModels/custom/en-GB.json)
- Store listing: [`skill-package/skill.json`](skill-package/skill.json)
- Regenerate the model from GTFS: `python tools/build_voice_model.py`

Paste the JSON into the Alexa console **Build → Interaction Model → JSON Editor**, then Save
and Build. A new unpublished skill can start with `en-GB` only.

### Invocation vs display name

| What users see / say | Value |
| --- | --- |
| Skill name (store and console) | `4NextLuas` |
| Invocation name (spoken) | `four next luas` |

### Custom intents

| Intent | Slots | Purpose |
| --- | --- | --- |
| `NextTramIntent` | `station` (`LUAS_STATION`), optional `direction` (`LUAS_DIRECTION`) | Times at a stop, or at the favourite |
| `SetFavouriteStopIntent` | same | Save one favourite platform |
| `GetFavouriteStopIntent` | none | Read back the favourite |

Direction phrases, where they apply at that stop:

- Cardinal: northbound / southbound / eastbound / westbound
- City: towards the city (suburban stops only; city-centre stops elicit a terminus)
- Terminus: towards Broombridge, Brides Glen, Tallaght, Saggart, Connolly, The Point, Parnell, …

Green Line is roughly north–south; Red Line is roughly east–west. A wrong cardinal is rejected
with the two options that do apply. Forks (Belgard westbound is both Tallaght and Saggart on
one platform) are answered from that platform.

Dialog is `SKILL_RESPONSE`: Lambda elicits `station` or `direction` when needed.

## Data sources

- Realtime: `https://api.nationaltransport.ie/gtfsr/v2/TripUpdates` (header `x-api-key`), max 1 call / 60 s **per key**.
- Static timetable: `https://www.transportforireland.ie/transitData/Data/GTFS_Realtime.zip`, **route_type 0** (tram).
  Luas is in that same zip as Dublin Bus; 4NextBus filters it out, this skill keeps only tram rows.
  Do not ingest `GTFS_LUAS.zip` for production IDs — they must match GTFS-R v2.

## Local setup (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env   # then fill in NTA_API_KEY
.\.venv\Scripts\python tools\poc_next_luas.py Dundrum --direction northbound --no-realtime
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python tools\build_voice_model.py
```

If `pip` fails with `CERTIFICATE_VERIFY_FAILED`, bootstrap once with
`--trusted-host pypi.org --trusted-host files.pythonhosted.org --upgrade pip truststore`.

NTA only issues one GTFS-Realtime subscription per developer account. 4NextLuas
shares that key with live 4NextBus (and later 4NextDart / 4NextTrain). Before calling
NTA it claims the same DynamoDB lock item as the bus skill (`FourNextBus` `META/RTLOCK`),
so the combined skills stay at one TripUpdates call per 60 seconds. The loser uses a
cached feed if that Lambda container has one, otherwise timetable times (“scheduled”).
Set `NTA_LOCK_TABLE` if the bus table name is not `FourNextBus`.

## Deploying (first time)

Everything is driven by `tools/deploy.py` (boto3 only).

1. AWS credentials in `%USERPROFILE%\.aws\credentials`.
2. Put `ALEXA_SKILL_ID`, `ALERT_EMAIL` and `NTA_API_KEY` in `.env`.
3. `python tools/deploy.py all` creates the stack (`FourNextLuas` table, `FourNextLuas-Skill` Lambda,
   SSM `/4nextluas/nta_api_key`), then uploads the zip. It prints the Lambda ARN.
4. First timetable load: `python -m ingest.build_timetable` (Luas is a few dozen stops; minutes, not an hour).
5. Alexa console: paste `skill-package/interactionModels/custom/en-GB.json`, paste the Lambda ARN.
   Upload `skill-package/assets/images/en-GB_smallIcon.png` (108×108) and
   `en-GB_largeIcon.png` (512×512) under Distribution. Privacy policy:
   https://zarleyltd.github.io/4NextLuas/privacy.html (GitHub Pages from `docs/`).
6. `python tools/deploy.py test --station Dundrum --direction northbound`
7. Daily refresh: `python tools/deploy.py ingest-key` then add the printed keys as GitHub secrets.
   The workflow in `.github/workflows/ingest.yml` runs at **03:55 UTC** (after 4NextBus at 03:40).

Later code changes: `python tools/deploy.py code`.

Do not reuse the live 4NextBus skill ID.

## Free tier

Same shape as 4NextBus: Lambda, one provisioned DynamoDB table, CloudWatch Logs, SSM Parameter Store,
GitHub Actions for the daily timetable build.
