import os
import json
import psycopg2
import boto3
import io
import csv
from flask import Flask, render_template, request, send_file
from datetime import datetime, timedelta, timezone

app = Flask(__name__)

# --- Secrets Manager ---
def get_db_credentials(secret_name):
    region = os.environ.get("AWS_REGION", "ap-southeast-1")
    sm = boto3.client("secretsmanager", region_name=region)
    resp = sm.get_secret_value(SecretId=secret_name)
    return json.loads(resp["SecretString"])

# --- DB Connection ---
def get_connection():
    creds = get_db_credentials(os.environ["DB_SECRET_ID"])
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=creds["username"],
        password=creds["password"],
        sslmode=os.environ.get("DB_SSLMODE", "require"),
    )

# --- Query Results ---
def query_results(hours=5):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    table = os.environ.get("TABLE_NAME", "github_status_runs")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT executed_at, overall_description, overall_indicator,
               components, incidents, maintenances
        FROM {table}
        WHERE executed_at >= %s
        ORDER BY executed_at DESC
    """, (cutoff,))
    rows = []
    tz_gmt8 = timezone(timedelta(hours=8))
    for r in cur.fetchall():
        executed_at_utc = r[0]
        executed_at_local = executed_at_utc.astimezone(tz_gmt8)
        rows.append({
            "executed_at": executed_at_local.strftime("%Y-%m-%d %H:%M:%S GMT+8"),
            "description": r[1],
            "indicator": r[2],
            "components": r[3],
            "incidents": r[4],
            "maintenances": r[5],
        })
    cur.close()
    conn.close()
    return rows

# --- Routes ---
@app.route("/")
def index():
    hours = int(request.args.get("hours", "5"))
    results = query_results(hours)
    return render_template("index.html", results=results, hours=hours)

@app.route("/download")
def download_csv():
    hours = int(request.args.get("hours", "5"))
    results = query_results(hours)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "executed_at","description","indicator",
        "components","incidents","maintenances"
    ])
    for r in results:
        writer.writerow([
            r["executed_at"], r["description"], r["indicator"],
            json.dumps(r["components"]), json.dumps(r["incidents"]), json.dumps(r["maintenances"])
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"github_status_{hours}h.csv"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
