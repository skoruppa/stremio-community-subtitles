#!/bin/bash

export FLASK_ENV=development
export FLASK_DEBUG=1

# FLASK_RUN_HOST and FLASK_RUN_PORT are loaded from .env by run.py
python run.py
