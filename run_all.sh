#!/bin/bash
# Generate, DRC, extract and LVS every cell.   usage: ./run_all.sh [pdk ...]
set -e
: "${PDK_ROOT:=$HOME/pdk}"
export PDK_ROOT
here=$(cd "$(dirname "$0")" && pwd)
pdks=${@:-gf180mcuD sky130A}
for pdk in $pdks; do
    python3 "$here/gen/gen.py" $pdk
    cd "$here/$pdk"
    rc=$PDK_ROOT/$pdk/libs.tech/magic/$pdk.magicrc
    setup=$PDK_ROOT/$pdk/libs.tech/netgen/${pdk}_setup.tcl
    : > summary.txt
    for c in BUF NOT AND NAND OR NOR XOR XNOR; do
        magic -dnull -noconsole -rcfile $rc "$here/scripts/drc_ext.tcl" $c > ${c}_magic.log 2>&1
        drc=$(grep -m1 DRC_TOTAL ${c}_magic.log | awk '{print $2}')
        netgen -batch lvs "${c}_lvs.spice $c" "${c}_ref.spice $c" $setup ${c}_lvs.txt > ${c}_netgen.log 2>&1 || true
        if grep -q 'Circuits match uniquely' ${c}_lvs.txt && ! grep -q 'Property errors' ${c}_lvs.txt; then lvs=match; else lvs=MISMATCH; fi
        printf "%-5s DRC %-4s LVS %s\n" $c "$drc" $lvs | tee -a summary.txt
    done
    cd "$here"
done
