# terrain-nav — navigating without GPS

Knowing where you are by looking at the shape of the ground underneath you.

A vehicle carries an inertial unit, a radar altimeter, a barometer, and a stored
elevation map. It has no GPS. Every second it measures the ground elevation
beneath itself, compares that against the map, and uses the mismatch to correct
an inertial solution that would otherwise drift away without bound.

No dependencies beyond the standard library. Terrain is generated procedurally,
so it runs immediately — but it reads real SRTM tiles too.

## The idea

A radar altimeter measures height above ground. A barometer measures height
above sea level. Subtract them and you get **the elevation of the ground you are
currently over** — one scalar, once per second.

One such number is nearly useless: an entire contour line of the map sits at
that elevation. But a *sequence* of them, tied together by the inertial unit's
knowledge of how far you moved between samples, traces an elevation profile. And
an elevation profile through rough terrain is close to unique. Match it against
the map and you have a position fix.

This is the operating principle behind terrain-referenced navigation, used in
cruise missiles (TERCOM), in aircraft, and — with sonar instead of radar — in
autonomous underwater vehicles, where GPS is unavailable by definition.

## Build and run

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/terrain_nav
./validate.sh
```

On Windows the notes in `../atom-md/README.md` apply verbatim: you need the
Visual Studio C++ workload, and you must build `--config Release`.

```bash
# the headline demo — writes a hill-shaded map with all three tracks
./build/terrain_nav --terrain ridged --dem-size 2000 --duration 600 \
                    --image map.ppm --csv history.csv

# the failure mode: featureless ground carries no information
./build/terrain_nav --terrain flat

# acquire a fix, then fly onto a plain and lose it
./build/terrain_nav --terrain mixed --heading 0 --start 2000,18000 --duration 280

# a real SRTM tile
./build/terrain_nav --hgt N37W122.hgt
```

Free global elevation data: **OpenTopography**, **USGS 3DEP** (1 m lidar over
much of the US), or SRTM `.hgt` tiles, which this reads directly.

## What the run tells you

```
    t(s)   dead-reckon terrain-aided     spread     N_eff  roughness
     0.0         472.1         465.8     1195.8      1394       32.4
    20.0         456.5          38.6       63.2      3762       31.3
   ...
   599.0         462.8          23.5       47.2      3418       44.9

result
  dead reckoning final error   462.8 m   (peak 472.1 m)
  terrain-aided final error     23.5 m
  lowest N_eff                  13.6 % of the population
  acquired fix at               17.0 s
  mean error while holding it   31.1 m
```

`N_eff` is sampled before resampling, so it shows the value that triggers a
resample rather than the uniform `N` that exists immediately afterwards. Read the
other way it is pinned above the resample threshold by construction and can never
report the particle starvation it exists to detect.

Dead reckoning walks away linearly with time, because the inertial unit has a
small constant velocity bias and nothing ever corrects it. The terrain-aided
solution converges from an initial 1.5 km box to a few tens of metres and
**stays there**. That bounded-versus-unbounded distinction is the entire point:
inertial navigation has excellent short-term accuracy and no long-term truth,
and terrain gives it the truth.

## How it works

### The measurement

```
ground_elevation = barometric_altitude − radar_altitude + noise
```

with noise of about `sqrt(radar_sigma² + baro_sigma²)` ≈ 9.5 m by default. The
barometer is the weak link, which is realistic — pressure altitude is sensitive
to weather.

### The filter

A **bootstrap particle filter**. Kalman filtering is the wrong tool here: the
measurement model is `z = DEM(x, y)`, and a DEM is about as non-linear as a
function gets — it is not differentiable in any useful sense, and its likelihood
surface is wildly multi-modal. An EKF linearises around a single estimate and
commits to one hypothesis immediately, which is exactly wrong when a hundred
valleys on the map fit your data equally well.

Particles represent the posterior as samples, so the filter can carry every
plausible hypothesis at once and let the terrain kill them off. Each cycle:

1. **Predict** — move every particle by the inertially-reported displacement,
   plus process noise standing in for unmodelled inertial error.
2. **Update** — for each particle, look up `DEM(x, y)` and score it against the
   measurement: `log w += −innovation² / 2σ²`.
3. **Resample** — when the effective sample size `1/Σw²` falls below half the
   population, resample systematically and add roughening jitter.

Three details matter more than they look:

- **Log-domain weights.** A particle 200 m wrong in elevation with σ = 10 m
  scores `exp(−200)`, which underflows to exactly zero in linear arithmetic.
  Do the accumulation in logs and subtract the maximum before exponentiating,
  or the filter silently dies.
- **Roughening after resampling.** Resampling duplicates survivors, so without
  added jitter the cloud collapses onto a handful of distinct points and can
  never recover from an early mistake.
- **Systematic resampling**, not multinomial — lower variance and O(N).

### Declaring a fix

The filter declares a fix from its **posterior spread**, never from its true
error. This is not a detail; it is the difference between a simulation and
something that could fly. A real vehicle has no access to its own error — if it
did, it would not need the filter. Spread is the only confidence signal
available in flight.

Getting this wrong is instructive, and this code got it wrong first: scoring
convergence against true error made the filter claim a solid fix over a
dead-flat plain, because the drifting estimate wandered inside the error
threshold by luck and sat there. Judged by spread — which never collapsed — the
same run correctly reports no fix at all.

## Observability: when this cannot work

Terrain navigation needs the terrain to *say something*. Formally the position
is unobservable wherever the elevation field is locally flat or self-similar,
and no filter, however good, recovers information that the measurements do not
contain.

The `mixed` scenario flies from ridged terrain onto a plain and shows the whole
arc in one run:

```
   t(s)   dead-reckon terrain-aided      spread   roughness
   40.0         191.8           8.4        53.2        19.6     <- locked on
  140.0         166.4          43.7        63.1         8.9     <- terrain fading
  200.0         190.5          84.2       140.1         0.9     <- nothing to see
  279.0         251.9         186.7       202.6         0.5     <- fix lost
```

Error and spread grow together as roughness collapses. The filter does not fail
silently — it reports its own growing uncertainty, which is what lets a real
system fall back to inertial-only and know that it has.

Practical consequences, all of which fall straight out of this:

- Deserts, plains, ice sheets, and open ocean are unusable.
- Ridge crossings are worth far more than ridge-parallel flight.
- Repetitive terrain — dune fields, regular ridge-and-valley — creates genuine
  multi-modal ambiguity, which is precisely why a particle filter is the right
  choice: it can hold both hypotheses until something breaks the tie.
- Terrain relief must exceed sensor noise. With a 9.5 m noise floor, 3 m of
  relief is invisible.

## Validating it

`validate.sh` tests behaviour rather than exit codes:

1. Terrain-aided error beats dead reckoning by 4× or more over informative ground
2. A fix is acquired from a ±3 km initial uncertainty box
3. Flat terrain produces **no** fix — the observability failure is required
4. Mixed terrain acquires a fix and then loses it as roughness collapses
5. A given seed reproduces exactly
6. Different seeds produce different runs
7. The filter beats dead reckoning across 8 seeds, not just a lucky one
8. A more precise altimeter never produces a worse fix
9. All three filter modes beat dead reckoning by 4× or more
10. Rao-Blackwellisation halves the bias error at equal particle count
11. `rbpf` with 1,000 particles beats `pf4d` with 20,000
12. Calibrating the bias measurably improves the coast after the fix is lost
13. A uniform map shift biases the fix by ‖shift‖ without costing confidence
14. Gradient inflation improves accuracy when map error correlates with slope
15. Gradient inflation does not degrade a run against an exact map

Current results: 600 s of flight, dead reckoning ends **463 m** out while the
terrain-aided solution holds **24 m**, with a mean of 31 m once converged.

## Calibrating the inertial unit

Correcting position is only half of what terrain can buy you. The inertial unit
has a constant velocity bias, and a filter that merely corrects position has to
fight that bias forever. A filter that *estimates* it can zero the sensor error
— and then keep coasting accurately long after the terrain stops helping.

Note what is being estimated: a **velocity** bias, in m/s. A raw accelerometer
bias would give velocity error growing as `t` and position error as `t²`. A
velocity-level bias — what attitude and gyro error look like after one
integration — gives position error linear in `t`. A full inertial error state
would be 15 states; this is the useful simplification.

Three modes, selectable with `--filter`:

| Mode | State | Bias handling |
|---|---|---|
| `pf2d` | `(x, y)` | absorbed into process noise |
| `pf4d` | `(x, y, bx, by)` | sampled — brute-force bootstrap |
| `rbpf` | `(x, y)` + per-particle Kalman filter | marginalised analytically |

### Why Rao-Blackwellisation applies

The model is mixed linear/nonlinear, and terrain-aided navigation is the
canonical example in the marginalised-particle-filter literature:

```
p_{k+1} = p_k + (v_meas − b_k)·dt + w_p     bias enters LINEARLY
b_{k+1} = b_k + w_b
z_k     = DEM(p_k) + e_k                     measurement ignores b entirely
```

Because `z` never touches `b`, the terrain cannot update the bias directly. The
bias is instead observed through the **sampled displacement**: once a particle
draws its step, that realised step is a linear measurement of the bias with
`H = −dt·I`, so each particle runs an exact 2×2 Kalman update. Particles whose
bias estimate is wrong take steps that carry them off terrain-consistent ground
and die at resampling.

So the particles only ever search the two genuinely non-linear dimensions, and
the two linear ones are integrated out in closed form.

### Measured results

Mean bias error over 8 seeds, 400 s of flight over ridged terrain:

| Filter | Particles | Mean bias error | Worst seed |
|---|---|---|---|
| `pf4d` | 1,000 | 1.544 m/s | 3.808 m/s |
| `pf4d` | 5,000 | 0.567 m/s | 0.969 m/s |
| `pf4d` | 20,000 | 0.374 m/s | 0.640 m/s |
| `pf4d` | 40,000 | 0.230 m/s | 0.406 m/s |
| **`rbpf`** | **1,000** | **0.145 m/s** | **0.252 m/s** |
| `rbpf` | 5,000 | 0.104 m/s | 0.208 m/s |

The Rao-Blackwellised filter with **1,000** particles is more accurate than the
bootstrap with **40,000** — a 40× reduction in particle count that still leaves
the bootstrap behind. It also runs marginally *faster* at equal particle count,
because sharper weights mean fewer resampling events.

Note too that `rbpf` barely moves from 1,000 to 5,000 particles: it is close to
the information limit of the measurements. Adding particles buys little, because
the bias uncertainty is being integrated analytically rather than sampled. That
is the Rao-Blackwell variance-reduction theorem showing up as a nearly flat line.

The bootstrap at 1,000 particles is worse than its own 3 m/s prior — with four
dimensions to cover, the cloud simply cannot span the space, and it diverges.

### What calibration buys: the coast test

Fly from ridged terrain onto a plain, lose the fix, and keep going on inertial
alone (`--terrain mixed`, 60 km map, 450 s):

| Filter | Bias error | Coast drift rate | Final position error |
|---|---|---|---|
| `pf2d` | not estimated | 1.01 m/s | 270.6 m |
| `pf4d` | 0.389 m/s | 0.36 m/s | 95.8 m |
| `rbpf` | 0.172 m/s | **0.18 m/s** | **62.1 m** |

Same terrain, same sensors, same particle count. The only difference is how well
the inertial bias was solved while the terrain was still informative — and it
shows up as a 5.6× slower error growth and a 4× better final position once the
terrain has gone quiet. That is the entire argument for co-estimating the bias.

The drift rate is measured from the moment the spread crosses the threshold, not
from the moment the loss is *declared* ten steps later. Dividing the later
interval's error growth by the earlier interval's duration understated it by
about 8%.

## The map is not the truth

Everything above assumes the stored DEM is exact. It is not. A real map has a
vertical accuracy and — far more dangerously on steep ground — a horizontal
registration error. A lateral offset of `d` metres on a slope of gradient `g`
looks like a vertical error of `|g|·d`, which on a 45° face equals `d` exactly.

`--gradient-inflation` propagates that horizontal uncertainty into the
measurement variance, per particle:

```
var_eff(i) = var_sensor + var_map_vertical + ∇DEM(x_i, y_i)ᵀ · Σ_xy · ∇DEM(x_i, y_i)
```

The gradient is the exact analytic derivative of the bilinear interpolant, not a
finite difference — though note it is only piecewise continuous, since a bilinear
surface is C0 and its gradient jumps across cell boundaries.

**One thing here is not optional.** Once the variance varies per particle, the
likelihood's normalising term `−½·log(var)` must be carried explicitly. With a
constant sigma it is a shared constant that cancels during normalisation. With a
per-particle sigma it does not, and dropping it hands every particle standing on
a cliff a free weight bonus — because `exp(−d²/2σ²) → 1` as `σ` grows. The filter
would then quietly migrate onto steep ground, which is the opposite of what the
inflation is for.

### Finding 1: a uniform map shift biases the fix, it does not starve the filter

The intuitive prediction is that misregistration on steep terrain kills the
correct particles. Measured, over terrain with a 52° mean slope:

| Map shift | ‖shift‖ | Final error | Fix held |
|---|---|---|---|
| 0, 0 | 0.0 m | 12.1 m | 96.2 % |
| 10, 10 | 14.1 m | 24.2 m | 96.0 % |
| 20, 20 | 28.3 m | 37.7 m | 96.2 % |
| 40, 40 | 56.6 m | 64.5 m | 96.2 % |
| 80, 80 | 113.1 m | 121.5 m | 96.2 % |

The error tracks ‖shift‖ almost exactly and the filter never loses confidence.

The reason is that a uniform shift is a **common-mode** error: every particle in
the neighbourhood takes nearly the same spurious innovation, and the log-sum-exp
normalisation cancels common offsets *exactly*. Starvation is therefore
impossible from this mechanism. What you get instead is arguably worse — a filter
that is confidently wrong by precisely the map's registration error, and no
internal signal that anything is amiss.

### Finding 2: slope-correlated map error is the real hazard

Starvation needs error that **differentially** penalises particles, which means
error correlated with local slope. Map *resolution* does exactly that: a coarse
grid is badly wrong on steep ground and nearly right on flat ground, so particles
over rough terrain are systematically punished and the filter drifts toward flat
areas — precisely where there is no information.

Truth on a 30 m grid, filter navigating a decimated copy, 8 seeds per cell:

| Map | Inflation off (median / worst) | Inflation on (median / worst) |
|---|---|---|
| exact | 6.8 m / 12.1 m | 6.0 m / 9.8 m |
| 4× coarse | 50.5 m / 61.4 m | 44.1 m / 55.0 m |
| 8× coarse | 48.2 m / **4682.8 m** | 36.5 m / 46.2 m |
| 12× coarse | 52.6 m / 88.7 m | 42.0 m / 58.8 m |
| 16× coarse | **64.6 m** / 84.6 m | 75.6 m / 132.3 m |

At 8× coarse across 24 seeds: 1/24 runs diverged catastrophically without
inflation versus 0/24 with, mean error 252 m versus 41 m, worst case 4683 m
versus 60 m.

Read honestly, that is a **~15–25 % median improvement and a large reduction in
tail risk**, not a rescue from certain death. A 1-versus-0 divergence count over
24 seeds carries no statistical weight by itself; the mean and worst case are
what actually carry the result.

### Finding 3: inflation backfires when the map is too coarse to differentiate

At 16× the effect reverses — inflation is *worse* (75.6 m versus 64.6 m median).
The mechanism is self-inflicted: the gradient is computed from the degraded map,
so once the map is too coarse to represent the real slope, the filter is
inflating variance according to a gradient that is itself wrong, and throwing
away good measurements for no reason.

Gradient inflation is therefore useful over a **middle band** of map quality —
degraded enough that slope-correlated error matters, accurate enough that the
slope estimate is still meaningful.

## Does the map have to be a grid?

A grid stores samples and interpolates between them. A small neural network can
instead store terrain as a continuous function — differentiable everywhere by the
chain rule rather than only within a cell. Since the filter now asks the map for
gradients, that sounded like it should matter.

`tools/train_siren.py` fits a SIREN (sinusoidal coordinate network, Sitzmann et
al. 2020) to a terrain grid in pure NumPy with hand-written backprop, and exports
weights that `NeuralMap` reads. Gradients come from forward-mode differentiation
through the network, which agrees with central differences to seven decimals.

Both representations sit behind one `TerrainMap` interface — `elevation(x, y)`
and `gradient(x, y)` — so they are drop-in alternatives comparable at equal bytes.

### The baseline has to be bicubic

The tempting framing is "grids are stair-stepped, neural fields are smooth." That
is false, and believing it would have produced a flattering, meaningless result.
Bilinear interpolation is C0 and its gradient jumps at every cell boundary, but
**bicubic (Catmull-Rom) interpolation is C1 and gives smooth analytic gradients
from exactly the same stored bytes.** That, not bilinear, is the honest baseline.

### Measured at equal storage

Truth is an 800×800 grid at 30 m (2 500 KiB) over ridged terrain with a 42° mean
slope. Navigation figures are medians over 8 seeds with the marginalised filter.

> **These two tables predate the harness fixes and have not been regenerated.**
> The INS bias bearing is now drawn uniformly rather than from a wrapped normal,
> which re-rolls every seeded run, so the navigation columns will move. The query
> column will move further: the map interface now returns elevation and gradient
> from one call, which costs a neural field one forward pass instead of two.
> Regenerating needs the trained SIREN weights, which are an offline step and are
> not in the repo — so the numbers are left as recorded rather than half-updated.
> Measured against the current build, the query figures are 41 ns for the
> bilinear grid, 91 ns bicubic, and 16 913 ns for a 64×3 SIREN — a **186×**
> penalty against the bicubic baseline, not the ~300× recorded below.
>
> The ordering the section argues from — bicubic beating bilinear on both median
> and tail, and the neural map losing on navigation despite winning on
> reconstruction — is a large effect and is not expected to invert. But treat the
> specific figures as stale.

| Representation | Store | Elev RMSE | Nav median | Nav worst | Query |
|---|---|---|---|---|---|
| grid 8×, bilinear | 39 KiB | 41.0 m | 72.5 m | 770.8 m | 42 ns |
| grid 8×, bicubic | 39 KiB | 34.5 m | **62.4 m** | **89.2 m** | 96 ns |
| SIREN 64×3 | 34 KiB | **26.4 m** | 102.2 m | 122.7 m | 30 458 ns |
| grid 16×, bilinear | 10 KiB | 78.3 m | 177.7 m | 427.4 m | 37 ns |
| grid 16×, bicubic | 10 KiB | 67.1 m | **152.2 m** | 3 986 m | 94 ns |
| SIREN 48×2 | 10 KiB | **49.9 m** | 1 334 m | 8 182 m | 11 333 ns |
| exact grid | 2 500 KiB | 0.0 m | 10.2 m | 21.3 m | 41 ns |

### The two budgets fail differently

Medians hide the shape of the failure. Over 14 seeds, counting a run as diverged
when it ends more than 300 m out:

| Representation | Median | Diverged | Best seed | Worst seed |
|---|---|---|---|---|
| grid 8×, bicubic | 60.3 m | **0/14** | 23.1 m | 89.2 m |
| SIREN 34 KiB | 101.6 m | **0/14** | 40.0 m | 122.7 m |
| grid 16×, bicubic | 153.9 m | 6/14 | 134.3 m | 3 987 m |
| SIREN 10 KiB | 8 098 m | 9/14 | **39.1 m** | 8 185 m |

At the ~39 KiB budget **neither representation ever diverges**. The neural map is
simply and consistently worse — roughly 1.7× the error, tightly distributed. That
is the clean comparison.

At the ~10 KiB budget **both representations become unreliable**, the grid failing
6 times in 14 and the SIREN 9. This budget is below what this terrain needs, and
the honest reading is not "grid beats neural" but "both fail, one more often."

The SIREN's best seed at 10 KiB is 39.1 m — better than the grid's *best* seed of
134.3 m. So the neural map demonstrably carries more usable information, exactly
as its lower RMSE suggests, and yet the filter cannot exploit it reliably. That
bimodality is the sharpest form of the puzzle below.

### Finding 4: better reconstruction, worse navigation

The neural map wins on every map-fidelity measure and loses on the only one that
counts:

- Elevation RMSE: **26.4 m vs 34.5 m** at budget A, **49.9 m vs 67.1 m** at budget B
- Fine relief retained: **73 % vs 63 %** — it is *not* over-smoothed
- Gradient RMSE: **0.759 vs 0.799**
- Error spatial correlation length: **78 m vs 109 m** — its error is *less* coherent
- Static profile matching against the map localises correctly, as well as the grid

And yet navigation is worse at both budgets, at ~300× the query cost.

**The mechanism is unresolved.** Seven explanations were tested and every one was
rejected by measurement:

| Hypothesis | Test | Result |
|---|---|---|
| Over-smoothed, loses fine detail | mean \|∇\| retained vs truth | rejected — SIREN keeps **more** (73 % vs 63 %) |
| Long-range coherent warp | error autocorrelation length | rejected — SIREN is **shorter** (78 m vs 109 m) |
| Loses navigational information | exhaustive profile-match search | rejected — localises correctly, as well as the grid |
| Over-inflates variance via bigger gradients | rerun with inflation disabled | rejected — worse either way (105 vs 110 m) |
| Corrupts the inertial bias estimate | rerun with `pf2d`, which has no bias state | rejected — worse either way (108 vs 104 m) |
| Creates spurious local minima that trap the filter | count minima in the cost surface | rejected — same count as the grid (1.1) |
| Low-frequency error the filter reads as terrain | bandpass the error field | rejected — SIREN has **less** (4.1 % vs 9.7 %) |

A run inspected directly shows the filter holding a *confident* fix — 30 m
posterior spread — on a position wrong by ~100 m. So it is not losing track; it is
locking onto the wrong place and believing it. But every property of the map that
would plausibly cause that is better for the SIREN than for the grid.

The safest statement the evidence supports is the narrow one:
**elevation RMSE does not predict navigation performance, and can rank
representations in the wrong order.** Anything beyond that would be a story rather
than a finding.

### Finding 5: the cheap idea won

Switching interpolation from bilinear to bicubic — no training, no extra bytes,
about 50 ns more per query — cut median error from 72.5 m to 62.4 m and the worst
case from **771 m to 89 m**. That 8.6× reduction in tail risk is the largest
single improvement in the table, and it came from reading bytes that were already
there more carefully.

The neural result is a genuine negative result, and worth having: at these budgets
an implicit neural terrain map is *not* the win it looks like on reconstruction
metrics. Note also that the stated motivation — memory-constrained micro-drones —
is exactly where a 300× compute penalty is least affordable, since such platforms
are compute-constrained too.

## Map-error injection: what the filter actually cares about

Since elevation RMSE fails to predict navigation performance, the question is
what does. Comparing whole representations confounds many properties at once, so
`PerturbedMap` wraps the **exact** truth grid and adds a synthetic error field
whose amplitude, spatial scale, and anisotropy can be varied one at a time.

`error_injection.sh` runs the three sweeps: exact 1000×1000 grid at 30 m, ridged
terrain, flight due east, marginalised filter, no gradient inflation, 12 seeds
per cell. Sensor noise is 9.5 m throughout.

### Amplitude — how much error can it absorb?

| Injected | Map RMSE | Nav median | Diverged | Worst |
|---|---|---|---|---|
| 0 m (control) | 0.0 m | 15.8 m | 0/12 | 25.2 m |
| 5 m | 5.0 m | 20.4 m | 0/12 | 32.3 m |
| 10 m | 10.0 m | 25.4 m | 0/12 | 51.0 m |
| 20 m | 19.9 m | 50.5 m | 0/12 | 79.0 m |
| 40 m | 39.8 m | 174.9 m | **4/12** | 5 275 m |
| 80 m | 79.7 m | 536.3 m | **9/12** | 1 958 m |

Clean and monotonic, with a sharp knee. The filter absorbs map error up to about
**twice the sensor noise** with only graceful degradation, and the breakdown sits
between 20 m and 40 m — roughly **2× to 4× sensor noise**. Below that it fails
gradually; above it, it fails catastrophically.

### Spatial scale — misplaced hills, or fake boulders?

Amplitude fixed at 20 m, so **every row has identical map RMSE**.

| Wavelength | Map RMSE | Nav median | Diverged | Worst |
|---|---|---|---|---|
| 100 m | 20.0 m | 27.5 m | 1/12 | 1 841 m |
| 250 m | 19.9 m | **76.5 m** | 0/12 | 89.2 m |
| 500 m | 19.9 m | 50.5 m | 0/12 | 79.0 m |
| 1 000 m | 19.9 m | 26.8 m | 1/12 | 2 242 m |
| 2 500 m | 20.0 m | **17.2 m** | 0/12 | 46.5 m |
| 5 000 m | 19.9 m | 20.4 m | 1/12 | 2 365 m |

**This is the result.** The same RMS error is **4.5× more damaging at 250 m than
at 2 500 m**, and the dependence is not monotonic — it peaks in a middle band.
At 2 500 m the injected error is almost free: 17.2 m against a perfect-map
control of 15.8 m.

So neither extreme is the problem. Fake boulders average out; a misplaced
mountain is nearly harmless. What hurts is error at an intermediate scale.

The reading consistent with the earlier uniform-shift result is that
long-wavelength error is **common-mode** across the particle cloud, and
log-sum-exp cancels common offsets exactly; short-wavelength error decorrelates
within the cloud and behaves like extra white noise the sensor model already
tolerates; only intermediate-scale error varies coherently *across* the cloud in
a way that differentially misweights particles. That is interpretation, not
measurement — what is measured is the 4.5× swing at fixed RMSE.

### Isotropy — along-track versus cross-track

Amplitude 20 m, nominal wavelength 500 m, geometric mean held fixed.

| Aspect | λ along-track | λ cross-track | Nav median | Diverged |
|---|---|---|---|---|
| 0.125× | 177 m | 1 414 m | 10.6 m | 0/12 |
| 0.25× | 250 m | 1 000 m | 39.6 m | 2/12 |
| 0.5× | 354 m | 707 m | 67.5 m | 4/12 |
| 1× | 500 m | 500 m | 50.5 m | 0/12 |
| 2× | 707 m | 354 m | 22.2 m | 0/12 |
| 4× | 1 000 m | 250 m | 87.4 m | 0/12 |
| 8× | 1 414 m | 177 m | 47.1 m | 4/12 |

**No reliable directional effect was detected, and this sweep is confounded.**
Changing the aspect ratio necessarily changes both wavelengths, and the previous
sweep showed navigation is strongly and non-monotonically sensitive to
wavelength — so most of the variation here is explainable by the along-track and
cross-track scales moving through the damaging middle band, not by anisotropy
itself. The medians do not trend with direction, and the divergence counts point
the opposite way from the medians at 0.25× versus 4×.

The one weak hint is that the two cells with a 250 m component behave
differently depending on its orientation — 87.4 m median when it is cross-track
against 39.6 m when along-track — but with 12 seeds and divergence counts running
counter to the medians, that is not separable from noise. Answering this properly
needs a design that holds both wavelengths fixed and rotates the error field
instead, which is not what was built here.

## Where this would go next

- **A real correlation stage.** Classic TERCOM correlates a whole batch of
  profile samples at once rather than filtering sample by sample. More robust
  for initial acquisition from a cold start.
- **Terrain slope in the likelihood.** A measurement taken on a steep slope is
  much more informative than one on a flat bench; weighting by local gradient
  sharpens convergence.
- **Real DEM tiles at scale**, with tiling and caching so the map need not fit
  in memory.
- **Vision instead of radar.** Swap the altimeter for a downward camera and
  match image features against orthophotos — same filter, entirely different
  front end, and the natural bridge to the photogrammetry project.
