#!/bin/bash

export FLASK_ENV=production

gunicorn -c gunicorn_config.py wsgi:app
