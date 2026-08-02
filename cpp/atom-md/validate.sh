#!/usr/bin/env bash
# Physics regression checks. Run after building:
#   cmake -S . -B build && cmake --build build -j && ./validate.sh
set -uo pipefail

BIN=${BIN:-./build/atom_md}
if [[ ! -x "$BIN" ]]; then
    echo "error: $BIN not found — build first (cmake -S . -B build && cmake --build build -j)" >&2
    exit 1
fi

fails=0
pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; fails=$((fails + 1)); }

echo "1. cell list must agree exactly with the O(N^2) pair loop"
# Only the banner line naming the search method may differ.
a=$("$BIN" --equil 200 --steps 500 --report 100 | grep -v "neighbour search")
b=$("$BIN" --equil 200 --steps 500 --report 100 --no-cells | grep -v "neighbour search")
if [[ "$a" == "$b" ]]; then
    pass "identical trajectories over 700 steps"
else
    fail "cell list and brute force diverged"
fi

echo "2. NVE energy drift must stay small and scale as dt^2"
prev=""
for dt in 0.008 0.004 0.002 0.001; do
    drift=$("$BIN" --dt $dt --equil 500 --steps 2000 --report 100000 --thermostat none \
            | awk '/max \|dE\/E\|/ {print $3}')
    if [[ -n "$prev" ]]; then
        ratio=$(awk -v p="$prev" -v d="$drift" 'BEGIN{print p/d}')
        ok=$(awk -v r="$ratio" 'BEGIN{print (r > 2.8 && r < 5.5) ? 1 : 0}')
        [[ "$ok" == 1 ]] && pass "dt=$dt drift=$drift (${ratio%.*}x better)" \
                         || fail "dt=$dt drift=$drift — ratio $ratio not near 4"
    else
        pass "dt=$dt drift=$drift (baseline)"
    fi
    prev=$drift
done

echo "3. drift at the default timestep must be below 1e-4"
drift=$("$BIN" --equil 500 --steps 2000 --report 100000 --thermostat none \
        | awk '/max \|dE\/E\|/ {print $3}')
ok=$(awk -v d="$drift" 'BEGIN{print (d < 1e-4) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "max |dE/E| = $drift" || fail "max |dE/E| = $drift is too large"

echo "4. Langevin thermostat must hit the target temperature"
for target in 0.6 1.2 2.0; do
    got=$("$BIN" --temperature $target --thermostat langevin --equil 2000 --steps 4000 \
          --report 100000 | awk '/^  T / {print $2; exit}')
    ok=$(awk -v g="$got" -v t="$target" 'BEGIN{print (g > 0.94*t && g < 1.06*t) ? 1 : 0}')
    [[ "$ok" == 1 ]] && pass "target T*=$target, measured $got" \
                     || fail "target T*=$target, measured $got"
done

echo "5. g(r) must show liquid structure (first peak near 1.1 sigma)"
rdf=$(mktemp)
"$BIN" --equil 1000 --steps 3000 --report 100000 --rdf "$rdf" > /dev/null
read -r peak_r peak_g < <(awk 'NR>1 && $2>m {m=$2; r=$1} END{print r, m}' "$rdf")
ok=$(awk -v r="$peak_r" -v g="$peak_g" 'BEGIN{print (r>1.0 && r<1.2 && g>2.5 && g<3.5) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "first peak g=$peak_g at r=$peak_r" \
                 || fail "first peak g=$peak_g at r=$peak_r is off"
# g(r) must vanish inside the repulsive core.
core=$(awk 'NR>1 && $1<0.8 {s+=$2} END{print s+0}' "$rdf")
ok=$(awk -v c="$core" 'BEGIN{print (c < 1e-9) ? 1 : 0}')
[[ "$ok" == 1 ]] && pass "no density inside the repulsive core" \
                 || fail "found density below r=0.8 sigma (sum $core)"
rm -f "$rdf"

echo
if [[ $fails -eq 0 ]]; then
    echo "all checks passed"
else
    echo "$fails check(s) failed"
fi
exit $fails
