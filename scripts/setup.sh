#!/bin/sh
# `make setup` — install everything with `uv sync`, including the two internal packages from SAR:
#   Pegasus (lbg-pegasus)             the team's standard judge metrics
#   CorteX DevKit (cortex-devkit)     sign in to CORTEX with SSO instead of an API key (CORTEX_AUTH=devkit)
#
# SAR needs your SAR token. Put it in env/.env, next to your other settings
# (the same token you'd put in pip.conf):
#     SAR_TOKEN_NAME=<USER_TOKEN_NAME>
#     SAR_TOKEN_PASS_CODE=<USER_TOKEN_PASS_CODE>
# This script hands them to uv for this one command only; they are never written anywhere else.
#
# No token or no SAR access? Everything else is still installed; Pegasus metrics then run on
# DeepEval (every result says which engine scored it) and CORTEX is reached with the API key.

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

# 3. The same SAR token opens both internal indexes in pyproject.toml. uv reads each index's
#    credentials from UV_INDEX_<INDEX NAME>_USERNAME / _PASSWORD. A value already set in your shell wins.
SAR_USER="$(env_value SAR_TOKEN_NAME)"
SAR_PASS="$(env_value SAR_TOKEN_PASS_CODE)"
: "${UV_INDEX_LBG_PEGASUS_USERNAME:=$SAR_USER}"         # lbg-pegasus         -> Pegasus
: "${UV_INDEX_LBG_PEGASUS_PASSWORD:=$SAR_PASS}"
: "${UV_INDEX_INNERSOURCE_GENTEX_USERNAME:=$SAR_USER}"  # innersource-gentex  -> CorteX DevKit
: "${UV_INDEX_INNERSOURCE_GENTEX_PASSWORD:=$SAR_PASS}"
export UV_INDEX_LBG_PEGASUS_USERNAME UV_INDEX_LBG_PEGASUS_PASSWORD
export UV_INDEX_INNERSOURCE_GENTEX_USERNAME UV_INDEX_INNERSOURCE_GENTEX_PASSWORD

# 4. Install. --inexact: never remove packages that are already installed.
#    Try Pegasus + DevKit together, then each on its own, then neither — so one internal package
#    that can't be reached never blocks the rest.
if [ -n "$SAR_USER" ]; then
    for groups in "--group pegasus --group devkit" "--group pegasus" "--group devkit"; do
        # shellcheck disable=SC2086  # $groups is meant to split into separate arguments
        if uv sync --inexact $groups; then
            echo ""
            case "$groups" in
                *pegasus*devkit*) echo "Installed everything, including Pegasus and the CorteX DevKit." ;;
                *pegasus*)        echo "Installed everything and Pegasus. The CorteX DevKit could not be installed." ;;
                *)                echo "Installed everything and the CorteX DevKit. Pegasus could not be installed." ;;
            esac
            exit 0
        fi
    done
    echo ""
    echo "WARNING: Pegasus and the CorteX DevKit could not be installed - check the SAR token in env/.env"
    echo "and your network (the lines above say which)."
else
    echo ""
    echo "NOTE: no SAR token in env/.env (SAR_TOKEN_NAME / SAR_TOKEN_PASS_CODE), so Pegasus and the"
    echo "CorteX DevKit are skipped."
fi
echo "Installing everything else. Pegasus metrics run on DeepEval, and CORTEX_AUTH must stay api_key,"
echo "until you add the token and run make setup again."
echo ""
uv sync --inexact --frozen
