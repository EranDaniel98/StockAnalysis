export const meta = {
  name: 'edge-discovery',
  description: 'Adversarial discovery of a novel, defensible equity edge: recon prior nulls, generate pre-registered hypotheses (3 seeded families + wildcard lane), refute each, synthesize a ranked slate with exact gauntlet commands.',
  whenToUse: 'When searching for a new market-beating strategy without manufacturing a false positive. Returns survivors + nulls, never a forced winner.',
  phases: [
    { title: 'Recon', detail: 'read prior research + memory to build an already-tried/killed ledger' },
    { title: 'Generate', detail: 'one agent per seeded family + wildcard lane → pre-registered hypotheses' },
    { title: 'Refute', detail: 'adversarial skeptics try to kill each candidate via documented failure modes' },
    { title: 'Synthesize', detail: 'rank survivors, list nulls, emit execution plan + honest caveat' },
  ],
}

// ---- shared context ----------------------------------------------------------
const MEMORY_DIR = 'C:/Users/Eran Daniel/.claude/projects/C--Users-Eran-Daniel-Desktop-Personal-StockNew/memory'
const REPO = 'C:/Users/Eran Daniel/Desktop/Personal/StockNew'

// The documented failure modes every candidate must survive. Refuters hunt these.
const FAILURE_MODES = [
  'phase-luck: positive only at a lucky rebalance offset; median across phases <=0 (a 2yr/63d window has a +/-20-30pp phase-noise envelope)',
  'beta-in-disguise: raw outperformance that is just leverage; CAPM-alpha (Jensen, OLS) flat/negative',
  'survivorship: relies on static universe membership; collapses under per-rebalance PIT membership (Russell +73% -> -9% clean)',
  'price-artifact: a single name carries the result via a corporate-action stitch (rename/reuse/split -> fake +1000% jump); momentum ranks the artifact #1',
  'lookahead/PIT: any feature reads data > as_of (restated fundamentals, forward-filled earnings, filing-timestamp leakage)',
  'coverage-sparsity: signal only fires on too few names/dates to trade (insider/distressed nulls died here)',
  'already-killed: the recon ledger shows this exact idea was tried and shelved/nulled',
  'cost-fragile: edge does not survive 50bps round-trip',
]

const RECON_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    tried: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { name: { type: 'string' }, verdict: { type: 'string' }, source: { type: 'string' } },
      required: ['name', 'verdict', 'source'] } },
    killed_families: { type: 'array', items: { type: 'string' } },
    unknown_verdict_scripts: { type: 'array', items: { type: 'string' } },
    reusable_harnesses: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['tried', 'killed_families', 'unknown_verdict_scripts', 'reusable_harnesses', 'notes'],
}

const HYP_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    name: { type: 'string' },
    family: { type: 'string' },
    mechanism: { type: 'string', description: 'WHY the edge should exist (economic/behavioral cause)' },
    why_generalizes: { type: 'string' },
    data_sources: { type: 'array', items: { type: 'string' } },
    pit_plan: { type: 'string', description: 'exactly how every feature stays <= as_of' },
    entry_signal: { type: 'string' },
    horizon: { type: 'string' },
    universe: { type: 'string' },
    construction: { type: 'string', description: 'long-only / beta-neutral L-S / etc + sizing' },
    orthogonality: { type: 'string', description: 'expected relationship to 12-1 momentum and value' },
    preregistered_bar: { type: 'string', description: 'pass/fail thresholds fixed BEFORE seeing returns' },
    gauntlet_commands: { type: 'array', items: { type: 'string' }, description: 'exact runnable commands using existing harnesses + snapshot ids' },
    already_tried_check: { type: 'string', description: 'cross-reference vs recon ledger; is this novel?' },
    novelty: { type: 'string' },
    survival_prior: { type: 'number', description: '0-1 self-assessed odds of surviving the full gauntlet' },
  },
  required: ['name', 'family', 'mechanism', 'why_generalizes', 'data_sources', 'pit_plan', 'entry_signal',
    'horizon', 'universe', 'construction', 'orthogonality', 'preregistered_bar', 'gauntlet_commands',
    'already_tried_check', 'novelty', 'survival_prior'],
}

const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    refuted: { type: 'boolean' },
    failure_mode: { type: 'string', description: 'which documented failure mode kills it, or "none"' },
    reasoning: { type: 'string' },
    confidence: { type: 'number' },
  },
  required: ['refuted', 'failure_mode', 'reasoning', 'confidence'],
}

const SYNTH_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    ranked_survivors: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { name: { type: 'string' }, rank: { type: 'number' }, rationale: { type: 'string' },
        first_gauntlet_command: { type: 'string' }, expected_outcome: { type: 'string' } },
      required: ['name', 'rank', 'rationale', 'first_gauntlet_command', 'expected_outcome'] } },
    rejected: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { name: { type: 'string' }, killed_by: { type: 'string' } },
      required: ['name', 'killed_by'] } },
    overall_verdict: { type: 'string' },
    honest_caveat: { type: 'string' },
  },
  required: ['ranked_survivors', 'rejected', 'overall_verdict', 'honest_caveat'],
}

// ---- seeded families + wildcard lane ----------------------------------------
const SEEDS = [
  { family: 'beta-neutral-long-short',
    brief: 'Construction edge, not a new factor. Build a beta-neutral / dollar-neutral long-short on existing factors (the strategy_debate finding named PEAD+quality L/S large-cap as the one durable candidate). Goal: positive CAPM-alpha that is NOT beta in disguise. Consider factor-crash tails (the COVID -3.7% factor-crash was not timing-fixable before).' },
  { family: 'edgar-filing-text-nlp',
    brief: 'New data. Derive a signal from EDGAR filing TEXT (10-K/10-Q/8-K language: MD&A tone, risk-factor deltas, litigation/going-concern language, item-by-item diffs vs prior filing). build_filing_signal.py exists -- read it first. Must be strictly PIT on filing accept-timestamp. Expected orthogonal to price/fundamentals factors.' },
  { family: 'accruals-quality-of-earnings',
    brief: 'Documented real anomaly (Sloan accruals). Cash-flow vs accrual earnings from EDGAR XBRL, PIT. build_accruals_sidecar.py exists -- read it first. Different signal axis than momentum/value; test as a standalone tilt and as an overlay.' },
  { family: 'wildcard-microstructure-altdata',
    brief: 'WILDCARD -- invent a NOVEL mechanism. Think freely about alpha sources derivable from the data on hand (Polygon OHLCV/minute/news, EDGAR text+XBRL, yfinance events/analyst, cross-asset hints from the crypto/funding scripts). Microstructure, implied-move proxies, peer/supply-chain networks, seasonality, regime-conditional combos -- anything. MUST be orthogonal to 12-1 momentum, PIT-feasible, and NOT in the killed ledger.' },
  { family: 'wildcard-event-catalyst',
    brief: 'WILDCARD -- invent a NOVEL mechanism centered on EVENTS/CATALYSTS (earnings-revision breadth, guidance changes, spin-offs, index reconstitution, post-IPO multi-day drift which a prior probe flagged as an untested rescue). Factor signal CONDITIONED on a catalyst. MUST be PIT, orthogonal, and novel vs the ledger.' },
  { family: 'wildcard-open',
    brief: 'WILDCARD -- fully open. Propose the single strongest idea you can defend that the other lanes did NOT cover. Reason from market-microstructure / behavioral-finance first principles about where a small, durable, beta-adjusted edge could still live in a US-equity book given this data. Be bold but defensible; novelty + survival_prior both matter.' },
]

const N_REFUTERS = 3

// ---- run --------------------------------------------------------------------
phase('Recon')
log('Reading prior research, study scripts, and memory to build the already-tried/killed ledger...')

const reconParts = await parallel([
  () => agent(
    `You are doing RECON for an equity-edge discovery search. Read these and extract everything already TRIED and its verdict, so we do not re-run dead horses.\n` +
    `Read: ${REPO}/CLAUDE.md (esp. the session-log + evaluation-discipline sections), and every *.md in ${MEMORY_DIR}.\n` +
    `Return a structured ledger: tried strategies+verdicts, families that were KILLED/nulled, scripts whose verdict you could not determine, and which harness scripts are reusable for validation.`,
    { schema: RECON_SCHEMA, phase: 'Recon', label: 'recon:memory', model: 'fable' }),
  () => agent(
    `You are doing RECON for an equity-edge discovery search. Read the research scripts to see what has been built/attempted.\n` +
    `List and skim: ${REPO}/scripts/research/*.py and these study scripts in ${REPO}/scripts/: vrp_study.py, tsmom_study.py, dispersion_premium_study.py, crypto_carry_study.py, insider_capitulation_study.py, build_filing_signal.py, build_accruals_sidecar.py, build_gap_crap_event.py, strategy_debate.py, factor_lab.py.\n` +
    `For each, note what it tests and (if discernible from code/docstrings/output handling) its verdict. Flag any whose result is unknown. Identify reusable validation harnesses (phase_envelope.py, breadth_summary.py, breadth_gate.py, price_artifact_scan.py, run_factor_backtest.py with passed_capm, right_tail_harness.py, calibration_abstention.py) and the available snapshot ids under ${REPO}/data/snapshots/.`,
    { schema: RECON_SCHEMA, phase: 'Recon', label: 'recon:scripts', model: 'fable' }),
]).then(r => r.filter(Boolean))

const ledger = JSON.stringify(reconParts, null, 2)
log(`Recon complete (${reconParts.length} ledger parts). Generating ${SEEDS.length} hypotheses, then refuting each with ${N_REFUTERS} skeptics.`)

const genPrompt = (seed) =>
  `You are generating ONE pre-registered hypothesis for a US-equity edge-discovery search. Be a rigorous quant, not a salesperson.\n\n` +
  `FAMILY: ${seed.family}\nBRIEF: ${seed.brief}\n\n` +
  `RECON LEDGER (already tried / killed -- do NOT propose anything in killed_families or duplicating tried items; build on reusable_harnesses):\n${ledger}\n\n` +
  `HARD RULES:\n- Strictly point-in-time: every feature reads only data <= as_of. State the PIT plan concretely.\n` +
  `- The bar is BETA-ADJUSTED CAPM-alpha (Jensen, OLS), positive median across >=6 rolling windows 2018-2026 AND positive in >=60% of rebalance phases, surviving 50bps cost. Raw return is not enough.\n` +
  `- Must be orthogonal to 12-1 momentum (else it is a clone).\n` +
  `- Pre-register pass/fail thresholds BEFORE any return is seen.\n` +
  `- gauntlet_commands must be EXACT and runnable using the existing harnesses and real snapshot ids from the ledger (e.g. uv run python scripts/phase_envelope.py --snapshot-id <id> --base-args "...", uv run python -m scripts.research.breadth_summary ..., uv run python -m scripts.research.price_artifact_scan ...).\n` +
  `- If this idea is effectively already-killed, say so honestly in already_tried_check and give it a low survival_prior rather than dressing it up.\n` +
  `Return the structured hypothesis.`

const refutePrompt = (hyp, i) =>
  `You are an ADVERSARIAL skeptic (#${i + 1}). Your job is to KILL this proposed equity edge, not to like it. Default to refuted=true unless it clearly withstands attack.\n\n` +
  `HYPOTHESIS:\n${JSON.stringify(hyp, null, 2)}\n\n` +
  `Attack it against these documented failure modes (each has killed a real prior strategy here):\n- ${FAILURE_MODES.join('\n- ')}\n\n` +
  `Also check: is it genuinely orthogonal to momentum, or a clone? Is the pre-registered bar honest or gameable? Are the gauntlet_commands real? Is the survival_prior inflated?\n` +
  `Pick the SINGLE most damaging failure mode if refuted. Be specific and cite the mechanism, not vibes.`

const results = await pipeline(
  SEEDS,
  (seed) => agent(genPrompt(seed), { schema: HYP_SCHEMA, phase: 'Generate', label: `gen:${seed.family}`, model: 'fable' }),
  (hyp, seed) => {
    if (!hyp) return null
    return parallel(
      Array.from({ length: N_REFUTERS }, (_, i) => () =>
        agent(refutePrompt(hyp, i), { schema: VERDICT_SCHEMA, phase: 'Refute', label: `refute:${seed.family}#${i + 1}`, model: 'fable' }))
    ).then((verdicts) => {
      const v = verdicts.filter(Boolean)
      const refutedCount = v.filter(x => x.refuted).length
      const survived = refutedCount < Math.ceil(N_REFUTERS / 2) // survives only if a MAJORITY fail to refute
      log(`${hyp.name}: ${refutedCount}/${v.length} refuters killed it -> ${survived ? 'SURVIVES' : 'rejected'}`)
      return { hypothesis: hyp, verdicts: v, refutedCount, survived }
    })
  }
)

const scored = results.filter(Boolean)
const survivors = scored.filter(r => r.survived)
log(`${survivors.length}/${scored.length} candidates survived the refutation gauntlet. Synthesizing the slate...`)

phase('Synthesize')
const synthesis = await agent(
  `You are the lead quant synthesizing an edge-discovery search. Be honest: most discovery runs end in a null, and that is an acceptable, correct outcome here. Do NOT manufacture a winner.\n\n` +
  `ALL CANDIDATES WITH REFUTATION VERDICTS:\n${JSON.stringify(scored.map(r => ({ hypothesis: r.hypothesis, refutedCount: r.refutedCount, survived: r.survived, verdicts: r.verdicts })), null, 2)}\n\n` +
  `Produce: ranked_survivors (highest-prior, most-orthogonal, cleanest-PIT first) each with the FIRST exact gauntlet command to run; rejected with the failure mode that killed each; an overall_verdict that states plainly whether anything is worth executing the full backtest gauntlet on; and a one-line honest_caveat reminding the reader that surviving design-stage refutation is necessary but NOT sufficient -- the phase-envelope + breadth + CAPM-alpha gauntlet on frozen snapshots is what decides, and the expected outcome is a modest regime-dependent tilt at best, not an oracle.`,
  { schema: SYNTH_SCHEMA, phase: 'Synthesize', label: 'synthesize', model: 'fable' })

return synthesis
