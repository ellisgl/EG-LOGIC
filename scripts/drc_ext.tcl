# usage: magic -dnull -noconsole -rcfile <pdk magicrc> drc_ext.tcl <CELL>
set cell [lindex $argv end]
load $cell
select top cell
drc euclidean on
drc style drc(full)
drc check
drc catchup
set n [drc list count total]
puts "DRC_TOTAL $n"
foreach {why boxes} [drc listall why] {
    puts "DRC_ERR [llength $boxes] :: $why"
    foreach b [lrange $boxes 0 2] { puts "   at: $b" }
}
extract do local
extract all
ext2spice lvs
ext2spice -o ${cell}_lvs.spice
ext2spice cthresh 0
ext2spice -o ${cell}.spice
gds write ${cell}.gds
quit -noprompt
