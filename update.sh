#!/bin/bash

set -e
cd ~/python/filamentsearch/openprinttag-database
git pull
cd ~/python/filamentsearch
.venv/bin/python build_db.py
sudo service optdsearch_ciede2000 restart
