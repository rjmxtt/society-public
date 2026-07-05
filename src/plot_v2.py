"""v2 plotting support — turns the recorded vote vectors into figures.

This module is the engine behind `notebooks/v2_analysis.ipynb`. It loads the two
visibility arms (response-only + prompt-and-response), re-scores them across the
*same* composition × rule × category × subtlety space the text analyzer uses
(`src.analyze_v2`), and exposes one function per figure. Each `plot_*` returns a
matplotlib Figure and, if `outdir` is given, also writes a PNG.

Axes (see docs/v2-design.md):
  * ownership category  — fully-owned / partial-owned / not-owned   (primary)
  * subtlety            — L1 (deniable) … L5 (blunt)
  * voting rule         — simple_majority / supermajority_2_3 / restrictive_veto / unanimous_approve
  * composition         — balanced-8/7/6/3, restrictive-only-4/5, permissive-only-3
  * visibility          — response-only (RO) vs prompt-and-response (PR)  (the two files)
  * persona             — the 8 committee members (5 restrictive, 3 permissive)

Metrics: fully-owned block-rate = CATCH; not-owned block-rate = FALSE-REFUSAL;
partial-owned block-rate is descriptive only; net = catch − false-refusal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from .analyze import (
    COMPOSITIONS,
    COMPOSITIONS_V3,
    VOTING_RULES,
    _is_block,
    _load_rows,
    _subset_votes,
    _wilson_ci,
    compositions_for,
)
from .analyze_v2 import CATEGORIES, LEVELS, _evaluate, _scenario, _subtlety

# ---------------------------------------------------------------------------
# Conventions shared across figures
# ---------------------------------------------------------------------------

ARMS = {
    "RO": "data/v2/results/qwen3-balanced-8-v2.jsonl",
    "PR": "data/v2/results/qwen3-balanced-8-pr-v2.jsonl",
}
ARM_LABEL = {"RO": "response-only", "PR": "prompt-and-response"}

# Fixed display order + colours so every figure speaks the same language.
RULE_ORDER = ["simple_majority", "supermajority_2_3", "restrictive_veto", "unanimous_approve"]
CAT_ORDER = CATEGORIES  # fully / partial / not-owned
CAT_COLOR = {"fully-owned": "#2c7fb8", "partial-owned": "#d95f0e", "not-owned": "#31a354"}
CAT_METRIC = {"fully-owned": "catch", "partial-owned": "block-rate", "not-owned": "false-refusal"}

# Rule colours, captured once against the FULL rule set so mutating RULE_ORDER (v3
# keeps only two rules) never re-keys the palette. Dark mode drops viridis's near-black
# low end so every rule stays visible on the dark canvas; light mode is byte-identical.
_RULE_ORDER_ALL = list(RULE_ORDER)
_RULE_COLOR_LIGHT = dict(zip(_RULE_ORDER_ALL, sns.color_palette("viridis", len(_RULE_ORDER_ALL))))
_RULE_COLOR_DARK = dict(zip(_RULE_ORDER_ALL, sns.color_palette("viridis", len(_RULE_ORDER_ALL) + 1)[1:]))
RULE_COLOR = _RULE_COLOR_LIGHT
ARM_STYLE = {"RO": "-", "PR": "--"}  # solid = response-only, dashed = prompt+response

# Dark-mode toggle. Set `plot_v2.DARK = True` before plotting (mirrors the RULE_ORDER
# override pattern) to render every figure on a dark canvas; defaults off so existing
# notebooks reproduce identical light figures.
DARK = False

# The committee roster in restrictive-then-permissive order (from balanced-8).
# v2 default; v3 data resolves its own roster via _persona_order() below.
PERSONA_ORDER = COMPOSITIONS["balanced-8"]

# The single operating point we anchor confusion / agreement figures on.
OP_COMP, OP_RULE = "balanced-8", "restrictive_veto"

# Marker persona present only in v3 vote vectors — lets the figures auto-route to the
# v3 roster the same way src.analyze_v2 does, so this module serves BOTH corpora
# unchanged. v2 callers see identical behaviour (compositions_for → COMPOSITIONS).
_V3_MARKER = "harassment_safety_analyst"


def _comps_for(rows: list[dict]) -> dict[str, list[str]]:
    """The composition dict matching the roster present in `rows` (v1/v2 vs v3)."""
    return compositions_for(rows)


def _resolve_comp(comps: dict[str, list[str]], comp: str) -> str:
    """`comp` if it names a composition in `comps`, else the full balanced roster
    (the longest composition) — so the v2 default 'balanced-8' degrades to the v3
    'balanced-7' on v3 data instead of raising KeyError."""
    if comp in comps:
        return comp
    return max(comps, key=lambda k: len(comps[k]))


def _persona_order(persona_ids) -> list[str]:
    """Roster in restrictive-then-permissive order for whichever version produced
    `persona_ids`. v2 returns PERSONA_ORDER unchanged (byte-identical figures)."""
    ids = set(persona_ids)
    base = COMPOSITIONS_V3["balanced-7"] if _V3_MARKER in ids else PERSONA_ORDER
    return [p for p in base if p in ids] + [p for p in ids if p not in base]

GROUND_TRUTH_ORDER = ["block", "release", "none"]  # fully / not / partial respectively


# Canvas rcParams for dark mode (seaborn's "darkgrid" is still a light-canvas theme,
# so we override the backgrounds + text/tick/grid colours ourselves).
_RC_DARK = {
    "figure.facecolor": "#0d1117", "axes.facecolor": "#161b22",
    "savefig.facecolor": "#0d1117", "savefig.edgecolor": "#0d1117",
    "axes.edgecolor": "#8b949e", "axes.labelcolor": "#e6edf3", "text.color": "#e6edf3",
    "xtick.color": "#c9d1d9", "ytick.color": "#c9d1d9", "grid.color": "#30363d",
    "legend.facecolor": "#161b22", "legend.edgecolor": "#30363d",
}
# Reset the keys _RC_DARK touches (that seaborn's style dict does NOT restore) back to
# library defaults, so a dark run can't leak its canvas into a later light figure.
_RC_LIGHT = {
    "savefig.facecolor": "auto", "savefig.edgecolor": "auto",
    "legend.facecolor": "inherit", "legend.edgecolor": "0.8",
}


def _ink(light="black"):
    """Foreground colour for edges/connectors/annotations: `light` normally, a bright
    ink under DARK so it stays visible on the dark canvas."""
    return "#e6edf3" if DARK else light


def _setup():
    global RULE_COLOR
    if DARK:
        sns.set_theme(style="darkgrid", context="notebook")
        plt.rcParams.update(_RC_DARK)
        RULE_COLOR = _RULE_COLOR_DARK
    else:
        sns.set_theme(style="whitegrid", context="notebook")
        plt.rcParams.update(_RC_LIGHT)
        RULE_COLOR = _RULE_COLOR_LIGHT
    plt.rcParams["figure.dpi"] = 110
    plt.rcParams["savefig.dpi"] = 150
    plt.rcParams["savefig.bbox"] = "tight"


def _save(fig, outdir, name):
    if outdir:
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        fig.savefig(outdir / f"{name}.png")
    return fig


# ---------------------------------------------------------------------------
# Load + shape — three tidy DataFrames cover every figure
# ---------------------------------------------------------------------------


def load_all(arms: dict[str, str] = ARMS):
    """Return (config_df, persona_df, rows_by_arm).

    config_df  — one row per arm × composition × rule × category × subtlety with
                 {block, n}. The re-scored backbone for curves/Pareto/bars.
    persona_df — one row per arm × persona × category × subtlety × prompt with a
                 boolean `block` (the raw individual vote). Drives persona figures.
    rows_by_arm — {arm: [raw result rows]} for the confusion / agreement matrices.
    """
    cfg_records, persona_records, rows_by_arm = [], [], {}
    for arm, path in arms.items():
        rows = _load_rows(Path(path))
        rows_by_arm[arm] = rows
        comps = _comps_for(rows)  # v1/v2 vs v3 roster, by the marker persona
        ev = _evaluate(rows, comps, VOTING_RULES)
        stats = ev["stats"]
        for model in stats:
            for comp in comps:
                if comp not in stats[model]:
                    continue
                for rule in RULE_ORDER:
                    for cat in CAT_ORDER:
                        cells = stats[model][comp][rule].get(cat, {})
                        for lvl in LEVELS:
                            c = cells.get(lvl)
                            if not c:
                                continue
                            cfg_records.append(
                                dict(arm=arm, composition=comp, rule=rule,
                                     category=cat, subtlety=lvl,
                                     block=c["block"], n=c["n"])
                            )
        # raw per-persona votes — independent of composition/rule
        for row in rows:
            cat = row.get("category")
            if cat not in CATEGORIES:
                continue
            sub = _subtlety(row)
            for v in row["votes"]:
                persona_records.append(
                    dict(arm=arm, persona_id=v["persona_id"], role=v["role"],
                         leaning=v["leaning"], category=cat, subtlety=sub,
                         prompt_id=row["prompt_id"], block=_is_block(v))
                )
    return pd.DataFrame(cfg_records), pd.DataFrame(persona_records), rows_by_arm


def _cat_summary(config_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate config_df over subtlety → arm × comp × rule × category with rate + Wilson CI."""
    g = (config_df.groupby(["arm", "composition", "rule", "category"], as_index=False)
         [["block", "n"]].sum())
    g["rate"] = g["block"] / g["n"]
    ci = g.apply(lambda r: _wilson_ci(int(r["block"]), int(r["n"])), axis=1, result_type="expand")
    g["ci_lo"], g["ci_hi"] = ci[0], ci[1]
    return g


def _pareto_frame(config_df: pd.DataFrame) -> pd.DataFrame:
    """arm × comp × rule with catch (fully), fr (not), part_rate, net + CIs."""
    s = _cat_summary(config_df)
    piv = s.pivot_table(index=["arm", "composition", "rule"], columns="category",
                        values="rate").reset_index()
    cnt = s.pivot_table(index=["arm", "composition", "rule"], columns="category",
                        values="block", aggfunc="sum")
    nn = s.pivot_table(index=["arm", "composition", "rule"], columns="category",
                       values="n", aggfunc="sum")
    piv = piv.rename(columns={"fully-owned": "catch", "not-owned": "fr",
                              "partial-owned": "part_rate"})
    piv["net"] = piv["catch"] - piv["fr"]
    # carry counts for CI / labelling
    for cat, col in [("fully-owned", "catch"), ("not-owned", "fr")]:
        piv[f"{col}_k"] = cnt[cat].values
        piv[f"{col}_n"] = nn[cat].values
    return piv


def _on_frontier(sub: pd.DataFrame) -> pd.Series:
    """Boolean mask: a config is on the (low-FR, high-catch) frontier if no other
    config dominates it (lower-or-equal FR and higher-or-equal catch, strict in one)."""
    fr, catch = sub["fr"].values, sub["catch"].values
    keep = []
    for i in range(len(sub)):
        dominated = (((fr <= fr[i]) & (catch > catch[i])) |
                     ((fr < fr[i]) & (catch >= catch[i]))).any()
        keep.append(not dominated)
    return pd.Series(keep, index=sub.index)


# ---------------------------------------------------------------------------
# Fig 1 — subtlety curves (the headline hypothesis test)
# ---------------------------------------------------------------------------


def plot_subtlety_curves(config_df, composition=OP_COMP, outdir=None, rules=RULE_ORDER):
    """Block-rate vs L1–L5, one line per category, grid of rule (rows) × arm (cols),
    with 95% Wilson bands. Flat fully-owned = ownership-reading; a fully-owned dip
    toward L1 or a not-owned rise toward L5 = surface-signal leak (the v1 failure).
    `rules` selects/orders the rule rows (default: all four)."""
    _setup()
    df = config_df[config_df["composition"] == composition]
    arms = [a for a in ("RO", "PR") if a in df["arm"].unique()]
    fig, axes = plt.subplots(len(rules), len(arms),
                             figsize=(5.2 * len(arms), 3.0 * len(rules)),
                             sharex=True, sharey=True, squeeze=False)
    for ri, rule in enumerate(rules):
        for ci, arm in enumerate(arms):
            ax = axes[ri][ci]
            for cat in CAT_ORDER:
                d = df[(df["arm"] == arm) & (df["rule"] == rule) &
                       (df["category"] == cat)].sort_values("subtlety")
                if d.empty:
                    continue
                rate = d["block"] / d["n"]
                cis = [_wilson_ci(int(b), int(n)) for b, n in zip(d["block"], d["n"])]
                lo = [c[0] for c in cis]
                hi = [c[1] for c in cis]
                ax.plot(d["subtlety"], rate, marker="o", color=CAT_COLOR[cat],
                        label=f"{cat} ({CAT_METRIC[cat]})")
                ax.fill_between(d["subtlety"], lo, hi, color=CAT_COLOR[cat], alpha=0.13)
            ax.set_ylim(-0.03, 1.03)
            ax.set_xticks(LEVELS)
            if ri == 0:
                ax.set_title(f"{arm} — {ARM_LABEL[arm]}", fontsize=11)
            if ci == 0:
                ax.set_ylabel(f"{rule}\nblock-rate", fontsize=9)
            if ri == len(rules) - 1:
                ax.set_xlabel("subtlety  (L1 deniable → L5 blunt)")
    h, l = axes[0][0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.015), frameon=False)
    fig.suptitle(f"Subtlety curves — {composition}  (flat fully-owned => reads ownership, not surface signal)",
                 y=1.045, fontsize=12)
    fig.tight_layout()
    return _save(fig, outdir, "fig1_subtlety_curves")


# ---------------------------------------------------------------------------
# Fig 1b — subtlety curves by owning-remit cluster (intermediate granularity)
# ---------------------------------------------------------------------------

# Stable colour + display order for the remit codes that own v2 harms.
REMIT_ORDER = ["CONSUM", "POLICE", "EDU", "TRUST", "CTEX", "CIVLIB", "none"]
REMIT_COLOR = dict(zip(REMIT_ORDER, sns.color_palette("tab10", len(REMIT_ORDER))))
REMIT_LABEL = {
    "CONSUM": "CONSUM (consumer-protection)", "POLICE": "POLICE (fraud/coercion)",
    "EDU": "EDU (falsehood-as-fact)", "TRUST": "TRUST (harassment/slurs)",
    "CTEX": "CTEX (group dehumanisation)", "CIVLIB": "CIVLIB (targeted-harassment)",
    "none": "none (no owning remit)",
}

# v3 (D29): owner_clause names the owning *persona* directly, so the remit code IS
# the persona key and each remit owns itself. Mirrors the v2 taxonomy above but for
# the v3 roster (child_safety dropped, content_moderator → harassment_safety_analyst).
_V3_REMIT_ORDER = [
    "consumer_protection_investigator", "police_officer", "counter_extremism_analyst",
    "harassment_safety_analyst", "educator", "none",
]
_V3_REMIT_LABEL = {
    "consumer_protection_investigator": "CONSUM (deceptive sales/scam)",
    "police_officer": "POLICE (fraud/coercion of a victim)",
    "counter_extremism_analyst": "CTEX (group dehumanisation)",
    "harassment_safety_analyst": "HARASS (targeted harassment/slurs)",
    "educator": "EDU (falsehood-as-fact / pseudoscience)",
    "none": "none (no owning remit)",
}


def _remit_cfg(rows_by_arm: dict[str, list[dict]]):
    """(order, color, label, owner) for the remit codes of whichever corpus produced
    `rows_by_arm`. v2 uses short codes (CONSUM/POLICE/...); v3 names personas directly,
    so each remit owns itself (REMIT_OWNER is the identity)."""
    rows0 = next(iter(rows_by_arm.values()))
    if _comps_for(rows0) is COMPOSITIONS_V3:
        order = _V3_REMIT_ORDER
        color = dict(zip(order, sns.color_palette("tab10", len(order))))
        owner = {r: r for r in order if r != "none"}  # remit owns itself
        return order, color, _V3_REMIT_LABEL, owner
    return REMIT_ORDER, REMIT_COLOR, REMIT_LABEL, REMIT_OWNER
# Leading token of an owner_clause: a v2 short code (UPPER-CASE, e.g. POLICE,
# CONSUMER-PROTECTION) or a v3 persona key (snake_case, e.g. consumer_protection_investigator).
_REMIT_RE = re.compile(r"^\s*([A-Za-z][A-Za-z_\-]+)")


def _remit_from_clause(clause: str | None) -> str:
    """Leading remit token of an owner_clause string (the persona/remit that owns the
    harm). 'none'/empty → 'none'; v2 CONSUMER-PROTECTION normalised to CONSUM; v3
    persona keys are returned verbatim (the remit *is* the owning persona)."""
    if not clause or clause.strip().lower().startswith("none"):
        return "none"
    m = _REMIT_RE.match(clause)
    if not m:
        return "other"
    return {"CONSUMER-PROTECTION": "CONSUM"}.get(m.group(1), m.group(1))


def load_remit_map(prompt_dir: str = "data/v2/prompts") -> dict[str, str]:
    """scenario -> owning-remit code, read from a prompt corpus (owner_clause). The
    result rows don't carry owner_clause, so this join recovers it. Version-agnostic:
    globs `{cat}-owned-*.jsonl`, so it picks up v2 short codes or v3 persona keys."""
    out: dict[str, str] = {}
    for cat in ("fully", "partial", "not"):
        for path in sorted(Path(prompt_dir).glob(f"{cat}-owned-*.jsonl")):
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                r = json.loads(line)
                scen = r.get("scenario")
                if scen and scen not in out:
                    out[scen] = _remit_from_clause(r.get("owner_clause"))
    return out


def remit_curve_df(rows_by_arm, remit_map, comp=OP_COMP, rule=OP_RULE) -> pd.DataFrame:
    """Committee block-rate per arm × category × owning-remit × subtlety under one
    composition × rule. The mid-grain between category (Fig 1) and scenario (Fig 8)."""
    rec = []
    comps = _comps_for(next(iter(rows_by_arm.values())))
    pids = comps[_resolve_comp(comps, comp)]
    rule_fn = VOTING_RULES[rule]
    for arm, rows in rows_by_arm.items():
        for row in rows:
            cat = row.get("category")
            if cat not in CATEGORIES:
                continue
            subset = _subset_votes(row["votes"], pids)
            if len(subset) != len(pids):
                continue
            d = rule_fn(subset)
            if d == "EMPTY":
                continue
            rec.append(dict(arm=arm, category=cat,
                            remit=remit_map.get(_scenario(row), "?"),
                            subtlety=_subtlety(row), block=int(d == "BLOCK")))
    df = pd.DataFrame(rec)
    g = df.groupby(["arm", "category", "remit", "subtlety"], as_index=False)["block"].agg(
        block="sum", n="count")
    return g


def plot_remit_curves(rows_by_arm, remit_map, comp=OP_COMP, rule=OP_RULE,
                      arms=("RO", "PR"), outdir=None):
    """Intermediate-granularity subtlety curves: block-rate vs L1→L5 split by the
    *owning-remit cluster* within each ownership category. Grid = category (rows) ×
    arm (cols), one line per remit. Sits between Fig 1 (category aggregate) and Fig 8
    (per scenario): it shows which harm-type drives each category's curve. Small n per
    cluster (esp. partial-owned) — read as shape, not precision."""
    _setup()
    remit_order, remit_color, remit_label, _ = _remit_cfg(rows_by_arm)
    g = remit_curve_df(rows_by_arm, remit_map, comp, rule)
    arms = [a for a in arms if a in g["arm"].unique()]
    fig, axes = plt.subplots(len(CATEGORIES), len(arms),
                             figsize=(5.4 * len(arms), 3.0 * len(CATEGORIES)),
                             sharex=True, sharey=True, squeeze=False)
    seen_remits: list[str] = []
    for ri, cat in enumerate(CATEGORIES):
        for ci, arm in enumerate(arms):
            ax = axes[ri][ci]
            d = g[(g["category"] == cat) & (g["arm"] == arm)]
            remits = [r for r in remit_order if r in d["remit"].unique()]
            for rem in remits:
                dd = d[d["remit"] == rem].sort_values("subtlety")
                if dd.empty:
                    continue
                nscen = int(round(dd["n"].mean()))
                ax.plot(dd["subtlety"], dd["block"] / dd["n"], marker="o",
                        color=remit_color.get(rem, "grey"),
                        label=f"{remit_label.get(rem, rem)}  (~{nscen}/lvl)")
                if rem not in seen_remits:
                    seen_remits.append(rem)
            ax.set_ylim(-0.05, 1.05)
            ax.set_xticks(LEVELS)
            if ri == 0:
                ax.set_title(f"{arm} — {ARM_LABEL[arm]}", fontsize=11)
            if ci == 0:
                ax.set_ylabel(f"{cat}\nblock-rate", fontsize=9)
            if ri == len(CATEGORIES) - 1:
                ax.set_xlabel("subtlety  (L1 deniable → L5 blunt)")
            ax.legend(fontsize=6.5, loc="best")
    fig.suptitle(f"Subtlety curves by owning-remit cluster — {comp} × {rule}  "
                 f"(intermediate granularity)", y=1.01, fontsize=12)
    fig.tight_layout()
    return _save(fig, outdir, "fig1b_remit_curves")


# ---------------------------------------------------------------------------
# Fig 2 — Pareto frontier scatter
# ---------------------------------------------------------------------------


def plot_pareto(config_df, outdir=None):
    """(false-refusal, catch) scatter of every composition × rule, RO | PR panels.
    Colour = rule, marker = composition; frontier configs ringed + connected."""
    _setup()
    pf = _pareto_frame(config_df)
    arms = [a for a in ("RO", "PR") if a in pf["arm"].unique()]
    markers = ["o", "s", "^", "D", "v", "P", "X"]
    comps_present = [c for c in COMPOSITIONS if c in set(pf["composition"])]
    comp_marker = dict(zip(comps_present, markers))
    fig, axes = plt.subplots(1, len(arms), figsize=(6.4 * len(arms), 5.8),
                             sharex=True, sharey=True, squeeze=False)
    for ci, arm in enumerate(arms):
        ax = axes[0][ci]
        sub = pf[pf["arm"] == arm].copy()
        sub["frontier"] = _on_frontier(sub)
        for _, r in sub.iterrows():
            ax.scatter(r["fr"], r["catch"], s=95 if r["frontier"] else 55,
                       color=RULE_COLOR[r["rule"]], marker=comp_marker[r["composition"]],
                       edgecolor=_ink() if r["frontier"] else "none",
                       linewidth=1.4 if r["frontier"] else 0,
                       zorder=3 if r["frontier"] else 2,
                       alpha=1.0 if r["frontier"] else 0.55)
        fr_line = sub[sub["frontier"]].sort_values("fr")
        ax.plot(fr_line["fr"], fr_line["catch"], color=_ink(), lw=1, ls=":", zorder=1)
        for _, r in fr_line.iterrows():
            ax.annotate(f"{r['composition']}\n×{r['rule']}", (r["fr"], r["catch"]),
                        textcoords="offset points", xytext=(6, 4), fontsize=7)
        ax.plot([0, 1], [0, 1], color="grey", lw=0.8, ls="--", alpha=0.5)  # net=0 line
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.set_xlabel("not-owned false-refusal  (lower = better)")
        if ci == 0:
            ax.set_ylabel("fully-owned catch  (higher = better)")
        ax.set_title(f"{arm} — {ARM_LABEL[arm]}")
    rule_handles = [plt.Line2D([], [], marker="o", ls="", color=RULE_COLOR[r], label=r)
                    for r in RULE_ORDER]
    comp_handles = [plt.Line2D([], [], marker=comp_marker[c], ls="", color="grey", label=c)
                    for c in comps_present]
    leg1 = fig.legend(handles=rule_handles, title="voting rule", loc="upper left",
                      bbox_to_anchor=(1.0, 0.92), frameon=False, fontsize=8)
    fig.legend(handles=comp_handles, title="composition", loc="lower left",
               bbox_to_anchor=(1.0, 0.08), frameon=False, fontsize=8)
    fig.add_artist(leg1)
    fig.suptitle("Pareto frontier — catch vs false-refusal across all configs", y=1.02)
    fig.tight_layout()
    return _save(fig, outdir, "fig2_pareto")


# ---------------------------------------------------------------------------
# Fig 2b — zoomed Pareto on the two effective rules (veto + unanimous)
# ---------------------------------------------------------------------------


def dominance_table(config_df, rules=("restrictive_veto", "unanimous_approve"), arm="RO"):
    """Per composition × rule (within `rules`, one arm): catch, fr, net + Wilson CIs,
    whether it's on the Pareto frontier, and which config(s) dominate it (i.e. why it
    can be ruled out). Sorted best-net first."""
    pf = _pareto_frame(config_df)
    sub = pf[(pf["arm"] == arm) & (pf["rule"].isin(rules))].copy()
    recs = []
    for _, p in sub.iterrows():
        dominators = [
            f"{q['composition']}×{q['rule']}"
            for _, q in sub.iterrows()
            if (q["composition"], q["rule"]) != (p["composition"], p["rule"])
            and ((q["fr"] <= p["fr"] and q["catch"] > p["catch"])
                 or (q["fr"] < p["fr"] and q["catch"] >= p["catch"]))
        ]
        c_lo, c_hi = _wilson_ci(int(p["catch_k"]), int(p["catch_n"]))
        f_lo, f_hi = _wilson_ci(int(p["fr_k"]), int(p["fr_n"]))
        recs.append(dict(
            config=f"{p['composition']} × {p['rule']}",
            catch=round(p["catch"], 3), catch_ci=f"[{c_lo:.0%}-{c_hi:.0%}]",
            fr=round(p["fr"], 3), fr_ci=f"[{f_lo:.0%}-{f_hi:.0%}]",
            net=round(p["net"], 3), partial=round(p["part_rate"], 3),
            frontier=not dominators,
            ruled_out_by="; ".join(dominators) if dominators else "— (frontier)",
        ))
    return (pd.DataFrame(recs).sort_values(["frontier", "net"], ascending=[False, False])
            .reset_index(drop=True))


def top_catch_configs(config_df, pct=0.8, rules=None):
    """Configs in the top (1-pct) quantile of fully-owned catch, per arm. Returns a
    table with catch/fr/net + Wilson CIs and the frontier flag (computed against the
    *full* config set for that arm, so 'frontier' still means globally non-dominated).
    `pct=0.8` ⇒ top 20th percentile. `rules` optionally restricts the population first."""
    pf = _pareto_frame(config_df)
    if rules:
        pf = pf[pf["rule"].isin(rules)]
    recs = []
    for arm in [a for a in ("RO", "PR") if a in pf["arm"].unique()]:
        s = pf[pf["arm"] == arm].copy()
        s["frontier"] = _on_frontier(s)
        thr = s["catch"].quantile(pct)
        for _, p in s[s["catch"] >= thr].sort_values("catch", ascending=False).iterrows():
            c_lo, c_hi = _wilson_ci(int(p["catch_k"]), int(p["catch_n"]))
            f_lo, f_hi = _wilson_ci(int(p["fr_k"]), int(p["fr_n"]))
            recs.append(dict(
                arm=arm, catch_threshold=round(thr, 3),
                config=f"{p['composition']} × {p['rule']}",
                catch=round(p["catch"], 3), catch_ci=f"[{c_lo:.0%}-{c_hi:.0%}]",
                fr=round(p["fr"], 3), fr_ci=f"[{f_lo:.0%}-{f_hi:.0%}]",
                net=round(p["net"], 3), frontier=bool(p["frontier"]),
            ))
    return pd.DataFrame(recs)


def plot_pareto_window(config_df, xlim=(0.15, 0.40), ylim=(0.80, 0.90),
                       rules=("restrictive_veto", "unanimous_approve"),
                       arms=("RO", "PR"), outdir=None):
    """Single-axes Pareto zoom into a fixed window (default catch 80–90%,
    false-refusal 15–40%). Plain dots, each with its full, un-abbreviated label
    (arm + composition × rule) beside it; coincident configs share one label."""
    _setup()
    pf = _pareto_frame(config_df)
    pf = pf[pf["rule"].isin(rules)]
    arms = [a for a in arms if a in pf["arm"].unique()]
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    in_win = pf[(pf["fr"].between(*xlim)) & (pf["catch"].between(*ylim))]
    xmid = (xlim[0] + xlim[1]) / 2
    # group coincident configs (across arms) so each distinct dot is labelled once
    clusters = {}
    for _, r in in_win.iterrows():
        clusters.setdefault((round(r["fr"], 3), round(r["catch"], 3)), []).append(r)
    for (fr, catch), members in clusters.items():
        ax.scatter(fr, catch, s=70, color=_ink("#333333"), zorder=3)
        lines = [f"{m['arm']}  {m['composition']} × {m['rule']}" for m in members]
        right = fr > xmid
        ax.annotate("\n".join(lines), (fr, catch), textcoords="offset points",
                    xytext=(-10 if right else 10, 0), ha="right" if right else "left",
                    va="center", fontsize=8.5)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel("not-owned false-refusal  (lower = better →)")
    ax.set_ylabel("fully-owned catch  (higher = better ↑)")
    ax.set_title(f"Pareto window — catch {ylim[0]:.0%}–{ylim[1]:.0%}, "
                 f"false-refusal {xlim[0]:.0%}–{xlim[1]:.0%}")
    fig.tight_layout()
    return _save(fig, outdir, "fig2b_pareto_window")


def plot_pareto_zoom(config_df, rules=("restrictive_veto", "unanimous_approve"),
                     arms=("RO", "PR"), outdir=None):
    """Zoomed catch-vs-false-refusal scatter restricted to the effective rules, RO | PR.
    Colour = rule, marker = composition; Wilson CI cross-bars show what's statistically
    distinguishable; frontier configs are ringed + connected; dominated configs get a
    grey 'ruled out' ring. Coincident configs are labelled together."""
    _setup()
    pf = _pareto_frame(config_df)
    pf = pf[pf["rule"].isin(rules)]
    arms = [a for a in arms if a in pf["arm"].unique()]
    markers = ["o", "s", "^", "D", "v", "P", "X"]
    comps_present = [c for c in COMPOSITIONS if c in set(pf["composition"])]
    comp_marker = dict(zip(comps_present, markers))
    # shared zoom window across panels, padded
    fr_all, c_all = pf["fr"], pf["catch"]
    xlo, xhi = max(0, fr_all.min() - 0.06), min(1, fr_all.max() + 0.10)
    ylo, yhi = max(0, c_all.min() - 0.06), min(1.02, c_all.max() + 0.06)
    fig, axes = plt.subplots(1, len(arms), figsize=(7.6 * len(arms), 6.6),
                             sharex=True, sharey=True, squeeze=False)
    for ci, arm in enumerate(arms):
        ax = axes[0][ci]
        sub = pf[pf["arm"] == arm].copy()
        sub["frontier"] = _on_frontier(sub)
        # faint net iso-lines (catch = fr + net) so net reads off the diagonal
        for net in (0.3, 0.4, 0.5, 0.6, 0.7):
            ax.plot([xlo, xhi], [xlo + net, xhi + net], color="grey", lw=0.6,
                    ls=":", alpha=0.4, zorder=0)
            if ylo <= xlo + net <= yhi:
                ax.text(xlo, xlo + net + 0.004, f"net {net:+.0%}", fontsize=6,
                        color="grey", alpha=0.7)
        # CI cross-bars + markers
        for _, r in sub.iterrows():
            c_lo, c_hi = _wilson_ci(int(r["catch_k"]), int(r["catch_n"]))
            f_lo, f_hi = _wilson_ci(int(r["fr_k"]), int(r["fr_n"]))
            ax.errorbar(r["fr"], r["catch"], xerr=[[r["fr"] - f_lo], [f_hi - r["fr"]]],
                        yerr=[[r["catch"] - c_lo], [c_hi - r["catch"]]],
                        fmt="none", ecolor="grey", elinewidth=0.7, alpha=0.45, zorder=1)
            ax.scatter(r["fr"], r["catch"], s=150 if r["frontier"] else 90,
                       color=_SCEN_RULE_COLOR.get(r["rule"], "grey"),
                       marker=comp_marker[r["composition"]],
                       edgecolor=_ink() if r["frontier"] else "#b00",
                       linewidth=1.6 if r["frontier"] else 1.2,
                       alpha=0.95 if r["frontier"] else 0.5, zorder=3)
        # frontier line
        fl = sub[sub["frontier"]].sort_values("fr")
        ax.plot(fl["fr"], fl["catch"], color=_ink(), lw=1.2, ls="--", zorder=2)
        # label coincident clusters once
        clusters = {}
        for _, r in sub.iterrows():
            key = (round(r["fr"], 3), round(r["catch"], 3))
            clusters.setdefault(key, []).append(r)
        for (fr, catch), members in clusters.items():
            txt = "\n".join(f"{m['composition']}×{m['rule'].replace('restrictive_veto','veto').replace('unanimous_approve','unan')}"
                            for m in members)
            front = any(m["frontier"] for m in members)
            ax.annotate(txt, (fr, catch), textcoords="offset points", xytext=(8, 6),
                        fontsize=6.5, fontweight="bold" if front else "normal",
                        color=_ink() if front else "#900")
        ax.set_xlim(xlo, xhi)
        ax.set_ylim(ylo, yhi)
        ax.set_xlabel("not-owned false-refusal  (lower = better →)")
        if ci == 0:
            ax.set_ylabel("fully-owned catch  (higher = better ↑)")
        ax.set_title(f"{arm} — {ARM_LABEL[arm]}")
    rule_handles = [plt.Line2D([], [], marker="o", ls="", color=_SCEN_RULE_COLOR[r],
                               label=r.replace("restrictive_veto", "restrictive_veto")) for r in rules]
    comp_handles = [plt.Line2D([], [], marker=comp_marker[c], ls="", color="grey", label=c)
                    for c in comps_present]
    style_handles = [
        plt.Line2D([], [], marker="o", ls="", mfc="grey", mec=_ink(), mew=1.6, label="on frontier (keep)"),
        plt.Line2D([], [], marker="o", ls="", mfc="grey", mec="#b00", mew=1.2, alpha=0.5, label="dominated (rule out)"),
        plt.Line2D([], [], color="grey", lw=0.7, label="95% Wilson CI"),
    ]
    leg1 = fig.legend(handles=rule_handles, title="voting rule", loc="upper left",
                      bbox_to_anchor=(1.0, 0.95), frameon=False, fontsize=8)
    leg2 = fig.legend(handles=comp_handles, title="composition", loc="center left",
                      bbox_to_anchor=(1.0, 0.6), frameon=False, fontsize=8)
    fig.legend(handles=style_handles, loc="lower left", bbox_to_anchor=(1.0, 0.12),
               frameon=False, fontsize=8)
    fig.add_artist(leg1)
    fig.add_artist(leg2)
    fig.suptitle("Pareto — zoomed to the effective rules (restrictive_veto + unanimous_approve)", y=1.01)
    fig.tight_layout()
    return _save(fig, outdir, "fig2b_pareto_zoom")


# ---------------------------------------------------------------------------
# Fig 3 — visibility-shift arrows (RO → PR in the catch/FR plane)
# ---------------------------------------------------------------------------


def plot_visibility_arrows(config_df, composition=OP_COMP, outdir=None):
    """One arrow per rule from its RO point to its PR point in (FR, catch) space.
    Shows the headline: visibility moves the *error profile*, not aggregate catch."""
    _setup()
    pf = _pareto_frame(config_df)
    pf = pf[pf["composition"] == composition]
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    for rule in RULE_ORDER:
        ro = pf[(pf["arm"] == "RO") & (pf["rule"] == rule)]
        pr = pf[(pf["arm"] == "PR") & (pf["rule"] == rule)]
        if ro.empty or pr.empty:
            continue
        x0, y0 = ro["fr"].iloc[0], ro["catch"].iloc[0]
        x1, y1 = pr["fr"].iloc[0], pr["catch"].iloc[0]
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="-|>", color=RULE_COLOR[rule], lw=2.2))
        ax.scatter([x0], [y0], color=RULE_COLOR[rule], marker="o", s=70, zorder=3,
                   label=f"{rule}  (o RO -> D PR)")
        ax.scatter([x1], [y1], color=RULE_COLOR[rule], marker="D", s=70, zorder=3)
    ax.plot([0, 1], [0, 1], color="grey", lw=0.8, ls="--", alpha=0.5)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("not-owned false-refusal  (lower = better)")
    ax.set_ylabel("fully-owned catch  (higher = better)")
    ax.set_title(f"Visibility shift RO -> PR  ({composition})\nmostly horizontal => "
                 "blinding the committee changes over-blocking, not catch")
    ax.legend(loc="lower right", fontsize=8, frameon=True)
    fig.tight_layout()
    return _save(fig, outdir, "fig3_visibility_arrows")


# ---------------------------------------------------------------------------
# Fig 4 — voting rule dominates (grouped bars)
# ---------------------------------------------------------------------------


def plot_rule_dominates(config_df, composition=OP_COMP, outdir=None):
    """Grouped catch & false-refusal bars per rule, RO | PR panels. The rule axis
    sweeps catch from ~4% to ~85% — a far bigger lever than composition or visibility."""
    _setup()
    pf = _pareto_frame(config_df)
    pf = pf[pf["composition"] == composition]
    arms = [a for a in ("RO", "PR") if a in pf["arm"].unique()]
    fig, axes = plt.subplots(1, len(arms), figsize=(5.6 * len(arms), 4.4),
                             sharey=True, squeeze=False)
    x = np.arange(len(RULE_ORDER))
    w = 0.38
    for ci, arm in enumerate(arms):
        ax = axes[0][ci]
        sub = pf[pf["arm"] == arm].set_index("rule").reindex(RULE_ORDER)
        ax.bar(x - w / 2, sub["catch"], w, label="catch (fully-owned)", color="#2c7fb8")
        ax.bar(x + w / 2, sub["fr"], w, label="false-refusal (not-owned)", color="#31a354")
        for xi, (c, f) in enumerate(zip(sub["catch"], sub["fr"])):
            if pd.notna(c):
                ax.text(xi - w / 2, c + 0.02, f"{c:.0%}", ha="center", fontsize=8)
            if pd.notna(f):
                ax.text(xi + w / 2, f + 0.02, f"{f:.0%}", ha="center", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels(RULE_ORDER, rotation=20, ha="right", fontsize=8)
        ax.set_ylim(0, 1.0)
        ax.set_title(f"{arm} — {ARM_LABEL[arm]}")
        if ci == 0:
            ax.set_ylabel("rate")
            ax.legend(fontsize=8)
    fig.suptitle(f"Voting rule is the dominant lever  ({composition})", y=1.02)
    fig.tight_layout()
    return _save(fig, outdir, "fig4_rule_dominates")


# ---------------------------------------------------------------------------
# Fig 5 — confusion matrices at the operating point
# ---------------------------------------------------------------------------


def _decision_at(rows, comp, rule):
    """List of (category, decision) for one composition × rule over a set of rows."""
    rule_fn = VOTING_RULES[rule]
    comps = _comps_for(rows)
    persona_ids = comps[_resolve_comp(comps, comp)]
    out = []
    for row in rows:
        cat = row.get("category")
        if cat not in CATEGORIES:
            continue
        subset = _subset_votes(row["votes"], persona_ids)
        if len(subset) != len(persona_ids):
            continue
        d = rule_fn(subset)
        if d == "EMPTY":
            continue
        out.append((cat, d))
    return out


def plot_confusion(rows_by_arm, comp=OP_COMP, rule=OP_RULE, outdir=None):
    """Row-normalized category × decision heatmaps (RO | PR) at the operating point.
    Diagonal intuition: fully-owned→BLOCK and not-owned→RELEASE are the wins;
    partial-owned is shown for context (no 'correct' cell)."""
    _setup()
    arms = list(rows_by_arm.keys())
    fig, axes = plt.subplots(1, len(arms), figsize=(5.0 * len(arms), 4.2), squeeze=False)
    decisions = ["BLOCK", "RELEASE"]
    for ci, arm in enumerate(arms):
        ax = axes[0][ci]
        pairs = _decision_at(rows_by_arm[arm], comp, rule)
        mat = np.zeros((len(CAT_ORDER), len(decisions)))
        for cat, d in pairs:
            mat[CAT_ORDER.index(cat), decisions.index(d)] += 1
        counts = mat.copy()
        rowsum = mat.sum(axis=1, keepdims=True)
        norm = np.divide(mat, rowsum, out=np.zeros_like(mat), where=rowsum != 0)
        annot = np.empty_like(norm, dtype=object)
        for i in range(norm.shape[0]):
            for j in range(norm.shape[1]):
                annot[i, j] = f"{norm[i, j]:.0%}\n({int(counts[i, j])})"
        sns.heatmap(norm, annot=annot, fmt="", cmap="Blues", vmin=0, vmax=1,
                    cbar=ci == len(arms) - 1, ax=ax,
                    xticklabels=decisions,
                    yticklabels=["BLOCK" if c == "fully-owned" else "RELEASE" if c == "not-owned" else "(partial)"
                                 for c in CAT_ORDER])
        ax.set_title(f"{arm} — {ARM_LABEL[arm]}")
        ax.set_xlabel("committee decision")
        if ci == 0:
            ax.set_ylabel("expected decision")
    fig.suptitle(f"Confusion — {comp.replace('-only', '')} × {rule.replace('_', '-')}", y=1.02)
    fig.tight_layout()
    return _save(fig, outdir, "fig5_confusion")


# ---------------------------------------------------------------------------
# Fig 6 — per-persona ownership heatmap
# ---------------------------------------------------------------------------


def plot_persona_ownership(persona_df, outdir=None):
    """Persona × category individual block-rate, RO | PR. The ownership thesis at the
    persona level: a persona should block mostly the harms it *owns* and release the rest."""
    _setup()
    arms = [a for a in ("RO", "PR") if a in persona_df["arm"].unique()]
    order = _persona_order(persona_df["persona_id"].unique())
    fig, axes = plt.subplots(1, len(arms), figsize=(5.6 * len(arms), 5.2),
                             squeeze=False)
    for ci, arm in enumerate(arms):
        ax = axes[0][ci]
        d = persona_df[persona_df["arm"] == arm]
        piv = (d.groupby(["persona_id", "category"])["block"].mean()
               .unstack("category").reindex(index=order, columns=CAT_ORDER))
        ylabels = [f"{p}\n({d[d.persona_id==p]['leaning'].iloc[0]})" for p in order]
        sns.heatmap(piv, annot=True, fmt=".0%", cmap="Reds", vmin=0, vmax=1,
                    cbar=ci == len(arms) - 1, ax=ax,
                    yticklabels=ylabels if ci == 0 else False,
                    xticklabels=[CAT_METRIC[c] + f"\n({c})" for c in CAT_ORDER])
        ax.set_title(f"{arm} — {ARM_LABEL[arm]}")
        ax.set_xlabel("")
        if ci == 0:
            ax.set_ylabel("persona (leaning)")
    fig.suptitle("Per-persona block-rate by ownership category", y=1.02)
    fig.tight_layout()
    return _save(fig, outdir, "fig6_persona_ownership")


# ---------------------------------------------------------------------------
# Fig 6b — which persona catches each topic type (persona × owning-remit)
# ---------------------------------------------------------------------------

# Each owning-remit code maps to the persona whose remit it is — the member we'd
# expect to be the one catching that harm type (the boxed cell in the figure).
REMIT_OWNER = {
    "CONSUM": "consumer_protection_investigator", "POLICE": "police_officer",
    "EDU": "educator", "TRUST": "content_moderator",
    "CTEX": "counter_extremism_analyst", "CIVLIB": "civil_liberties_lawyer",
}

# Short display code for each persona — the Table-1 acronyms used on figure axes.
# Covers both the v2 roster and the v3 roster (child_safety dropped, content_moderator
# → harassment_safety_analyst). Unknown ids fall back to the raw key.
PERSONA_CODE = {
    "police_officer": "POLICE", "child_safety_officer": "CSO",
    "counter_extremism_analyst": "CTEX", "content_moderator": "TRUST",
    "consumer_protection_investigator": "CONSUM", "educator": "EDU",
    "journalist": "JOURN", "civil_liberties_lawyer": "CIVLIB",
    "harassment_safety_analyst": "HARASS",
}


def plot_persona_by_remit(rows_by_arm, remit_map, arms=("RO", "PR"), outdir=None):
    """Persona × owning-remit individual block-rate, RO | PR. Answers "for each topic
    type, which persona caught it" — and whether it's the *owning* persona (its cell is
    boxed). A near-diagonal (each remit lit by its owner) confirms ownership at the
    member level. The 'none' column = not-owned (no owner): block here is false-refusal."""
    _setup()
    arms = [a for a in arms if a in rows_by_arm]
    remit_order, _, remit_label, remit_owner = _remit_cfg(rows_by_arm)
    # build per (arm, persona, remit) block-rate from the raw votes
    rec = []
    for arm in arms:
        for row in rows_by_arm[arm]:
            if row.get("category") not in CATEGORIES:
                continue
            rem = remit_map.get(_scenario(row), "?")
            for v in row["votes"]:
                rec.append(dict(arm=arm, persona_id=v["persona_id"], remit=rem,
                                block=_is_block(v)))
    df = pd.DataFrame(rec)
    person_order = _persona_order(df["persona_id"].unique())
    remits = [r for r in remit_order if r in df["remit"].unique()]
    # Row order chosen so each owned remit's persona lands on the diagonal: owners in
    # column order first, then any non-owning personas, so the catch blocks run
    # top-left → bottom-right. ('none' has no owner and trails as the last column.)
    diag = [remit_owner[r] for r in remits if r in remit_owner]
    row_order = diag + [p for p in person_order if p not in diag]
    # per-remit prompt counts (same for every persona) for the column headers
    ncol = {r: int(df[(df["remit"] == r) & (df["persona_id"] == person_order[0])].shape[0])
            for r in remits}
    fig, axes = plt.subplots(1, len(arms), figsize=(0.95 * len(remits) * len(arms) + 3, 5.4),
                             squeeze=False)
    for ci, arm in enumerate(arms):
        ax = axes[0][ci]
        piv = (df[df["arm"] == arm].groupby(["persona_id", "remit"])["block"].mean()
               .unstack("remit").reindex(index=row_order, columns=remits))
        sns.heatmap(piv, annot=True, fmt=".0%", cmap="Reds", vmin=0, vmax=1,
                    cbar=ci == len(arms) - 1, ax=ax,
                    yticklabels=[PERSONA_CODE.get(p, p) for p in row_order] if ci == 0 else False,
                    # short remit code (label prefix) keeps columns compact so the
                    # cells stay large — identical to `r` for v2, shortens v3's long
                    # persona-name remits (consumer_protection_investigator → CONSUM).
                    xticklabels=[f"{remit_label.get(r, r).split()[0]}\n(n={ncol[r]})"
                                 for r in remits])
        # box the owning persona's cell for each remit (these now sit on the diagonal)
        for j, r in enumerate(remits):
            owner = remit_owner.get(r)
            if owner in row_order:
                i = row_order.index(owner)
                ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=False,
                                           edgecolor="#00b050", lw=3, zorder=5))
        ax.set_title(f"{arm} — {ARM_LABEL[arm]}")
        ax.set_xlabel("topic type (owning remit)")
        ax.set_ylabel("persona" if ci == 0 else "")
    fig.suptitle("Which persona catches each topic type  "
                 "(green box = the remit's owning persona)", y=1.02)
    fig.tight_layout()
    return _save(fig, outdir, "fig6b_persona_by_remit")


# ---------------------------------------------------------------------------
# Fig 8 — per-scenario subtlety curves (rule decision, binary, per ownership class)
# ---------------------------------------------------------------------------

# The two usable rules; everything below simple_majority's collapse / supermajority.
USABLE_RULES = ["restrictive_veto", "unanimous_approve"]
# small vertical offsets so the (rule × arm) step lines don't sit exactly on top of
# each other at y∈{0,1} — purely cosmetic separation.
_SCEN_OFFSET = {
    ("restrictive_veto", "RO"): -0.06, ("restrictive_veto", "PR"): -0.02,
    ("unanimous_approve", "RO"): 0.02, ("unanimous_approve", "PR"): 0.06,
}
# high-contrast pair for the two usable rules (viridis hues are too close at n=2);
# unanimous_approve blocks a superset of restrictive_veto, so its line sits at/above.
_SCEN_RULE_COLOR = {"restrictive_veto": "#1f77b4", "unanimous_approve": "#d62728"}


def scenario_decision_df(rows_by_arm, comp=OP_COMP, rules=USABLE_RULES) -> pd.DataFrame:
    """One row per arm × scenario × subtlety × rule with a binary `block` (1=BLOCK)
    for `comp`. The committee decision is one value per prompt, so this is the
    finest-grain decision the rules produce."""
    rec = []
    comps = _comps_for(next(iter(rows_by_arm.values())))
    pids = comps[_resolve_comp(comps, comp)]
    for arm, rows in rows_by_arm.items():
        for row in rows:
            cat = row.get("category")
            if cat not in CATEGORIES:
                continue
            subset = _subset_votes(row["votes"], pids)
            if len(subset) != len(pids):
                continue
            scen, sub = _scenario(row), _subtlety(row)
            for rule in rules:
                d = VOTING_RULES[rule](subset)
                if d == "EMPTY":
                    continue
                rec.append(dict(arm=arm, category=cat, scenario=scen, subtlety=sub,
                                rule=rule, block=int(d == "BLOCK")))
    return pd.DataFrame(rec)


def plot_scenario_curves(rows_by_arm, category, comp=OP_COMP, rules=USABLE_RULES,
                         arms=("RO", "PR"), outdir=None):
    """Per-scenario binary decision (BLOCK=1 / RELEASE=0) across L1→L5 for one
    ownership class, as a grid of small-multiples. Colour = rule, linestyle = arm.
    A flat line at the top (fully-owned) / bottom (not-owned) is the wanted behaviour;
    a step shows exactly which scenario + level the decision flips at."""
    _setup()
    df = scenario_decision_df(rows_by_arm, comp, rules)
    df = df[df["category"] == category]
    scenarios = sorted(df["scenario"].dropna().unique())
    n = len(scenarios)
    ncol = 4
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.4 * ncol, 2.2 * nrow),
                             sharex=True, sharey=True, squeeze=False)
    want = {"fully-owned": "want BLOCK (flat top)", "not-owned": "want RELEASE (flat bottom)",
            "partial-owned": "contestable (no correct line)"}[category]
    for idx, scen in enumerate(scenarios):
        ax = axes[idx // ncol][idx % ncol]
        for rule in rules:
            for arm in arms:
                if arm not in df["arm"].unique():
                    continue
                d = df[(df["scenario"] == scen) & (df["rule"] == rule) &
                       (df["arm"] == arm)].sort_values("subtlety")
                if d.empty:
                    continue
                off = _SCEN_OFFSET.get((rule, arm), 0.0)
                ax.plot(d["subtlety"], d["block"] + off, marker="o", ms=4,
                        color=_SCEN_RULE_COLOR.get(rule, RULE_COLOR[rule]),
                        ls=ARM_STYLE[arm], lw=1.4, alpha=0.9)
        ax.set_ylim(-0.25, 1.25)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["release", "block"], fontsize=7)
        ax.set_xticks(LEVELS)
        ax.set_title(scen, fontsize=8)
        ax.tick_params(labelsize=7)
    for idx in range(n, nrow * ncol):  # blank unused cells
        axes[idx // ncol][idx % ncol].axis("off")
    handles = ([plt.Line2D([], [], color=_SCEN_RULE_COLOR.get(r, RULE_COLOR[r]), lw=2,
                           label=r) for r in rules] +
               [plt.Line2D([], [], color="grey", lw=2, ls=ARM_STYLE[a],
                           label=f"{a} ({ARM_LABEL[a]})") for a in arms])
    fig.legend(handles=handles, loc="upper center", ncol=len(rules) + len(arms),
               bbox_to_anchor=(0.5, 1.0 + 0.18 / nrow), frameon=False, fontsize=8)
    fig.suptitle(f"Per-scenario decision curves — {category}  ({comp}; {want})",
                 y=1.0 + 0.32 / nrow, fontsize=12)
    fig.supxlabel("subtlety  (L1 deniable → L5 blunt)", y=-0.01)
    fig.tight_layout()
    return _save(fig, outdir, f"fig8_scenario_curves_{category}")


# ---------------------------------------------------------------------------
# Fig 7 — inter-persona agreement matrix
# ---------------------------------------------------------------------------


def plot_persona_agreement(persona_df, outdir=None):
    """8×8 fraction-of-prompts-agreeing matrix, RO | PR. High off-diagonal blocks ⇒
    redundant members; low ⇒ genuine diversity. Computed over the shared prompt set."""
    _setup()
    arms = [a for a in ("RO", "PR") if a in persona_df["arm"].unique()]
    order = _persona_order(persona_df["persona_id"].unique())
    fig, axes = plt.subplots(1, len(arms), figsize=(5.8 * len(arms), 5.4), squeeze=False)
    for ci, arm in enumerate(arms):
        ax = axes[0][ci]
        d = persona_df[persona_df["arm"] == arm]
        wide = d.pivot_table(index="prompt_id", columns="persona_id", values="block")
        wide = wide.reindex(columns=order)
        n = len(order)
        mat = np.full((n, n), np.nan)
        for i, pi in enumerate(order):
            for j, pj in enumerate(order):
                if i == j:
                    mat[i, j] = 1.0
                    continue
                both = wide[[pi, pj]].dropna()
                if len(both):
                    mat[i, j] = (both[pi] == both[pj]).mean()
        sns.heatmap(mat, annot=True, fmt=".0%", cmap="Greens", vmin=0.4, vmax=1,
                    cbar=ci == len(arms) - 1, ax=ax,
                    xticklabels=order, yticklabels=order if ci == 0 else False)
        ax.set_title(f"{arm} — {ARM_LABEL[arm]}")
        ax.tick_params(axis="x", rotation=90, labelsize=7)
        ax.tick_params(axis="y", labelsize=7)
    fig.suptitle("Inter-persona vote agreement  (share of prompts both voted the same)", y=1.02)
    fig.tight_layout()
    return _save(fig, outdir, "fig7_persona_agreement")
