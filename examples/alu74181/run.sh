#!/bin/bash
# Build and check the ALU181 (74181) example.   usage: ./run.sh [pdk ...]
# Needs the library cells first: ../../run_all.sh (the preview uses their masks).
set -e
: "${PDK_ROOT:=$HOME/pdk}"
export PDK_ROOT
here=$(cd "$(dirname "$0")" && pwd)
for pdk in ${@:-gf180mcuD sky130A}; do
    python3 "$here/alu181_netlist.py"
    python3 "$here/make_alu181.py" $pdk
    cd "$here/$pdk"
    magic -dnull -noconsole -rcfile $PDK_ROOT/$pdk/libs.tech/magic/$pdk.magicrc \
        "$here/../../scripts/drc_ext.tcl" ALU181 > ALU181_magic.log 2>&1
    netgen -batch lvs "ALU181_lvs.spice ALU181" "ALU181_ref.spice ALU181" \
        $PDK_ROOT/$pdk/libs.tech/netgen/${pdk}_setup.tcl ALU181_lvs.txt > ALU181_netgen.log 2>&1 || true
    drc=$(grep -m1 DRC_TOTAL ALU181_magic.log | awk '{print $2}')
    if grep -q 'Circuits match uniquely' ALU181_lvs.txt && ! grep -q 'Property errors' ALU181_lvs.txt
    then lvs=match; else lvs=MISMATCH; fi
    echo "$pdk ALU181  DRC $drc  LVS $lvs" | tee summary.txt
    python3 "$here/sim_alu181.py" $pdk | tee -a summary.txt
    rm -f AND.ext OR.ext XOR.ext NAND.ext NOR.ext NOT.ext
    cd "$here"
done
