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
    t(s)   dead-reckon terrain-aided      spread     N_eff   roughness
     0.0         218.6         734.5       859.6      5000        68.3
    20.0         205.0          18.5        39.3      4254        62.3
   ...
   259.0         234.2           1.0        43.6      5000        86.5

result
  dead reckoning final error   234.2 m   (peak 234.2 m)
  terrain-aided final error      1.0 m
  acquired fix at               11.0 s
  mean error while holding it   22.2 m
```

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

Current results: 600 s of flight, dead reckoning ends **497 m** out while the
terrain-aided solution holds **16 m**, with a mean of 32 m once converged.

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
| `pf4d` | 1,000 | 2.363 m/s | 4.863 m/s |
| `pf4d` | 5,000 | 0.724 m/s | 1.062 m/s |
| `pf4d` | 20,000 | 0.356 m/s | 0.744 m/s |
| `pf4d` | 40,000 | 0.246 m/s | 0.675 m/s |
| **`rbpf`** | **1,000** | **0.114 m/s** | **0.273 m/s** |
| `rbpf` | 5,000 | 0.118 m/s | 0.214 m/s |

The Rao-Blackwellised filter with **1,000** particles is more than twice as
accurate as the bootstrap with **40,000** — a 40× reduction that extrapolates to
well over 100× to actually match it. It also runs marginally *faster* at equal
particle count, because sharper weights mean fewer resampling events.

Note too that `rbpf` is flat from 1,000 to 5,000 particles: it has already hit
the information limit of the measurements. Adding particles cannot help, because
the bias uncertainty is being integrated analytically rather than sampled. That
is the Rao-Blackwell variance-reduction theorem showing up as a flat line.

The bootstrap at 1,000 particles is worse than its own 3 m/s prior — with four
dimensions to cover, the cloud simply cannot span the space, and it diverges.

### What calibration buys: the coast test

Fly from ridged terrain onto a plain, lose the fix, and keep going on inertial
alone (`--terrain mixed`, 60 km map, 450 s):

| Filter | Bias error | Coast drift rate | Final position error |
|---|---|---|---|
| `pf2d` | not estimated | 0.79 m/s | 244.7 m |
| `pf4d` | 0.530 m/s | 0.58 m/s | 125.6 m |
| `rbpf` | 0.119 m/s | **0.32 m/s** | **59.6 m** |

Same terrain, same sensors, same particle count. The only difference is how well
the inertial bias was solved while the terrain was still informative — and it
shows up as a 2.5× slower error growth and a 4× better final position once the
terrain has gone quiet. That is the entire argument for co-estimating the bias.

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
| 0, 0 | 0.0 m | 3.6 m | 96.8 % |
| 10, 10 | 14.1 m | 16.7 m | 96.8 % |
| 20, 20 | 28.3 m | 30.3 m | 96.8 % |
| 40, 40 | 56.6 m | 59.6 m | 96.8 % |
| 80, 80 | 113.1 m | 115.5 m | 96.2 % |

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

| Representation | Store | Elev RMSE | Nav median | Nav worst | Query |
|---|---|---|---|---|---|
| grid 8×, bilinear | 39 KiB | 41.0 m | 72.5 m | 770.8 m | 42 ns |
| grid 8×, bicubic | 39 KiB | 34.5 m | **62.4 m** | **89.2 m** | 96 ns |
| SIREN 64×3 | 34 KiB | **26.4 m** | 102.2 m | 122.7 m | 30 458 ns |
| grid 16×, bilinear | 10 KiB | 78.3 m | 177.7 m | 427.4 m | 37 ns |
| grid 16×, bicubic | 10 KiB | 67.1 m | **152.2 m** | 3 986 m | 94 ns |
| SIREN 48×2 | 10 KiB | **49.9 m** | 1 334 m | 8 182 m | 11 333 ns |
| exact grid | 2 500 KiB | 0.0 m | 10.2 m | 21.3 m | 41 ns |

### Finding 4: better reconstruction, worse navigation

The neural map wins on every map-fidelity measure and loses on the only one that
counts:

- Elevation RMSE: **26.4 m vs 34.5 m** at budget A, **49.9 m vs 67.1 m** at budget B
- Fine relief retained: **73 % vs 63 %** — it is *not* over-smoothed
- Gradient RMSE: **0.759 vs 0.799**
- Error spatial correlation length: **78 m vs 109 m** — its error is *less* coherent
- Static profile matching against the map localises correctly, as well as the grid

And yet navigation is 1.6× worse at budget A and 9× worse at budget B, at ~300×
the query cost. Three plausible explanations were tested and rejected: it is not
over-smoothing, not a long-range coherent warp, and not a loss of map information
(a static rigid-translation profile search finds the right position with either
map). Inspecting a run directly shows the filter holding a *confident* fix — 30 m
posterior spread — on a position wrong by ~100 m, while its inertial bias estimate
diverges to 4.5 m/s against a true value of 1.2 m/s and a prior of 3.0 m/s.

The working explanation is coupling rather than accuracy: a map whose error varies
with position produces an apparent position offset that changes as the vehicle
moves, the filter attributes that changing offset to vehicle motion, and it lands
in the bias estimate — which then corrupts the prediction step. Reconstruction
error and navigation error are simply not the same quantity, and MSE training
optimises the wrong one.

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
