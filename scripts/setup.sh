#!/bin/sh
# `make setup` — install everything with `uv sync`, Pegasus included.
#
# Pegasus (lbg-pegasus) comes from SAR, which needs your SAR token. Put it in env/.env,
# next to your other settings (the same token you'd put in pip.conf):
#     SAR_TOKEN_NAME=<USER_TOKEN_NAME>
#     SAR_TOKEN_PASS_CODE=<USER_TOKEN_PASS_CODE>
# This script hands them to uv for this one command only; they are never written anywhere else.
#
# No token or no SAR access? Everything else is still installed; Pegasus metrics then run on
# DeepEval and every result says which engine scored it.

set -u

# 1. env/.env: create it from the example on the first run.
if [ ! -f env/.env ]; then
    cp env/.env.example env/.env
    echo "Created env/.env - fill in your values (SAR token for Pegasus, CORTEX, agent URLs)."
fi

# 2. Read one value from env/.env (the last "NAME=" line, like other env loaders), without quotes
#    or a trailing " # comment".
env_value() {
    sed -n "s/^$1=//p" env/.env | tail -n 1 | sed 's/[[:space:]][[:space:]]*#.*$//; s/^["'\'']//; s/["'\'']$//; s/[[:space:]]*$//'
}

# 3. uv reads the credentials of the index named "lbg-pegasus" (pyproject.toml) from these two variables.
#    A value already set in your shell wins.
: "${UV_INDEX_LBG_PEGASUS_USERNAME:=$(env_value SAR_TOKEN_NAME)}"
: "${UV_INDEX_LBG_PEGASUS_PASSWORD:=$(env_value SAR_TOKEN_PASS_CODE)}"
export UV_INDEX_LBG_PEGASUS_USERNAME UV_INDEX_LBG_PEGASUS_PASSWORD

# 4. Install. --inexact: never remove packages that are already installed.
if [ -n "$UV_INDEX_LBG_PEGASUS_USERNAME" ] && uv sync --inexact --group pegasus; then
    echo "Installed everything, including Pegasus."
    exit 0
fi

echo ""
if [ -z "$UV_INDEX_LBG_PEGASUS_USERNAME" ]; then
    echo "NOTE: no SAR token in env/.env (SAR_TOKEN_NAME / SAR_TOKEN_PASS_CODE), so Pegasus is skipped."
else
    echo "WARNING: Pegasus could not be installed - check the SAR token in env/.env and your network."
fi
echo "Installing everything else. Pegasus metrics run on DeepEval until you add the token and run make setup again."
echo ""
uv sync --inexact --frozen
