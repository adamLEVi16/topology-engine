#!/usr/bin/env bash
# Phase 3: grid versus neural terrain map at equal storage.
#
# Holds the storage budget fixed and compares three representations of the same
# terrain: a decimated grid read with bilinear interpolation, the same grid read
# with bicubic interpolation, and a SIREN trained to the same byte count.
#
# The bicubic row is the point of the experiment. A coarse grid is not obliged to
# be stair-stepped -- bicubic gives it smooth, analytic gradients from the very
# same bytes -- so it, not bilinear, is the baseline a neural field has to beat.
#
# KNOWN LIMITATION: $SEEDS varies the flight only -- sensor noise, INS bias, start
# offset. The terrain is one realisation (--terrain-seed default) for every row.
# The equivalent confound in error_injection.sh, where the injected error field
# was likewise held fixed across everything called a seed, turned out to dominate
# the axis being swept, so do not read these medians as spanning terrains.
#
# Unlike that case it is not cheaply fixable: a different terrain needs a SIREN
# retrained against it, so pooling over terrains means retraining per seed. The
# grid rows could be pooled today; the neural rows could not, and pooling only
# half the table would be worse than pooling none of it.
set -uo pipefail

BIN=${BIN:-./build/terrain_nav}
SCRATCH=${SCRATCH:-/tmp}
SEEDS=${SEEDS:-1 2 3 4 5 6 7 8}
BASE="--dem-size 800 --dem-spacing 30 --relief 2500 --terrain ridged"
FLIGHT="--filter rbpf --gradient-inflation --duration 160 --start 1500,1500 --quiet"

[[ -x "$BIN" ]] || { echo "error: $BIN not found — build first" >&2; exit 1; }

# median of stdin
median() { sort -n | awk '{a[NR]=$1} END{ if(NR==0){print "n/a"} else if(NR%2){printf "%.1f", a[(NR+1)/2]} else {printf "%.1f", (a[NR/2]+a[NR/2+1])/2} }'; }

row() {   # label, map-args...
    local label="$1"; shift
    local fid nav_errs=() t

    fid=$("$BIN" $BASE "$@" --map-rmse)
    local erms grms
    erms=$(echo "$fid" | awk '/elevation RMSE/{printf "%.1f", $3}')
    grms=$(echo "$fid" | awk '/gradient RMSE/{printf "%.3f", $3}')
    t=$("$BIN" $BASE "$@" --bench-map 200000 | awk '/query cost/{printf "%.0f", $3}')

    for s in $SEEDS; do
        nav_errs+=("$("$BIN" $BASE "$@" $FLIGHT --seed "$s" \
                     | awk '/terrain-aided final error/{print $4}')")
    done
    local med
    med=$(printf '%s\n' "${nav_errs[@]}" | median)
    local worst
    worst=$(printf '%s\n' "${nav_errs[@]}" | sort -n | tail -1)

    printf "%-30s %9s m %10s %9s m %9.1f m %8s ns\n" \
        "$label" "$erms" "$grms" "$med" "$worst" "$t"
}

echo "Truth: 800x800 grid @ 30 m (2500 KiB), ridged terrain, ~42 deg mean slope"
echo "Filter: Rao-Blackwellised, gradient inflation on, ${SEEDS// /,} seeds"
echo
printf "%-30s %11s %10s %11s %11s %11s\n" \
    "REPRESENTATION" "ELEV RMSE" "GRAD RMSE" "NAV median" "NAV worst" "QUERY"
printf -- "------------------------------------------------------------------------------------------\n"

echo "-- budget A: ~39 KiB ------------------------------------------------------------------------"
row "grid 8x, bilinear  (39 KiB)" --map-downsample 8  --map-interp bilinear
row "grid 8x, bicubic   (39 KiB)" --map-downsample 8  --map-interp bicubic
[[ -f "$SCRATCH/siren_33k.siren" ]] && \
    row "SIREN 64x3        (34 KiB)" --neural "$SCRATCH/siren_33k.siren"

echo "-- budget B: ~10 KiB ------------------------------------------------------------------------"
row "grid 16x, bilinear (10 KiB)" --map-downsample 16 --map-interp bilinear
row "grid 16x, bicubic  (10 KiB)" --map-downsample 16 --map-interp bicubic
[[ -f "$SCRATCH/siren_10k.siren" ]] && \
    row "SIREN 48x2        (10 KiB)" --neural "$SCRATCH/siren_10k.siren"

echo "-- reference --------------------------------------------------------------------------------"
row "exact grid        (2500 KiB)" --map-downsample 1 --map-interp bilinear
