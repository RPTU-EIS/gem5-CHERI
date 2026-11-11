#!/bin/sh
# Run the tag-validation workloads (tagval/build.py: MiBench, Octane under
# Duktape, FFmpeg) with the Olden runner, results under RESULTS/tagval/.
# The MiBench workloads ship input files, so runs boot CheriBSD themselves
# (NO_CHECKPOINT=1, as holygrail.sh sets anyway).
#
# Usage: util/cheri/tagval/run_all.sh RESULTS [TAG]
# Environment: as util/cheri/olden/run_all.sh; WORK default
#   ~/hiwi/tagval-gem5
set -eu
export SUITE_NAME=tagval NO_CHECKPOINT=1
export WORK=${WORK:-$HOME/hiwi/tagval-gem5}
exec "$(dirname "$0")/../olden/run_all.sh" "$@"
