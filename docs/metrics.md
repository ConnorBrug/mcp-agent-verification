# Metrics

Definitions for the three metrics reported for RQ1 (translation faithfulness). Math uses GitHub
LaTeX syntax.

## Notation

| Symbol | Meaning |
|---|---|
| $S$ | Set of tool-schema scenarios. Each $s \in S$ has one hand-written reference model $R_s$. |
| $G_s$ | Generated models for scenario $s$ (one per LLM run). $G = \bigcup_{s \in S} G_s$. |
| $\mathrm{ref}(g)$ | The reference model for generated model $g$: $\mathrm{ref}(g) = R_s$ for $g \in G_s$. |
| $P$ | Property set, the `LTLSPEC`s in `properties/safety.ltl`. Currently $\lvert P \rvert = 3$. |
| $V_I$ | Interface variables from `docs/interface.md`: `action`, `tainted`, `confirmed`, `privileged`, `grant`. |
| $\sigma\vert_{V_I}$ | A state $\sigma$ restricted to the interface variables. |
| $[\,\cdot\,]$ | Indicator: 1 if the condition is true, 0 otherwise. |

## 1. Parse rate

$$
\mathrm{parse}(g) = \big[\, \text{nuXmv builds } g \text{ with } P \text{ appended, exits 0, and reports a verdict for every } \varphi \in P \,\big]
$$

A model that runs but omits or mistypes an interface variable fails this test, because the
appended properties will not resolve.

$$
\mathrm{PR} = \frac{1}{\lvert G \rvert} \sum_{g \in G} \mathrm{parse}(g)
$$

## 2. Verdict agreement rate

For a model $M$ that parses and a property $\varphi \in P$, let
$v_M(\varphi) \in \{\top, \bot\}$ be nuXmv's verdict ($\top$ means $M \models \varphi$).

Per-model agreement:

$$
A(g) =
\begin{cases}
\dfrac{1}{\lvert P \rvert} \displaystyle\sum_{\varphi \in P} \big[\, v_g(\varphi) = v_{\mathrm{ref}(g)}(\varphi) \,\big] & \text{if } \mathrm{parse}(g) = 1 \\[2ex]
0 & \text{otherwise}
\end{cases}
$$

Reported two ways. The strict rate counts a non-parsing model as full disagreement. The
conditional rate is over parsing models only.

$$
\mathrm{VA} = \frac{1}{\lvert G \rvert} \sum_{g \in G} A(g)
\qquad
\mathrm{VA}_{\mathrm{parsed}} = \frac{\sum_{g \in G} A(g)}{\sum_{g \in G} \mathrm{parse}(g)}
$$

These satisfy $\mathrm{VA} = \mathrm{PR} \cdot \mathrm{VA}_{\mathrm{parsed}}$.

Diagnostic: the false-safe rate, the share of reference violations the generated model reports as
safe. This is the error that hides real bugs.

$$
\mathrm{FS} = \frac{\big\lvert \{ (g, \varphi) : \mathrm{parse}(g) = 1,\ v_g(\varphi) = \top,\ v_{\mathrm{ref}(g)}(\varphi) = \bot \} \big\rvert}
                   {\big\lvert \{ (g, \varphi) : \mathrm{parse}(g) = 1,\ v_{\mathrm{ref}(g)}(\varphi) = \bot \} \big\rvert}
$$

## 3. Trace admissibility

Let $C_s$ be the counterexamples nuXmv produces on $R_s$ over $P$, parsed by
`eval/parse_trace.py`. Each $\pi \in C_s$ is a finite sequence $\pi_0, \dots, \pi_{k-1}$ of
interface valuations, $k = \lvert \pi \rvert$.

Generated model $g$ admits $\pi$ if some path of $g$ from an initial state matches $\pi$ on the
interface variables at every step:

$$
\mathrm{adm}(g, \pi) = \Big[\, \exists\, \sigma_0 \sigma_1 \cdots \sigma_{k-1} \text{ path of } g,\ \sigma_0 \in I_g,\ \forall i < k:\ \sigma_i\vert_{V_I} = \pi_i \,\Big]
$$

$$
\mathrm{TA}(g) = \frac{1}{\lvert C_{\mathrm{ref}(g)} \rvert} \sum_{\pi \in C_{\mathrm{ref}(g)}} \mathrm{adm}(g, \pi)
\qquad
\mathrm{TA} = \frac{1}{\lvert G' \rvert} \sum_{g \in G'} \mathrm{TA}(g)
$$

where $G' = \{ g \in G : \mathrm{parse}(g) = 1,\ C_{\mathrm{ref}(g)} \neq \emptyset \}$.
Guarded references produce no counterexamples, so their generated models are not in $G'$.

Why the finite prefix is enough: all three properties in $P$ are safety properties, so each
violation is witnessed by a finite bad prefix. Every counterexample $\pi$ contains one. If $g$
admits $\pi$ and has a total transition relation (required by `docs/interface.md`), the prefix
extends to an infinite path of $g$ that violates the same property.

How to compute $\mathrm{adm}(g, \pi)$ with nuXmv: let $c_i$ be the conjunction
$\bigwedge_{v \in V_I} (v = \pi_i(v))$ and check

$$
g \models \neg\, \big( c_0 \wedge \mathbf{X}(c_1 \wedge \mathbf{X}(c_2 \wedge \cdots \mathbf{X}\, c_{k-1})) \big)
$$

$\mathrm{adm}(g, \pi) = 1$ exactly when this spec is **false**, i.e. nuXmv finds a path realizing
$\pi$.
