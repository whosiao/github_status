import os, json, logging, socket
from datetime import datetime, timezone

import boto3
import psycopg2
from psycopg2.extras import Json
import urllib3
from urllib3.util import Timeout

GITHUB_SUMMARY_URL = "https://www.githubstatus.com/api/v2/summary.json"
GITHUB_INCIDENTS_URL = "https://www.githubstatus.com/api/v2/incidents.json"
GITHUB_MAINTENANCE_URL = "https://www.githubstatus.com/api/v2/scheduled-maintenances.json"

DB_SECRET_ID = os.environ.get("DB_SECRET_ID")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME")
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require")
TABLE_NAME = os.environ.get("TABLE_NAME", "github_status_runs")

HTTP = urllib3.PoolManager(num_pools=4)
HTTP_TIMEOUT = Timeout(connect=5.0, read=10.0)
HTTP_HEADERS = {"User-Agent": "github-status-lambda/1.0"}

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_db_creds():
    if not DB_SECRET_ID:
        raise RuntimeError("Missing env var DB_SECRET_ID")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-1"
    sm = boto3.client("secretsmanager", region_name=region)
    logger.info("Fetching DB creds from Secrets Manager: %s", DB_SECRET_ID)
    resp = sm.get_secret_value(SecretId=DB_SECRET_ID)
    data = json.loads(resp["SecretString"])
    username = data.get("username") or data.get("user")
    password = data.get("password") or data.get("pwd") or data.get("passwd")
    if not username or not password:
        raise RuntimeError("Secret must contain 'username' and 'password'")
    return username, password

def tcp_probe(host, port, timeout=5):
    addrs = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    logger.info("Resolved %s to: %s", host, [a[4][0] for a in addrs])
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.close()
    logger.info("TCP probe OK")

def connect_db(username, password):
    if not DB_HOST or not DB_NAME:
        raise RuntimeError("Missing DB_HOST or DB_NAME")
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=username,
        password=password,
        dbname=DB_NAME,
        connect_timeout=5,
        sslmode=DB_SSLMODE,
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            row = cur.fetchone()
            logger.info("DB SELECT 1 -> %s", row)
    return conn

def fetch_json(url: str) -> dict:
    r = HTTP.request("GET", url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT, retries=False)
    logger.info("%s -> HTTP %s", url, r.status)
    if r.status < 200 or r.status >= 300:
        raise RuntimeError(f"HTTP {r.status} fetching {url}: {r.data[:200]!r}")
    return json.loads(r.data.decode("utf-8"))

def fetch_github_status():
    summary = fetch_json(GITHUB_SUMMARY_URL)
    incidents_all = fetch_json(GITHUB_INCIDENTS_URL).get("incidents", [])
    maints_all = fetch_json(GITHUB_MAINTENANCE_URL).get("scheduled_maintenances", [])

    overall_indicator = summary["status"]["indicator"]
    overall_description = summary["status"]["description"]

    components = [
        {"name": c.get("name"), "status": c.get("status")}
        for c in summary.get("components", [])
        if c.get("name") is not None and c.get("status") is not None
    ]

    def sort_key(x):
        return x.get("updated_at") or x.get("created_at") or ""

    incidents = [
        {"impact": i.get("impact"), "name": i.get("name"), "status": i.get("status")}
        for i in sorted(incidents_all, key=sort_key, reverse=True)[:10]
    ]
    maintenances = [
        {"impact": m.get("impact"), "name": m.get("name"), "status": m.get("status")}
        for m in sorted(maints_all, key=sort_key, reverse=True)[:10]
    ]
    logger.info("Parsed summary: components=%d incidents=%d maintenances=%d",
                len(components), len(incidents), len(maintenances))
    return overall_description, overall_indicator, components, incidents, maintenances

def insert_run(conn, overall_description, overall_indicator, components, incidents, maintenances):
    sql = f"""
        INSERT INTO {TABLE_NAME} (
          overall_description, overall_indicator, components, incidents, maintenances
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING run_id, executed_at
    """
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                overall_description,
                overall_indicator,
                Json(components),
                Json(incidents),
                Json(maintenances),
            ))
            run_id, executed_at = cur.fetchone()
            logger.info("Inserted run_id=%s executed_at=%s", run_id, executed_at)
            return str(run_id), executed_at

def lambda_handler(event, context):
    try:
        logger.info("=== START github status poll ===")
        username, password = get_db_creds()
        tcp_probe(DB_HOST, DB_PORT, timeout=5)
        conn = connect_db(username, password)
        od, oi, comps, incs, maints = fetch_github_status()
        run_id, executed_at = insert_run(conn, od, oi, comps, incs, maints)
        conn.close()
        logger.info("=== DONE run_id=%s ===", run_id)
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "ok", "run_id": run_id, "executed_at": executed_at.isoformat()})
        }
    except Exception as e:
        logger.exception("FAILED: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
