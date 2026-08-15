# spec: rig_space (the fingerprint as a trajectory in a collapsed latent space)

The fingerprint is not a set of categorical bars; it is a **position in a continuous
low-dimensional space, moving over time**. Categorical arms (topology, orchestrator,
worker, effort, routing, review regime, knowledge practice) cannot be navigated: you
can only hop between discrete values, which is why a per-axis recommendation is
clumsy. Collapse the arms into a continuous space and three things become well-posed:
the fingerprint **identifies** a rig (a point, "you are here"), the meters
(efficiency, misery, bloat) become **fields** over the space, and the recommendation
becomes **gradient descent** toward the better region: the vector from where you are
to where you should be.

## Four axes: three latent, one time

The rig state is 4-dimensional: three latent spatial axes plus time. Time is not
decoration; it changes two things at once, and the model must carry both.

1. **Your position moves.** Operators iterate. The old "efficiency over time" line
   chart is really your **trajectory** through the rig-space; the question is whether
   it is converging on the good region or wandering.
2. **The field moves.** The efficient region shifts as the landscape changes (a new
   model appears; opus-5 did not exist before late July). The optimum is a moving
   target, so the field is windowed in time.

So the tool is a **control problem**: two trajectories, yours and the frontier's, in a
3D latent space over time, and the recommendation is the gradient at your current
position toward the current optimum.

## Three bodies at three velocities (the temporal dynamics)

Borrowed structure (see Acknowledgments): the same three bodies that layered-affect
models track, mapped to the rig, each a position updated at its own velocity-response
scalar:

- **session = emotion**: the fast, per-task config; one point per session.
- **era = mood**: the medium body that drifts as the setup changes. The operator's
  detected eras (orchestrator/worker changes) ARE the mood moving through the space.
- **baseline = personality**: the slow body: the operator's default rig, what they
  fall back to; the long-run centroid.

Update rule, per body, discrete over the session stream (pure vector math, the way an
affect engine runs): `pos += response * (target - pos)`, where `target` is the newer,
faster body (emotion pulls mood, mood pulls personality) and `response` is that body's
velocity constant (session fast, era medium, baseline slow). Deterministic given the
constants and the ordered session positions.

## The collapse (arms -> latent coordinates)

Two implementations behind one seam, both the pattern already used for misery and the
pattern classifier: an inference/one-time step computes coordinates out of band and
writes a cache; the stdlib driver consumes coordinates deterministically.

1. **Hand-written embedding (now, sparse data).** Three interpretable latent axes,
   each arm value assigned a pre-placed vector by design (the PAD approach: pre-placed
   points, then movement between them). Working proposal for the axes:
   - **fan-out**: solo -> delegate -> workflow (how much you parallelize).
   - **firepower/cost**: haiku/fable -> sonnet -> opus (model tier and its cost).
   - **rigor**: none/automated -> agentic/sweeps -> cross-model (review intensity).
   A rig's coordinate is the combination of its arm vectors. Stdlib, fully legible.
2. **Learned embedding (later, the federation payoff).** Train a self-organizing map
   (Kohonen) on the FEDERATED rig-corpus: your rig mints to a position on a shared map
   of everyone's rigs, and the efficiency gradient is learned from the commons. This
   is the 3dl-logo method (a trained SOM minting a position from an input), so the
   fingerprint literally becomes the logo. Needs the commons for enough data; runs out
   of band (embedding + SOM), writes the same coordinate cache the driver reads.

## The recommendation

Gradient descent, in the space: at the operator's current **mood** position, the
direction of steepest improvement in the windowed field (higher efficiency, lower
misery, lower bloat), projected back onto the nearest arm-change so it is actionable.
It is `(target - current) * response` -- the same update the affect model runs -- with
the target being the current-frontier optimum rather than a fixed point. Never an axis
the operator already maxes (they are already at that coordinate).

## Visualization

The fingerprint becomes a **map, not bars**: the operator's trajectory as a path
through the 2D-projected latent space (or the SOM lattice), the current mood point
marked, the personality centroid, and an arrow toward the current optimum. The eras
are waypoints on the path. The moving frontier is a second, shifting marker.

## Determinism and portability

The coordinate cache (hand-written or SOM-minted) and the dynamics constants are
inputs; the driver's trajectory + gradient computation is a pure function of them:
same inputs, same day, same bytes. The embedding step is out of band (stdlib
hand-written now, or an inference/SOM pass later), exactly like the misery and
fingerprint-labels caches.

## Acceptance (`test_rig_space.py`)

Given fixture sessions with known arms and timestamps and a hand-written embedding:
1. each session embeds to a deterministic latent coordinate; a rig that is more
   parallel / stronger-model / higher-review sits further along fan-out / firepower /
   rigor respectively (monotonicity of the hand-written placement);
2. the three bodies update in order (session -> era -> baseline) with the given
   velocity constants, and personality moves slower than mood moves slower than
   session; determinism holds;
3. the gradient at the current mood points toward the higher-scoring region of the
   windowed field, and maps to a concrete arm-change;
4. a no-embedding run leaves the existing meters untouched (the layer is additive).

## Acknowledgments

The model borrows a **structural analogy**, and the source is credited, not lifted.
The continuous-affect-space idea -- collapsing discrete states into a low-dimensional
space you move a position through -- is the **PAD (Pleasure-Arousal-Dominance) model,
Mehrabian & Russell (1974), _An approach to environmental psychology_ (MIT Press);
Mehrabian (1996), _Current Psychology_ 14(4)**. The **layered dynamics** -- emotion /
mood / personality as three bodies at three velocities -- follows **Gebhard (2005),
_ALMA: A Layered Model of Affect_ (AAMAS)**, which builds on PAD. What Vibrant takes is
the shape, not an affect model: the underlying math (embedding a categorical state
space, gradient descent, decay/velocity trajectory updates) is general dynamical
systems and control. We reuse the shape for rig-space, and say so.
