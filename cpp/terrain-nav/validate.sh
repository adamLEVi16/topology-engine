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

echo
if [[ $fails -eq 0 ]]; then echo "all checks passed"; else echo "$fails check(s) failed"; fi
exit $fails
