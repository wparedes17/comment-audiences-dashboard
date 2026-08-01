#!/bin/sh
set -e

python -m dashboard_sentiment.wait_for_db
python -m dashboard_sentiment.verify_schema

exec gunicorn -b 0.0.0.0:8080 "dashboard_sentiment.app:create_app()"
