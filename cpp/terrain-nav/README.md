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

Current results: 600 s of flight, dead reckoning ends **497 m** out while the
terrain-aided solution holds **16 m**, with a mean of 32 m once converged.

## Where this would go next

- **Estimate the inertial bias.** Extend the state to `(x, y, bias_x, bias_y)`.
  Right now the bias is absorbed into process noise, which works but throws away
  the filter's ability to *calibrate* the inertial unit — the thing that makes
  the solution keep coasting accurately after terrain runs out.
- **A real correlation stage.** Classic TERCOM correlates a whole batch of
  profile samples at once rather than filtering sample by sample. More robust
  for initial acquisition from a cold start.
- **Rao-Blackwellisation.** Keep particles only for the non-linear horizontal
  states and run an analytic Kalman update for the linear ones. Far fewer
  particles for the same accuracy.
- **Terrain slope in the likelihood.** A measurement taken on a steep slope is
  much more informative than one on a flat bench; weighting by local gradient
  sharpens convergence.
- **Real DEM tiles at scale**, with tiling and caching so the map need not fit
  in memory.
- **Vision instead of radar.** Swap the altimeter for a downward camera and
  match image features against orthophotos — same filter, entirely different
  front end, and the natural bridge to the photogrammetry project.
