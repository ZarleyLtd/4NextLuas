"""Runtime configuration for the Lambda (env vars + SSM for the secret)."""
from __future__ import annotations

import os
from functools import lru_cache


TABLE_NAME = os.environ.get("FOURNEXTLUAS_TABLE", "FourNextLuas")
# Shared NTA TripUpdates lock. Default is the live bus table so one key is
# 1 call / 60s across 4NextBus, 4NextTram, and later Dart/Train siblings.
LOCK_TABLE = os.environ.get("NTA_LOCK_TABLE", "FourNextBus")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "eu-west-1"
# Comma-separated list of Alexa skill IDs allowed to invoke the handler (empty = no check).
SKILL_IDS = frozenset(s.strip() for s in os.environ.get("ALEXA_SKILL_ID", "").split(",") if s.strip())
NTA_KEY_PARAM = os.environ.get("NTA_API_KEY_PARAM", "/4nextluas/nta_api_key")


@lru_cache(maxsize=1)
def nta_api_key() -> str:
    """Prefer an explicit env var (local dev/tests); otherwise read the SSM SecureString once."""
    direct = os.environ.get("NTA_API_KEY", "").strip()
    if direct:
        return direct
    import boto3
    ssm = boto3.client("ssm", region_name=REGION)
    return ssm.get_parameter(Name=NTA_KEY_PARAM, WithDecryption=True)["Parameter"]["Value"].strip()
