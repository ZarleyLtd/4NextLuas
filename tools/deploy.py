"""Deploy 4NextLuas to AWS using boto3 only (no AWS CLI, no SAM, no S3 bucket).

  python tools/deploy.py stack --skill-id amzn1.ask.skill.xxx --email you@example.com
  python tools/deploy.py key            # store NTA_API_KEY from .env as an SSM SecureString
  python tools/deploy.py code           # build the Lambda zip and upload it directly
  python tools/deploy.py ingest-key     # create an access key for the GitHub Actions user (printed once)
  python tools/deploy.py all --skill-id ... --email ...

Credentials: standard boto3 resolution (AWS_PROFILE / ~/.aws/credentials / env vars).
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
REGION = os.environ.get("AWS_REGION", "eu-west-1")
STACK = os.environ.get("FOURNEXTLUAS_STACK", "FourNextLuas")
TABLE = os.environ.get("FOURNEXTLUAS_TABLE", "FourNextLuas")
FUNCTION = os.environ.get("FOURNEXTLUAS_FUNCTION", "FourNextLuas-Skill")
PARAM = os.environ.get("NTA_API_KEY_PARAM", "/4nextluas/nta_api_key")
LOCK_TABLE = os.environ.get("NTA_LOCK_TABLE", "FourNextBus")
LAMBDA_PY = "3.13"


def session():
    return boto3.session.Session(region_name=REGION)


# ---- stack -------------------------------------------------------------------------------

def deploy_stack(skill_id: str, email: str, reserved: str) -> None:
    cfn = session().client("cloudformation")
    template = (ROOT / "template.yaml").read_text(encoding="utf-8")
    ids = [s.strip() for s in skill_id.split(",") if s.strip()]
    if not 1 <= len(ids) <= 2:
        sys.exit("--skill-id takes one or two comma-separated skill IDs")
    params = [
        {"ParameterKey": "SkillId", "ParameterValue": ids[0]},
        {"ParameterKey": "SecondSkillId", "ParameterValue": ids[1] if len(ids) > 1 else ""},
        {"ParameterKey": "AlertEmail", "ParameterValue": email},
        {"ParameterKey": "TableName", "ParameterValue": TABLE},
        {"ParameterKey": "FunctionName", "ParameterValue": FUNCTION},
        {"ParameterKey": "NtaKeyParameterName", "ParameterValue": PARAM},
        {"ParameterKey": "NtaLockTable", "ParameterValue": LOCK_TABLE},
        {"ParameterKey": "ReservedConcurrency", "ParameterValue": reserved},
    ]
    kwargs = dict(StackName=STACK, TemplateBody=template, Parameters=params,
                  Capabilities=["CAPABILITY_NAMED_IAM"])
    try:
        cfn.describe_stacks(StackName=STACK)
        exists = True
    except ClientError:
        exists = False
    try:
        if exists:
            print(f"updating stack {STACK} ...")
            cfn.update_stack(**kwargs)
            waiter = cfn.get_waiter("stack_update_complete")
        else:
            print(f"creating stack {STACK} ...")
            cfn.create_stack(**kwargs, OnFailure="DELETE")
            waiter = cfn.get_waiter("stack_create_complete")
    except ClientError as exc:
        if "No updates are to be performed" in str(exc):
            print("stack already up to date")
            return
        raise
    try:
        waiter.wait(StackName=STACK, WaiterConfig={"Delay": 10, "MaxAttempts": 90})
    except Exception:
        _print_stack_failures(cfn, STACK)
        raise
    outputs = cfn.describe_stacks(StackName=STACK)["Stacks"][0].get("Outputs", [])
    print("stack ready:")
    for o in outputs:
        print(f"  {o['OutputKey']}: {o['OutputValue']}")


def _print_stack_failures(cfn, stack_name: str) -> None:
    try:
        events = cfn.describe_events(StackName=stack_name, Filters={"FailedEvents": True})
    except Exception as exc:
        print(f"could not load stack failure details: {exc}")
        return
    print("stack failure details:")
    for ev in events.get("OperationEvents", []):
        reason = ev.get("ValidationStatusReason") or ev.get("ResourceStatusReason") or ""
        name = ev.get("ValidationName") or ev.get("EventType") or ""
        print(f"  {ev.get('LogicalResourceId')} {ev.get('ResourceType')} {name}: {reason}")


# ---- NTA key -----------------------------------------------------------------------------

def put_key() -> None:
    key = os.environ.get("NTA_API_KEY", "").strip()
    if not key:
        key = input("NTA API key: ").strip()
    ssm = session().client("ssm")
    ssm.put_parameter(Name=PARAM, Value=key, Type="SecureString", Overwrite=True,
                      Description="4NextLuas NTA GTFS-R subscription key")
    print(f"stored {PARAM} ({key[:4]}...{key[-4:]})")


# ---- code --------------------------------------------------------------------------------

def build_zip() -> bytes:
    build = ROOT / "build" / "lambda"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    print("installing runtime dependencies for Lambda (manylinux, python", LAMBDA_PY, ") ...")
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt"),
           "--target", str(build), "--platform", "manylinux2014_x86_64", "--implementation", "cp",
           "--python-version", LAMBDA_PY, "--only-binary=:all:", "--upgrade"]
    subprocess.run(cmd, check=True)
    # boto3/botocore come with the Lambda runtime; drop them if a dependency pulled them in.
    for junk in ["boto3", "botocore", "s3transfer", "bin", "__pycache__"]:
        p = build / junk
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for dist in build.glob("*.dist-info"):
        if dist.name.split("-")[0] in ("boto3", "botocore", "s3transfer"):
            shutil.rmtree(dist, ignore_errors=True)
    shutil.copytree(ROOT / "src", build / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(build.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                info = zipfile.ZipInfo(path.relative_to(build).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, path.read_bytes())
    data = buf.getvalue()
    (ROOT / "build" / "lambda.zip").write_bytes(data)
    print(f"built build/lambda.zip: {len(data)/1e6:.1f} MB")
    return data


def deploy_code() -> None:
    data = build_zip()
    lam = session().client("lambda")
    print(f"uploading to {FUNCTION} ...")
    lam.update_function_code(FunctionName=FUNCTION, ZipFile=data, Publish=False)
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    cfg = lam.get_function_configuration(FunctionName=FUNCTION)
    print(f"deployed: {cfg['FunctionArn']} runtime={cfg['Runtime']} size={cfg['CodeSize']/1e6:.1f} MB "
          f"state={cfg['State']} lastUpdate={cfg['LastUpdateStatus']}")


# ---- ingest user key ---------------------------------------------------------------------

def create_ingest_key() -> None:
    iam = session().client("iam")
    user = f"{TABLE}-ingest"
    existing = iam.list_access_keys(UserName=user)["AccessKeyMetadata"]
    if len(existing) >= 2:
        sys.exit(f"{user} already has 2 access keys; delete one in the IAM console first.")
    key = iam.create_access_key(UserName=user)["AccessKey"]
    print("Add these to the GitHub repository secrets (shown once):")
    print(f"  AWS_ACCESS_KEY_ID     = {key['AccessKeyId']}")
    print(f"  AWS_SECRET_ACCESS_KEY = {key['SecretAccessKey']}")


# ---- smoke test --------------------------------------------------------------------------

def invoke_test(station: str, direction: str = "northbound") -> None:
    import json
    lam = session().client("lambda")
    app_id = os.environ.get("ALEXA_SKILL_ID", "test").split(",")[0].strip()
    event = {
        "version": "1.0",
        "session": {"new": True, "sessionId": "s", "application": {"applicationId": app_id},
                    "user": {"userId": "amzn1.ask.account.DEPLOYTEST"}},
        "context": {"System": {"application": {"applicationId": app_id},
                               "user": {"userId": "amzn1.ask.account.DEPLOYTEST"},
                               "device": {"deviceId": "d", "supportedInterfaces": {}}}},
        "request": {"type": "IntentRequest", "requestId": "r", "locale": "en-GB",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "intent": {"name": "NextTramIntent", "confirmationStatus": "NONE",
                               "slots": {
                                   "station": {"name": "station", "value": station},
                                   "direction": {"name": "direction", "value": direction},
                               }}},
    }
    t0 = time.perf_counter()
    resp = lam.invoke(FunctionName=FUNCTION, Payload=json.dumps(event).encode())
    body = json.loads(resp["Payload"].read())
    print(f"{time.perf_counter()-t0:.2f}s ->", json.dumps(body.get("response", body), indent=2)[:1500])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["stack", "key", "code", "ingest-key", "test", "all"])
    ap.add_argument("--skill-id", default=os.environ.get("ALEXA_SKILL_ID"))
    ap.add_argument("--email", default=os.environ.get("ALERT_EMAIL"))
    ap.add_argument("--reserved-concurrency", default="none",
                    help='reserved concurrency for the skill Lambda (default "none")')
    ap.add_argument("--station", default="Dundrum", help="station name for the test invocation")
    ap.add_argument("--direction", default="northbound", help="direction for the test invocation")
    args = ap.parse_args()

    if args.action in ("stack", "all"):
        if not args.skill_id or not args.email:
            sys.exit("--skill-id and --email are required for the stack (or set ALEXA_SKILL_ID / ALERT_EMAIL in .env)")
        deploy_stack(args.skill_id, args.email, args.reserved_concurrency)
    if args.action in ("key", "all"):
        put_key()
    if args.action in ("code", "all"):
        deploy_code()
    if args.action == "ingest-key":
        create_ingest_key()
    if args.action == "test":
        invoke_test(args.station, args.direction)


if __name__ == "__main__":
    main()
