#!/usr/bin/env bash
# Map-error injection: take a perfect grid, add controlled synthetic error, and
# find which property of the error the filter actually cares about.
#
# Comparing whole representations confounds many properties at once. Here the
# base map is the exact truth grid, so injected error is the only difference,
# and it is swept one axis at a time: amplitude, spatial scale, anisotropy.
set -uo pipefail

BIN=${BIN:-./build/terrain_nav}
SEEDS=${SEEDS:-$(seq 1 12)}
[[ -x "$BIN" ]] || { echo "error: $BIN not found — build first" >&2; exit 1; }

# Due east, so "along x" is unambiguously along-track for the anisotropy sweep.
WORLD="--dem-size 1000 --dem-spacing 30 --relief 2500 --terrain ridged"
FLIGHT="--filter rbpf --heading 0 --start 3000,15000 --duration 180 --quiet"

cell() {   # error args... -> "median diverged worst"
    local vals=""
    for s in $SEEDS; do
        vals="$vals $("$BIN" $WORLD "$@" $FLIGHT --seed "$s" \
                      | awk '/terrain-aided final error/{print $4}')"
    done
    echo "$vals" | tr ' ' '\n' | grep -v '^$' | sort -n > /tmp/ei.txt
    local n med div worst
    n=$(wc -l < /tmp/ei.txt)
    med=$(awk -v n="$n" '{a[NR]=$1} END{printf "%.1f", (n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2}' /tmp/ei.txt)
    div=$(awk '$1>300' /tmp/ei.txt | wc -l)
    worst=$(tail -1 /tmp/ei.txt)
    printf "%s %s/%s %s" "$med" "$div" "$n" "$worst"
}

hdr() { printf "%-16s %10s %10s %10s %10s\n" "$1" "map RMSE" "nav median" "diverged" "nav worst";
        printf -- "------------------------------------------------------------\n"; }
rms() { "$BIN" $WORLD "$@" --map-rmse | awk '/elevation RMSE/{printf "%.1f", $3}'; }

echo "Base: exact 1000x1000 grid @ 30 m, ridged, 2500 m relief"
echo "Flight: due east, 180 s, marginalised filter, no gradient inflation"
echo "Seeds per cell: $(echo $SEEDS | wc -w).  'diverged' = final error > 300 m."
echo

echo "== 1. AMPLITUDE (lambda 500 m, isotropic) — how much error can it absorb? =="
hdr "amplitude"
for a in 0 5 10 20 40 80; do
    if [[ "$a" == 0 ]]; then
        printf "%-16s %10s %10s %10s %10s\n" "0 m (control)" "0.0" $(cell --error-amplitude 0)
    else
        printf "%-16s %10s %10s %10s %10s\n" "${a} m" \
            "$(rms --error-amplitude $a --error-wavelength 500)" \
            $(cell --error-amplitude $a --error-wavelength 500)
    fi
done

echo
echo "== 2. SPATIAL SCALE (amplitude 20 m, isotropic) — misplaced hills or fake boulders? =="
hdr "wavelength"
for w in 100 250 500 1000 2500 5000; do
    printf "%-16s %10s %10s %10s %10s\n" "${w} m" \
        "$(rms --error-amplitude 20 --error-wavelength $w)" \
        $(cell --error-amplitude 20 --error-wavelength $w)
done

echo
echo "== 3. ISOTROPY (amplitude 20 m, lambda 500 m) — along-track vs cross-track =="
hdr "aspect"
for r in 0.125 0.25 0.5 1 2 4 8; do
    case "$r" in
        0.125|0.25|0.5) tag="cross-track" ;;
        1)              tag="isotropic"   ;;
        *)              tag="along-track" ;;
    esac
    printf "%-16s %10s %10s %10s %10s\n" "${r}x  ${tag}" \
        "$(rms --error-amplitude 20 --error-wavelength 500 --error-aspect $r)" \
        $(cell --error-amplitude 20 --error-wavelength 500 --error-aspect $r)
done
