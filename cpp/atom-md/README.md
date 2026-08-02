# atom-md — simulating atoms in C++

A self-contained molecular dynamics engine: 864 argon atoms in a periodic box,
interacting through a Lennard-Jones potential, integrated with velocity Verlet.
No dependencies beyond the standard library.

It is deliberately small enough to read end to end (~600 lines) but does the
things a real MD code has to do: periodic boundaries, an O(N) neighbour search,
long-range corrections, thermostats that sample the right ensemble, and a
validation suite that checks the physics rather than just the exit code.

## First, what does "simulate atoms" mean?

The word covers about six orders of magnitude in cost, and picking the wrong
level is the most expensive mistake available. Roughly, from cheapest to most
accurate:

| Level | Treats electrons? | Reach | Use it when |
|---|---|---|---|
| Classical MD (this code) | No — fitted pair/many-body potential | 10⁴–10⁹ atoms, ns–µs | Structure, diffusion, phase behaviour, mechanics |
| Reactive / machine-learned potentials | Implicitly, via a fit to QM | 10³–10⁷ atoms, ns | Bonds break and re-form |
| Tight binding / semi-empirical | Approximately | 10²–10⁴ atoms, ps | Electronic structure on a budget |
| DFT (Kohn-Sham) | Yes, mean-field | 10–10³ atoms, ps | Reaction energies, spectra, band structure |
| Quantum Monte Carlo / coupled cluster | Yes, correlated | 1–10² atoms | Benchmark accuracy |

Classical MD is the right default unless you specifically need chemistry
(bond breaking) or electrons. It is also the only level where you can write
something genuinely useful from scratch in an afternoon — the others are
years of work, and you should use VASP, Quantum ESPRESSO, PySCF, or CP2K.

If you *do* want classical MD in production rather than in a learning
exercise, use LAMMPS, GROMACS, OpenMM, or HOOMD-blue. They are heavily
optimised, parallel, and validated. This code exists to show you what those
packages are doing inside.

## Build and run

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/atom_md
```

Then check the physics:

```bash
./validate.sh
```

Useful invocations:

```bash
# canonical sampling instead of NVE
./build/atom_md --thermostat langevin --temperature 1.2

# write the radial distribution function and a trajectory you can open in VMD/OVITO
./build/atom_md --rdf gr.dat --traj traj.xyz

# a bigger system
./build/atom_md --cells 10          # 4000 atoms

# melt it
./build/atom_md --temperature 3.0 --density 0.5
```

`--help` lists every flag.

## How it works

### Reduced units

Everything is in Lennard-Jones units: σ = ε = m = 1. This keeps the arithmetic
near 1.0, which matters for floating-point accuracy, and makes results
transferable — one simulation describes every LJ fluid at that reduced state
point. Multiply back out at the end. For argon (σ = 3.405 Å, ε/k_B = 119.8 K,
m = 39.948 u):

| Quantity | Unit | Argon value |
|---|---|---|
| length | σ | 3.405 Å |
| energy | ε | 1.654 × 10⁻²¹ J |
| temperature | ε/k_B | 119.8 K |
| time | σ√(m/ε) | 2.156 ps |
| pressure | ε/σ³ | 41.9 MPa |

The program prints both the reduced values and the argon mapping.

### The potential

```
U(r) = 4ε[(σ/r)¹² − (σ/r)⁶]
```

The r⁻⁶ term is the attractive dispersion interaction, and it is real physics.
The r⁻¹² repulsion is not — it is a computational convenience, chosen because
it is the square of the r⁻⁶ term and therefore free once you have computed it.
Nothing about quantum mechanics says 12.

Forces come from the analytic derivative, never finite differences:

```
F(r)/r = 24ε(2(σ/r)¹² − (σ/r)⁶)/r²
```

Working with `F/r` and the displacement vector avoids a `sqrt` in the inner
loop. The whole kernel needs only `r²`.

### Cutoff, shift, and tail

Evaluating every pair is O(N²) and pointless — the potential is negligible past
a few σ. We cut off at 2.5σ. Two corrections follow:

- **Shift.** Truncating leaves a discontinuity at r_c, and a discontinuous
  potential means an impulsive force that quietly injects energy. We subtract
  U(r_c) so the potential goes to zero continuously.
- **Tail correction.** The energy and pressure we discarded past r_c are
  recovered analytically, assuming g(r) = 1 out there. These are constants, so
  they shift reported energies without touching the dynamics.

### Periodic boundaries

864 atoms in a box is mostly surface. Periodic boundaries remove the surface
entirely: the box tiles space infinitely, and an atom leaving one face re-enters
the opposite one. Interactions use the **minimum image convention** — each pair
interacts through the nearest periodic copy:

```cpp
d.x -= box * std::nearbyint(d.x / box);
```

This is only unambiguous if the box is at least twice the cutoff, which the
constructor enforces.

### Integration: velocity Verlet

```
v(t + ½dt) = v(t) + (dt/2)·F(t)/m
r(t + dt)  = r(t) + dt·v(t + ½dt)
F(t + dt)  = −∇U(r(t + dt))
v(t + dt)  = v(t + ½dt) + (dt/2)·F(t + dt)/m
```

Verlet-family integrators dominate MD not because they are accurate — they are
only second order — but because they are **symplectic**: they exactly conserve a
quantity close to the true energy, so error stays bounded over millions of steps
instead of drifting. A 4th-order Runge-Kutta is locally more accurate and
useless here, because its energy error accumulates without bound.

One force evaluation per step. That force evaluation is ~95% of the runtime, so
everything else is noise.

### Neighbour search: cell lists

The naive pair loop is O(N²). Since interactions vanish past r_c, bin atoms into
cells of side ≥ r_c and only check an atom against its own cell and the 26
neighbours. Visiting only the **13 forward** neighbours plus the i<j pairs inside
each cell touches every pair exactly once, which halves the work again.

Storage is the classic linked-cell trick: `head_[cell]` is the first atom in a
cell, `next_[i]` the next atom in the same cell, terminated by −1. Two `int`
arrays, no allocation per step.

Measured on this machine, 200 steps:

| Atoms | Cell list | All pairs | Speedup |
|---|---|---|---|
| 256 | 0.09 s | 0.09 s | 1.0× |
| 864 | 0.47 s | 0.86 s | 1.8× |
| 2048 | 1.37 s | 4.45 s | 3.2× |
| 4000 | 3.27 s | 16.65 s | 5.1× |

The crossover is around a few hundred atoms; the gap widens without bound.

### Temperature control

Temperature comes from the equipartition theorem — it is a *measurement*, not a
setting:

```
T = 2·KE / ((3N − 3)·k_B)
```

The −3 accounts for the centre-of-mass momentum we froze at startup. Forget it
and every reported temperature is wrong by a factor of 3N/(3N−3), which is
small, embarrassing, and hard to spot.

Three options:

- **`none`** — pure NVE. Constant energy. The honest baseline.
- **`berendsen`** (default) — rescales velocities toward the target with a weak
  coupling constant. Robust for equilibration but it does **not** sample a
  correct canonical ensemble, so this code uses it only before production and
  then switches to NVE to measure.
- **`langevin`** — adds friction and matched noise via the BAOAB splitting.
  Genuinely samples the canonical ensemble, so it stays on during production.

The Berendsen caveat is not pedantry. Its suppressed energy fluctuations
produce wrong heat capacities and, in the worst case, the "flying ice cube"
artifact where kinetic energy drains into centre-of-mass motion.

## Validating it

MD is unusually easy to get subtly wrong: a sign error in the force, a missing
minimum image, a double-counted pair. All of them produce output that looks
plausible. `validate.sh` checks the things that would catch them:

1. **Cell list ≡ brute force.** The two neighbour-search paths must produce
   identical trajectories over 700 steps. This catches double-counted or missed
   pairs, which is the single most likely cell-list bug.
2. **Energy conservation and its scaling.** In NVE the total energy must be flat
   (< 10⁻⁴ relative drift), and halving dt must reduce the drift ~4×, confirming
   the integrator really is second order. Measured: 3.6e-05 → 9.8e-06 → 2.8e-06
   → 7.1e-07 for dt = 0.008 → 0.001.
3. **Thermostat accuracy.** Langevin must reach the requested temperature across
   T* = 0.6, 1.2, 2.0.
4. **Structure.** g(r) must be zero inside the repulsive core and show the liquid
   first-shell peak near 1.1σ.

The default state point (ρ* = 0.8442, T* = 0.722) is the Verlet/Rahman argon
benchmark, so the numbers are checkable against 1967 literature. This code gives
PE/atom ≈ −5.64 and a first g(r) peak of 3.02 at r = 1.10σ, both in the expected
range.

Energy conservation is the sharpest single test. If it holds to 10⁻⁵ over
thousands of steps, your forces are almost certainly the exact analytic gradient
of your potential, because nothing else conserves energy by accident.

## Where this would go next

In rough order of value:

- **Neighbour (Verlet) lists** with a skin distance on top of the cell list —
  rebuild every ~10-20 steps instead of every step. Typically another 2-3×.
- **Threading.** The pair loop parallelises well with OpenMP, though the
  `forces_[j] -= f` write needs per-thread force buffers or a full (non-half)
  neighbour list.
- **SIMD.** Structure-of-arrays layout instead of `std::vector<Vec3>` lets the
  inner loop vectorise.
- **Electrostatics.** Charged systems need Ewald summation or PME, because the
  Coulomb r⁻¹ tail cannot be cut off. This is the single biggest jump in
  complexity toward a real MD code.
- **Bonded interactions** — bonds, angles, dihedrals — to get from noble gases
  to molecules.
- **Better potentials.** EAM for metals, Tersoff/Stillinger-Weber for
  semiconductors, or a machine-learned potential for near-QM accuracy.
