#!/usr/bin/env bash
# Build units, run the judge, and assemble for one prompt version on a fixed key set.
#   scripts/judge/iterate.sh <version> [passes]     e.g. scripts/judge/iterate.sh v2 A,B1,B2
set -euo pipefail
V=$1; PASSES=${2:-A,B1,B2}
ROOT=$(pwd)/logs/12-judge/pilot10
R=$ROOT/$V
uv run python scripts/judge/build_units.py logs/03-pilot/v4flash/promptB-5att --keys $ROOT/keys.txt --passes $PASSES --out $R
uv run inspect eval src/earh/judge/task.py@judge -T units=$R/judge_units.jsonl \
  --model deepinfra-raw/glm53flash -M reasoning_effort=${EFFORT:-high} --max-connections 60 \
  --log-dir $R/logs --display plain > $R/run.out 2>&1 || { tail -20 $R/run.out; exit 1; }
grep -E "valid |mean " $R/run.out | tail -2
uv run python scripts/judge/assemble.py $R
