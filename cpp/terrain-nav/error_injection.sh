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
# Realisations of the injected error field. Varying only --seed changes sensor
# noise, the true INS bias and the start offset -- NOT the error field, which
# stays at its default. Sweeping wavelength against a single realisation
# measures that one field's quirks, not the effect of wavelength.
ERROR_SEEDS=${ERROR_SEEDS:-11 12 13 14 15 16 17 18}
[[ -x "$BIN" ]] || { echo "error: $BIN not found — build first" >&2; exit 1; }

# Due east, so "along x" is unambiguously along-track for the anisotropy sweep.
WORLD="--dem-size 1000 --dem-spacing 30 --relief 2500 --terrain ridged"
FLIGHT="--filter rbpf --heading 0 --start 3000,15000 --duration 180 --quiet"

cell() {   # error args... -> "median diverged worst"
    # A private temp file per call: a fixed /tmp path would collide between two
    # concurrent invocations of this script and is a symlink target in a shared
    # /tmp. mktemp gives a unique name and safe permissions.
    local tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/terrainnav.XXXXXX") || return 1
    local vals=""
    for es in $ERROR_SEEDS; do
        for s in $SEEDS; do
            vals="$vals $("$BIN" $WORLD "$@" --error-seed "$es" $FLIGHT --seed "$s" \
                          | awk '/terrain-aided final error/{print $4}')"
        done
    done
    echo "$vals" | tr ' ' '\n' | grep -v '^$' | sort -n > "$tmp"
    local n med div worst
    n=$(wc -l < "$tmp")
    med=$(awk -v n="$n" '{a[NR]=$1} END{printf "%.1f", (n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2}' "$tmp")
    div=$(awk '$1>300' "$tmp" | wc -l)
    worst=$(tail -1 "$tmp")
    rm -f "$tmp"
    printf "%s %s/%s %s" "$med" "$div" "$n" "$worst"
}

hdr() { printf "%-16s %10s %10s %10s %10s\n" "$1" "map RMSE" "nav median" "diverged" "nav worst";
        printf -- "------------------------------------------------------------\n"; }
rms() { "$BIN" $WORLD "$@" --map-rmse | awk '/elevation RMSE/{printf "%.1f", $3}'; }

echo "Base: exact 1000x1000 grid @ 30 m, ridged, 2500 m relief"
echo "Flight: due east, 180 s, marginalised filter, no gradient inflation"
echo "Per cell: $(echo $ERROR_SEEDS | wc -w) error-field realisations x $(echo $SEEDS | wc -w) flight seeds."
echo "'diverged' = final error > 300 m."
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
