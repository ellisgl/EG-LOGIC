#!/bin/bash
# Build and check the ADD4 example.   usage: ./run.sh [pdk ...]
# Needs the library cells first: ../../run_all.sh (the preview uses their masks).
set -e
: "${PDK_ROOT:=$HOME/pdk}"
export PDK_ROOT
here=$(cd "$(dirname "$0")" && pwd)
for pdk in ${@:-gf180mcuD sky130A}; do
    python3 "$here/make_adder4.py" $pdk
    cd "$here/$pdk"
    magic -dnull -noconsole -rcfile $PDK_ROOT/$pdk/libs.tech/magic/$pdk.magicrc \
        "$here/../../scripts/drc_ext.tcl" ADD4 > ADD4_magic.log 2>&1
    netgen -batch lvs "ADD4_lvs.spice ADD4" "ADD4_ref.spice ADD4" \
        $PDK_ROOT/$pdk/libs.tech/netgen/${pdk}_setup.tcl ADD4_lvs.txt > ADD4_netgen.log 2>&1 || true
    drc=$(grep -m1 DRC_TOTAL ADD4_magic.log | awk '{print $2}')
    if grep -q 'Circuits match uniquely' ADD4_lvs.txt && ! grep -q 'Property errors' ADD4_lvs.txt
    then lvs=match; else lvs=MISMATCH; fi
    echo "$pdk ADD4  DRC $drc  LVS $lvs" | tee summary.txt
    python3 "$here/sim_adder4.py" $pdk | tee -a summary.txt
    rm -f AND.ext OR.ext XOR.ext
    cd "$here"
done
