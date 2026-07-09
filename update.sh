#!/bin/bash

set -e
cd ~/python/OpenPrintTagDatabase-Color-Search-SQL/openprinttag-database
git pull
cd ~/python/OpenPrintTagDatabase-Color-Search-SQL
.venv/bin/python build_db.py
sudo systemctl restart optd_sql.service
