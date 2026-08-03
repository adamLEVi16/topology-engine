#!/usr/bin/env bash
# Behavioural checks for the terrain-referenced navigation filter.
#   cmake -S . -B build && cmake --build build -j && ./validate.sh
set -uo pipefail

BIN=${BIN:-./build/terrain_nav}
if [[ ! -x "$BIN" ]]; then
    echo "error: $BIN not found — build first" >&2
    exit 1
fi

fails=0
pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; fails=$((fails + 1)); }

# Pulls one labelled number out of the summary block.
field() { awk -v k="$1" '$0 ~ k {for (i=1;i<=NF;i++) if ($i+0==$i && $i!="") {print $i; exit}}'; }

echo "1. informative terrain: the filter must beat dead reckoning"
out=$("$BIN" --terrain ridged --duration 600 --dem-size 2000 --quiet)
pf=$(echo "$out"  | awk '/terrain-aided final error/ {print $4}')
dr=$(echo "$out"  | awk '/dead reckoning final error/ {print $5}')
ok=$(awk -v p="$pf" -v d="$dr" 'BEGIN{print (p < d/4 && p < 100) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "terrain-aided ${pf} m vs dead-reckoned ${dr} m" \
                 || fail "terrain-aided ${pf} m vs dead-reckoned ${dr} m"

echo "2. the filter must acquire a fix from a large initial uncertainty"
out=$("$BIN" --terrain ridged --init-radius 3000 --particles 12000 --quiet)
if echo "$out" | grep -q "acquired fix at"; then
    t=$(echo "$out" | awk '/acquired fix at/ {print $4}')
    ok=$(awk -v t="$t" 'BEGIN{print (t <= 60) ? 1 : 0}')
    [[ "$ok" == 1 ]] && pass "acquired from a +/-3 km box in ${t} s" \
                     || fail "took ${t} s to acquire, expected under 60 s"
else
    fail "never acquired a fix from a +/-3 km box"
fi

echo "3. flat terrain must NOT converge (observability, not a bug)"
out=$("$BIN" --terrain flat --quiet)
if echo "$out" | grep -q "never acquired a fix"; then
    pass "correctly failed to localise over featureless ground"
else
    fail "claimed a fix over flat terrain — the likelihood model is wrong"
fi

echo "4. mixed terrain must acquire a fix and then lose it"
out=$("$BIN" --terrain mixed --heading 0 --start 2000,18000 --duration 280 --quiet)
if echo "$out" | grep -q "acquired fix at" && echo "$out" | grep -q "LOST fix at"; then
    r=$(echo "$out" | awk '/LOST fix at/ {print $(NF-1)}')
    ok=$(awk -v r="$r" 'BEGIN{print (r < 5) ? 1 : 0}')
    [[ "$ok" == 1 ]] && pass "lost the fix where roughness fell to ${r} m" \
                     || fail "lost the fix at roughness ${r} m, expected near zero"
else
    fail "expected acquire-then-lose over mixed terrain"
fi

echo "5. runs must be reproducible for a given seed"
a=$("$BIN" --terrain ridged --seed 42 --quiet)
b=$("$BIN" --terrain ridged --seed 42 --quiet)
[[ "$a" == "$b" ]] && pass "identical output for seed 42" || fail "same seed gave different results"

echo "6. different seeds must give different runs"
c=$("$BIN" --terrain ridged --seed 43 --quiet)
[[ "$a" != "$c" ]] && pass "seed 43 differs from seed 42" || fail "seed is not being used"

echo "7. the filter must be robust across seeds, not lucky on one"
wins=0; trials=8
for s in 1 2 3 4 5 6 7 8; do
    out=$("$BIN" --terrain ridged --seed $s --quiet)
    pf=$(echo "$out" | awk '/terrain-aided final error/ {print $4}')
    dr=$(echo "$out" | awk '/dead reckoning final error/ {print $5}')
    ok=$(awk -v p="$pf" -v d="$dr" 'BEGIN{print (p < d) ? 1 : 0}')
    wins=$((wins + ok))
done
[[ $wins -ge 7 ]] && pass "beat dead reckoning in $wins/$trials seeds" \
                  || fail "only beat dead reckoning in $wins/$trials seeds"

echo "8. tightening the altimeter must not make the fix worse"
loose=$("$BIN" --terrain ridged --radar-sigma 25 --meas-sigma 30 --seed 5 --quiet \
        | awk '/mean error while holding it/ {print $6}')
tight=$("$BIN" --terrain ridged --radar-sigma 1 --meas-sigma 6 --seed 5 --quiet \
        | awk '/mean error while holding it/ {print $6}')
ok=$(awk -v l="$loose" -v t="$tight" 'BEGIN{print (t <= l) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "sigma 25 m -> ${loose} m error, sigma 1 m -> ${tight} m error" \
                 || fail "better sensor gave worse result (${loose} -> ${tight})"

echo "9. every filter mode must still beat dead reckoning"
for m in pf2d pf4d rbpf; do
    out=$("$BIN" --filter $m --terrain ridged --duration 400 --dem-size 1600 --quiet)
    pf=$(echo "$out" | awk '/terrain-aided final error/ {print $4}')
    dr=$(echo "$out" | awk '/dead reckoning final error/ {print $5}')
    ok=$(awk -v p="$pf" -v d="$dr" 'BEGIN{print (p < d/4) ? 1 : 0}')
    [[ "$ok" == 1 ]] && pass "$m: ${pf} m vs dead-reckoned ${dr} m" \
                     || fail "$m: ${pf} m vs dead-reckoned ${dr} m"
done

echo "10. Rao-Blackwellisation must beat the bootstrap at equal particle count"
mean_bias() {   # mode, particles -> mean bias error over 6 seeds
    local m=$1 n=$2 tot=0
    for s in 1 2 3 4 5 6; do
        local e
        e=$("$BIN" --filter "$m" --particles "$n" --seed $s --terrain ridged \
             --duration 400 --dem-size 1600 --quiet | awk '/bias error/{print $3}')
        tot=$(awk -v t=$tot -v e="$e" 'BEGIN{print t+e}')
    done
    awk -v t=$tot 'BEGIN{printf "%.4f", t/6}'
}
b4=$(mean_bias pf4d 5000)
br=$(mean_bias rbpf 5000)
ok=$(awk -v a="$b4" -v b="$br" 'BEGIN{print (b < a/2) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "5000 particles: bootstrap ${b4} m/s vs Rao-Blackwellised ${br} m/s" \
                 || fail "5000 particles: bootstrap ${b4} m/s vs Rao-Blackwellised ${br} m/s"

echo "11. Rao-Blackwellisation must beat the bootstrap using 20x fewer particles"
br_small=$(mean_bias rbpf 1000)
b4_big=$(mean_bias pf4d 20000)
ok=$(awk -v a="$b4_big" -v b="$br_small" 'BEGIN{print (b < a) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "rbpf@1000 ${br_small} m/s beats pf4d@20000 ${b4_big} m/s" \
                 || fail "rbpf@1000 ${br_small} m/s vs pf4d@20000 ${b4_big} m/s"

echo "12. a calibrated bias must make the solution coast better"
coast() {
    "$BIN" --filter "$1" --terrain mixed --dem-size 2000 --heading 0 \
           --start 2000,30000 --duration 450 --quiet | awk '/coasted/{print $6}'
}
c2=$(coast pf2d)
cr=$(coast rbpf)
if [[ -z "$c2" || -z "$cr" ]]; then
    fail "expected both modes to acquire and then lose a fix"
else
    ok=$(awk -v a="$c2" -v b="$cr" 'BEGIN{print (b < a) ? 1 : 0}')
    [[ "$ok" == 1 ]] && pass "coast drift ${c2} m/s uncalibrated vs ${cr} m/s calibrated" \
                     || fail "coast drift ${c2} m/s uncalibrated vs ${cr} m/s calibrated"
fi

echo "13. a uniform map shift must bias the fix, NOT starve the filter"
# Common-mode error: every nearby particle takes the same hit, and log-sum-exp
# cancels common offsets exactly, so the filter stays confident and stays wrong.
out=$("$BIN" --filter rbpf --relief 5000 --map-shift 40,40 --duration 400 \
      --dem-size 1600 --quiet)
err=$(echo "$out" | awk '/terrain-aided final error/ {print $4}')
held=$(echo "$out" | awk '/fix held/ {print $4}')
ok=$(awk -v e="$err" -v h="$held" 'BEGIN{print (e > 40 && e < 90 && h > 90) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "shift |40,40|=56.6 m gave ${err} m error, fix held ${held}%" \
                 || fail "shift |40,40|=56.6 m gave ${err} m error, fix held ${held}%"

echo "14. gradient inflation must help when map error correlates with slope"
median_err() {   # extra-args -> median final error over 5 seeds
    local out=""
    for s in 1 2 3 4 5; do
        out="$out $("$BIN" --filter rbpf --relief 5000 --map-downsample 8 "$@" \
                    --seed $s --duration 400 --dem-size 1600 --quiet \
                    | awk '/terrain-aided final error/{print $4}')"
    done
    echo "$out" | tr ' ' '\n' | grep -v '^$' | sort -n | awk '{a[NR]=$1} END{print a[int((NR+1)/2)]}'
}
off=$(median_err)
on=$(median_err --gradient-inflation)
ok=$(awk -v a="$off" -v b="$on" 'BEGIN{print (b < a) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "8x degraded map: ${off} m without inflation, ${on} m with" \
                 || fail "8x degraded map: ${off} m without inflation, ${on} m with"

echo "15. inflation must not hurt when the map is exact"
clean_off=$("$BIN" --filter rbpf --relief 5000 --seed 3 --duration 400 --dem-size 1600 \
            --quiet | awk '/terrain-aided final error/{print $4}')
clean_on=$("$BIN" --filter rbpf --relief 5000 --seed 3 --gradient-inflation --duration 400 \
           --dem-size 1600 --quiet | awk '/terrain-aided final error/{print $4}')
ok=$(awk -v a="$clean_off" -v b="$clean_on" 'BEGIN{print (b < a * 2.5) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "exact map: ${clean_off} m without, ${clean_on} m with" \
                 || fail "exact map: inflation degraded a perfect map (${clean_off} -> ${clean_on})"

echo "16. bicubic must reconstruct better than bilinear from the same bytes"
BASE="--dem-size 800 --dem-spacing 30 --relief 2500 --terrain ridged"
lin=$("$BIN" $BASE --map-downsample 8 --map-interp bilinear --map-rmse | awk '/elevation RMSE/{print $3}')
cub=$("$BIN" $BASE --map-downsample 8 --map-interp bicubic  --map-rmse | awk '/elevation RMSE/{print $3}')
ok=$(awk -v a="$lin" -v b="$cub" 'BEGIN{print (b < a) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "8x grid: bilinear ${lin} m, bicubic ${cub} m" \
                 || fail "8x grid: bilinear ${lin} m, bicubic ${cub} m"

echo "17. analytic gradients must match central differences"
for cfg in "--map-interp bilinear" "--map-interp bicubic"; do
    d=$("$BIN" $BASE --map-downsample 8 $cfg --probe 7000,7000 \
        | awk '/delta/{gsub(/[(),]/,""); print ($2<0?-$2:$2)+($3<0?-$3:$3)}')
    ok=$(awk -v d="$d" 'BEGIN{print (d < 1e-4) ? 1 : 0}')
    [[ "$ok" == 1 ]] && pass "${cfg#--map-interp } gradient matches to ${d}" \
                     || fail "${cfg#--map-interp } gradient off by ${d}"
done

echo "18. bicubic must reduce navigation tail risk on a degraded map"
worst() {
    local out=""
    for s in 1 2 3 4 5 6 7 8; do
        out="$out $("$BIN" $BASE --map-downsample 8 --map-interp "$1" --filter rbpf \
                    --gradient-inflation --duration 160 --start 1500,1500 --seed $s --quiet \
                    | awk '/terrain-aided final error/{print $4}')"
    done
    echo "$out" | tr ' ' '\n' | grep -v '^$' | sort -n | tail -1
}
wl=$(worst bilinear); wc=$(worst bicubic)
ok=$(awk -v a="$wl" -v b="$wc" 'BEGIN{print (b < a) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "worst case ${wl} m bilinear vs ${wc} m bicubic" \
                 || fail "worst case ${wl} m bilinear vs ${wc} m bicubic"

# The neural checks only run when a trained network is present, since training
# is a separate offline step and the repo does not ship weights.
if [[ -n "${SIREN:-}" && -f "${SIREN:-}" ]]; then
    echo "19. neural map gradients must match central differences"
    d=$("$BIN" $BASE --neural "$SIREN" --probe 7000,7000 \
        | awk '/delta/{gsub(/[(),]/,""); print ($2<0?-$2:$2)+($3<0?-$3:$3)}')
    ok=$(awk -v d="$d" 'BEGIN{print (d < 1e-4) ? 1 : 0}')
    [[ "$ok" == 1 ]] && pass "SIREN forward-mode gradient matches to ${d}" \
                     || fail "SIREN gradient off by ${d}"
else
    echo "19. neural map checks skipped (set SIREN=path/to/map.siren to enable)"
fi

echo "20. bicubic must be safe at and beyond the map edges"
# The 4x4 Catmull-Rom footprint reaches ix-1 and ix+2, so an unclamped lookup
# would read outside the array one cell from the boundary.
edge_ok=1
for pt in 0,0 -500,-500 5970,5970 99999,99999 0,5970; do
    out=$("$BIN" --dem-size 200 --dem-spacing 30 --map-interp bicubic --probe "$pt" 2>&1)
    v=$(echo "$out" | awk '/^elevation  /{print $2}' | tail -1)
    ok=$(awk -v v="$v" 'BEGIN{print (v+0==v && v>0 && v<100000) ? 1 : 0}')
    [[ "$ok" == 1 ]] || { edge_ok=0; echo "      bad value at $pt: $v"; }
done
[[ "$edge_ok" == 1 ]] && pass "corners and out-of-range queries return finite elevations" \
                      || fail "bicubic produced a bad value at a map edge"

echo "21. conflicting map sources must be rejected, not silently resolved"
conf_ok=1
for pair in "--error-amplitude 20 --map-downsample 8" \
            "--error-amplitude 20 --map-interp bicubic"; do
    if "$BIN" --dem-size 200 --duration 1 --quiet $pair > /dev/null 2>&1; then
        conf_ok=0; echo "      accepted: $pair"
    fi
done
[[ "$conf_ok" == 1 ]] && pass "combined map options exit non-zero with an explanation" \
                      || fail "a conflicting map combination was silently accepted"

echo "22. a corrupt neural map must be refused, not navigated against"
if [[ -n "${SIREN:-}" && -f "${SIREN:-}" ]]; then
    tmp=$(mktemp -d)
    # Byte-swap every word after the magic: what a big-endian reader would see.
    python3 - "$SIREN" "$tmp/swapped.siren" <<'PY'
import sys
d = open(sys.argv[1], "rb").read()
out = bytearray(d[:8]); body = d[8:]
for i in range(0, len(body) - len(body) % 4, 4):
    out += body[i:i+4][::-1]
open(sys.argv[2], "wb").write(bytes(out))
PY
    head -c 40 "$SIREN" > "$tmp/trunc.siren"
    corrupt_ok=1
    for f in "$tmp/swapped.siren" "$tmp/trunc.siren"; do
        "$BIN" --dem-size 200 --neural "$f" --probe 100,100 > /dev/null 2>&1 && {
            corrupt_ok=0; echo "      accepted corrupt file: $(basename "$f")"; }
    done
    "$BIN" --dem-size 200 --neural "$SIREN" --probe 100,100 > /dev/null 2>&1 || {
        corrupt_ok=0; echo "      rejected a VALID file"; }
    rm -rf "$tmp"
    [[ "$corrupt_ok" == 1 ]] && pass "byte-swapped and truncated maps refused, valid map accepted" \
                             || fail "corrupt neural map handling is wrong"
else
    echo "  SKIP  set SIREN=path/to/map.siren to enable"
fi

echo
if [[ $fails -eq 0 ]]; then echo "all checks passed"; else echo "$fails check(s) failed"; fi
exit $fails
