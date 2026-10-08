# Verification settings — where they should live

**Status: BUILT, 2026-10-08.** The decision below was taken — yes, one setting
for the app — and all four stages landed (`NEXT_STEPS.md` §62, §63).

**One part of stage 4 was wrong and is recorded rather than quietly dropped:**
it assumed a single `VerificationPanel` would serve both tabs. They do not
render the same panel — Analysis scores one model, Comparison scores several
against each other — so stage 4 extracted Analysis's panel alone. What the two
tabs share is the settings, which is what stages 1–3 delivered.

This is the boundary `NEXT_STEPS.md` §60 stopped at. The Verification Metrics
panel is the largest remaining block in both tabs and the obvious next thing to
extract, and it cannot be extracted cleanly until it is settled where the
settings it reads actually live.

---

## 1. What the settings are

Four numbers decide what a score *means*. Every scored endpoint takes them, and
every panel in both scored tabs reads them:

| setting | what it changes | measured effect |
|---|---|---|
| **threshold** | what counts as an event | the whole contingency table |
| **lead range** (`hour_min`/`hour_max`) | which forecasts are scored | AIFS region CSI **0.363 → 0.3082** between 0–168 h and 0–240 h (§54) |
| **FSS neighbourhood** | the spatial scale FSS is judged at | UKMO region FSS **0.7912 → 0.7389** between 5 cells and 3 (§54) |
| **scored area** (`box_cells`) | how many cells the contingency table pools | one cell gave CSI 0.0833 from a single hit; the 9×9 box gave 0.2756 over 1,103 events (§41) |

They are not display options. Two readers using different values are answering
different questions, and nothing on screen says so — which is the defect this
project has now corrected three times in the same place (§41 the estimator, §54
the defaults, §55 Analysis's internal copies).

## 2. Where they live today, measured 2026-10-08

| | threshold | lead range | FSS window | box cells |
|---|---|---|---|---|
| **AnalysisTab** | 1 | 1 | 1 | 1 |
| **ComparisonTab** | **2** (point, region) | 1 | **2** (point, region) | 1 |
| shared between the tabs | **no** | **no** | **no** | **no** |

Two findings, both verified rather than inferred:

**a. Comparison still carries the defect §55 fixed in Analysis.** It holds
`threshold` and `regionThreshold`, and `fssWindow` and `regionFssWindow`. They
start equal — §54 saw to that — and diverge the moment either is touched, with
only one of each visible in each mode.

**b. The two tabs never share anything but defaults.** Tabs are hidden with
`display: none` and never unmount, so both copies stay live for the session.
Demonstrated in the running app: Analysis set to **5 mm/6h over 24–72 h**, and
the Comparison tab at that same moment still reading **0–168 h** with its own
threshold. Both panels are one click apart and neither mentions the other.

§54 unified the *starting values*. It did not and could not unify what happens
after the first keystroke.

## 3. What a fix has to respect

- **§55's merge must not be undone.** Any design that gives a panel its own
  threshold re-splits what was just merged. This is why §60 stopped: a seam
  that would undo a fix is not a seam.
- **The cyclone tab reads none of this** and must not acquire it, for the same
  reason it does not get the run selector (§53, `TAB_CONTEXT`).
- **Defaults stay in one place.** `VERIFICATION_DEFAULTS` (§54) is the source
  of the starting values whatever else changes.
- **The backend already treats these as one question.** §41 made both surfaces
  use the same estimator; the remaining divergence is entirely client-side.

## 4. The options

### A. Leave them per-tab; extend §55's merge to Comparison

Merge Comparison's two thresholds and two FSS windows, as Analysis's were.
Nothing else moves.

- Fixes finding (a); leaves (b) untouched.
- Smallest change, no new concepts, no behaviour change across tabs.
- The Verification panel still cannot be extracted without passing four
  value-and-setter pairs down, which moves lines rather than behaviour.

### B. One app-level `VerificationProvider`, mirroring `RunContext`

A provider beside `RunProvider` holding the four settings; `useVerification()`
in any panel that scores. Both tabs read and write the same values.

- Fixes (a) and (b) together: there is one threshold in the app, as there is
  one run.
- **The panel extraction falls out of it.** A verification panel reads context
  instead of props, so it can be lifted from either tab without threading
  anything through — which is the thing §60 blocked on.
- Follows a precedent the codebase already has, including its guard rail:
  `useRun()` throws outside its provider rather than defaulting, because a
  component that silently rendered without a run would send unqualified
  requests.
- **Changes behaviour**: setting a threshold in Analysis changes what
  Comparison will show. That is the decision below.

### C. A shared hook, `useVerificationSettings()`, instantiated per tab

One definition of the shape and the defaults; each tab calls it and gets its
own copy.

- Fixes (a), leaves (b) deliberately: the tabs stay independent.
- Removes the duplication of *declaration* without coupling the values.
- Half a step: the panel still takes its settings as props, so the extraction
  is still prop-threading, just tidier.

## 5. Recommendation — B

The run selector is the precedent and the argument. A forecast run qualifies
every number on screen, so it lives above the tabs and every tab reads it; a
threshold qualifies every categorical number exactly the same way. The app
already decided this question once.

It is also the only option that makes the next extraction honest. Under A or C,
`VerificationPanel` takes eight props that are really one idea; under B it
takes none, and the panel can then be shared by both tabs instead of existing
twice.

**The cost is the coupling, and it should be stated plainly:** a reader who
tunes Comparison to 5 mm/6h and switches to Analysis will find Analysis showing
5 mm/6h. I think that is right — it is the same question, and the alternative
is what we have now, which is two live answers with nothing saying so — but it
is a change in how the app behaves, not a refactor.

## 6. The decision

**Should changing a verification setting in one tab change it in the other?**

- **Yes** → option B. One threshold, one lead range, one neighbourhood, one
  box, for the whole app. Recommended.
- **No** → option C, plus A's merge inside Comparison. The tabs stay
  independent on purpose, and the two-live-answers behaviour is then a
  *decision* rather than an accident — which is worth something on its own, and
  should be said in the UI if we choose it.

## 7. If B: how it would be built

Four stages, each shippable and verifiable on its own:

1. **Merge Comparison's pairs** (option A on its own). One threshold and one
   FSS window inside that tab, exactly as §55 did for Analysis. No new
   concepts; provable with the same before/after that §55 used.
2. **Add `VerificationProvider`** beside `RunProvider` in `index.js`, holding
   the four settings seeded from `VERIFICATION_DEFAULTS`, with `useVerification()`
   throwing outside it. Nothing consumes it yet.
3. **Move each tab onto the context**, one tab per commit, deleting its local
   state as it goes. The visible change — and the one to verify in the browser
   — is that a setting changed in one tab is already set in the other.
4. **Extract `VerificationPanel` once** and use it in both tabs, which is the
   point of the exercise and is what finally takes the categorical machinery
   out of two 1,000-line components.

**What would prove it:** a test that sets a threshold through one tab's input
and asserts the other tab's input shows it (the coupling is the feature, so it
is what the test should pin); the existing `verificationDefaults.test.js`
extended to assert no component declares these as local state; and the live
check from §2 run again, expecting the opposite result.

**What would make it wrong:** if a reader genuinely wants to compare two
thresholds side by side — Analysis at 5 mm/6h against Comparison at 25 — then
B removes something they use. Nothing in the current UI offers that as a
feature, and today it happens only by accident, but it is the question worth
asking before stage 3 lands.
