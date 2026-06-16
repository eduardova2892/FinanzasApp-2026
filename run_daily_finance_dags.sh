#!/bin/bash

cd "/mnt/c/Users/eduar/OneDrive/Documents/01_EduPC_Legion/04 AppMyFinances"

source airflow_venv/bin/activate

export AIRFLOW_HOME=~/airflow
export FINANZAS_APP_HOME="$(pwd)"

airflow dags test daily_usd_pen_finanzas "$(date +%F)"
airflow dags test exchange_rate_bcrp "$(date +%F)"
airflow dags test exchange_rate_bcp "$(date +%F)"
airflow dags test market_prices_ibkr_portfolio "$(date +%F)"
