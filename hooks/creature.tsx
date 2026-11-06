// The creature band: a one-row band above the prompt with your cclevel creature, a level bar,
// today's XP and its mood. While Claude works the creature walks (each stage its own way) and acts
// out the tool Claude is using: it writes while Claude edits files, sniffs around while it searches,
// lifts while it runs commands, flexes when a commit lands and sweats when a tool fails. When Claude
// is idle it sleeps. A level up gets a short burst. In the terminal it also renames Claude's spinner
// word ("Gigachad is grinding"). On a new machine the first creature hatches live: the egg wobbles,
// cracks, and the creature appears with its class, once. Back after two or more empty days, it shows
// dusty and asleep, shakes awake and says welcome back, once that day, with no toast. The line shows
// your streak from 2 days. `/creature` turns it off or on.
//
// It shows the last offline scan (`cclevel.py --json --no-save`), kept in this plugin's own store,
// and starts a new scan in the background only when that one is more than an hour old. It makes no
// network call, and the scan writes nothing: it is the same offline card `/pet` prints.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { Action, Burst, Creature, Stage } from '../types'

const STAGES: readonly Stage[] = ['Egg', 'Hatchling', 'Lil Guy', 'Big Guy', 'Gigachad', 'GOAT']
const LEVEL_MAX = 99
const TRACK = 8                            // cells the creature walks across while Claude works
const PROPS = 5                            // room for what it holds: a barbell, a pencil, "+XP*"
const TICK_MS = 300                        // one step per tick
const STALE_MS = 60 * 60 * 1000            // scan again when the last scan is older than this
const SCAN_GUARD_MS = 3 * 60 * 1000        // another session started a scan this recently: leave it to that one
const SCAN_TIMEOUT_MS = 2 * 60 * 1000
const LINGER_MS = 2500                     // a commit's flex or a failure's sweat stays this long
const HOLD_MS = 1200                       // a tool's look stays at least this long after the tool ends
const BURST_MS = 6000                      // a level up is celebrated this long
const HATCH_MS = 8000                      // the first creature's hatch plays this long
const BACK_DAYS = 2                        // empty UTC days before today that make a welcome back
const STREAK_MIN = 2                       // the band line shows the streak from this many days
const HATCH_DAYS = 7                       // only on a machine whose ledger is at most this old: never a replay after an update
const DAY_MS = 24 * 60 * 60 * 1000
const BAR = 10                             // cells in the level bar

const WRITE_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])
const SEARCH_TOOLS = new Set(['Read', 'Grep', 'Glob', 'LS', 'WebSearch', 'WebFetch', 'ToolSearch'])
const COMMIT_RE = /\bgit\s+commit\b/       // the scanner counts commits the same way
const SPARKLE = ['*', '+', '.', '+']
const EYES = 'o.O0'                         // must match the scanner's EYES (skills/pet/scripts/cclevel.py)
const EGG_CRESTS = '.:o~'                   // and its Egg shell marks
const LOOKS = 64
const ACTION_VERBS: Record<Action['kind'], string> = {
  write: 'writing code', search: 'sniffing around', run: 'lifting', commit: 'flexing', error: 'sweating',
}
const MODE_VERBS: Record<string, string> = { thinking: 'big-braining', responding: 'cooking' }

// Change a shape tag when its value's fields change: it declines what an earlier version stored.
const creature = atom({ plugin: 'cclevel', key: 'creature' } as const, null, { shape: 'creature-5' })
const frame = atom({ plugin: 'cclevel', key: 'frame' } as const, 0)
const isHidden = atom({ plugin: 'cclevel', key: 'isHidden' } as const, false)
const isScanning = atom({ plugin: 'cclevel', key: 'isScanning' } as const, false)
const action = atom({ plugin: 'cclevel', key: 'action' } as const, null, { shape: 'action-1' })
const burst = atom({ plugin: 'cclevel', key: 'burst' } as const, null, { shape: 'burst-3' })

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0

/** A creature from data this mod does not control (the store), or null. */
export function asCreature(value: unknown): Creature | null {
  if (typeof value !== 'object' || value === null) return null
  const { level, stage, mood, xp, xpLevelStart, xpNextLevel, xpToday, at } = value as Record<string, unknown>
  if (typeof level !== 'number' || !Number.isInteger(level) || level < 1 || level > 999) return null
  if (typeof stage !== 'string' || !(STAGES as readonly string[]).includes(stage)) return null
  if (typeof mood !== 'string' || mood.length === 0 || mood.length > 40) return null
  if (![xp, xpLevelStart, xpNextLevel, xpToday, at].every(isCount)) return null
  const { look, shiny, cls, hatched, away, streak } = value as Record<string, unknown>
  const c: Creature = {
    level, stage: stage as Stage, mood, xp: xp as number, xpLevelStart: xpLevelStart as number,
    xpNextLevel: xpNextLevel as number, xpToday: xpToday as number, at: at as number,
  }
  if (typeof cls === 'string' && /^[A-Za-z ]{1,30}$/.test(cls)) c.cls = cls
  // The ledger's first day, or null before there is a ledger. Missing (an older scanner) means not new.
  if (hatched === null || (typeof hatched === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(hatched))) c.hatched = hatched
  if (away === null || (isCount(away) && Number.isInteger(away))) c.away = away
  if (isCount(streak) && Number.isInteger(streak)) c.streak = streak
  // Markings that are out of range are dropped: the classic look.
  if (typeof look === 'number' && Number.isInteger(look) && look >= 0 && look < LOOKS && typeof shiny === 'boolean') {
    c.look = look
    c.shiny = shiny
  }
  return c
}

/** A creature from the scan's JSON (`--json`), stamped with when the scan started, or null. */
export function fromScan(json: unknown, at: number): Creature | null {
  if (typeof json !== 'object' || json === null) return null
  const o = json as Record<string, unknown>
  const marks = typeof o.marks === 'object' && o.marks !== null ? o.marks as Record<string, unknown> : {}
  const raw = typeof o.raw === 'object' && o.raw !== null ? o.raw as Record<string, unknown> : {}
  return asCreature({
    level: o.level, stage: o.stage, mood: o.mood, xp: o.xp, xpLevelStart: o.xp_level_start,
    xpNextLevel: o.xp_next_level, xpToday: o.xp_today_pending, at, look: marks.look, shiny: marks.shiny,
    cls: o.class, hatched: o.hatched, away: raw.away_days, streak: raw.current_streak,
  })
}

/** Whether this scan is from a new machine: no ledger yet, or one at most HATCH_DAYS old. */
export function isNewMachine(c: Creature): boolean {
  if (c.hatched === null) return true
  if (c.hatched === undefined) return false
  const first = Date.parse(`${c.hatched}T00:00:00Z`)
  return Number.isFinite(first) && Math.floor(c.at / DAY_MS) - Math.floor(first / DAY_MS) <= HATCH_DAYS
}

/** The hatch's words, the same in the band and its toast. */
export function hatchText(c: Creature): string {
  if (c.stage === 'Egg') return 'An egg appeared! It hatches at Lv 5.'
  const who = c.cls === undefined || c.cls === 'Unhatched' ? c.stage : `${c.stage} ${c.cls}`
  const a = /^[AEIOU]/.test(who) ? 'an' : 'a'
  return `HATCHED! It's ${a} ${who} · Lv ${c.level}${c.shiny === true ? ' · ✦ Shiny!' : ''}`
}

/** The hatch at tick `k` of its burst: the egg wobbles two ticks, cracks two, then the creature parties. */
export function hatchSprite(c: Creature, k: number): string {
  const party = sprite(c.stage, c.level, k, 'party', c)
  if (c.stage === 'Egg' || k >= 4) return party
  const egg = k < 2 ? sprite('Egg', 1, k, 'walk').trimEnd() : k === 2 ? "(,.')" : '\\(o o)/'
  return egg.padEnd(party.length)
}

/** The UTC date of epoch milliseconds `at`: the scanner's days are UTC dates too. */
export function utcDay(at: number): string {
  return new Date(at).toISOString().slice(0, 10)
}

/** Whether this scan is a return: two or more empty UTC days just before today. */
export function isBack(c: Creature): boolean {
  return typeof c.away === 'number' && c.away >= BACK_DAYS
}

/** The welcome back's words. */
export function backText(c: Creature): string {
  return `Welcome back! Your ${c.stage} woke up.`
}

/** The welcome back at tick `k` of its burst: two ticks dusty and asleep, one shaking awake, then the party. */
export function backSprite(c: Creature, k: number): string {
  const party = sprite(c.stage, c.level, k, 'party', c)
  if (k >= 3) return party
  const face = sprite(c.stage, c.level, 0, 'walk').trimEnd()
  const cells = k < 2 ? `${sprite(c.stage, c.level, 0, 'asleep', c).trimEnd()} . .` : `~${face}~`
  return cells.padEnd(party.length)
}

/** The band line after the level bar: today's XP, the streak from 2 days, and the mood. */
export function lineText(c: Creature): string {
  const today = c.xpToday > 0 ? ` +${c.xpToday} today ·` : ''
  const streak = (c.streak ?? 0) >= STREAK_MIN ? ` streak ${c.streak} ·` : ''
  return `${today}${streak} ${c.mood}`
}

/** How far through its level the creature is, 0 to 1. */
export function progress(c: Creature): number {
  if (c.level >= LEVEL_MAX) return 1
  const span = c.xpNextLevel - c.xpLevelStart
  return span > 0 ? Math.min(1, Math.max(0, (c.xp - c.xpLevelStart) / span)) : 0
}

/** The stage's own move at step `n`: the Egg cracks as it nears hatching, the Hatchling flaps,
 * Lil Guy skips, Big Guy stomps, Gigachad pumps its arms, and the GOAT's crown sparkles. */
function shell(stage: Stage, n: number, level: number): { left: string; eyes: string; right: string } {
  const isOdd = n % 2 === 1
  switch (stage) {
    case 'Egg':
      return { left: '(', eyes: level >= 4 ? ",.'" : level === 3 ? " .'" : ' . ', right: ')' }
    case 'Hatchling':
      return isOdd ? { left: '\\', eyes: 'o o', right: '/' } : { left: '/', eyes: 'o o', right: '\\' }
    case 'Lil Guy':
      return { left: '( ', eyes: isOdd ? '^ ^' : 'o o', right: ' )' }
    case 'Big Guy':
      return isOdd ? { left: '|( ', eyes: 'o o', right: ' )|' } : { left: '/( ', eyes: 'o o', right: ' )\\' }
    case 'Gigachad':
      return isOdd ? { left: '_( ', eyes: 'o o', right: ' )_' } : { left: '\\( ', eyes: 'o o', right: ' )/' }
    case 'GOAT': {
      const s = SPARKLE[n % SPARKLE.length] ?? '*'
      return { left: `${s}( `, eyes: '@ @', right: ` )${s}` }
    }
  }
}

/** What the creature looks like: walking, acting out a tool, asleep, or celebrating. */
export type Look = 'walk' | Action['kind'] | 'asleep' | 'party'

/** The creature's cells at step `n`, always the same width for a stage so the text beside it stays put.
 * `marks` is the scan's look: the walk uses its eye style (the Egg its shell mark), and a shiny one
 * twinkles in the prop room. Every other look keeps its own eyes, since they act. */
export function sprite(stage: Stage, level: number, n: number, look: Look, marks: { look?: number; shiny?: boolean } = {}): string {
  const step = look === 'asleep' ? 0 : n
  const { left, eyes: shellEyes, right } = shell(stage, step, level)
  const mark = marks.look ?? 0
  const ownEyes = stage === 'Egg' ? shellEyes.replace('.', EGG_CRESTS[(mark >> 4) % 4] ?? '.')
    : stage === 'GOAT' ? shellEyes : shellEyes.replaceAll('o', EYES[mark % 4] ?? 'o')
  const eye = stage === 'GOAT' ? '@' : 'o'
  const eyes = stage === 'Egg' ? ownEyes : {
    walk: ownEyes,
    asleep: '- -',
    write: shellEyes,
    search: n % 2 === 0 ? `${eye}${eye} ` : ` ${eye}${eye}`,
    run: '> <',
    commit: '^ ^',
    error: ';_;',
    party: '^ ^',
  }[look]
  const face = left + eyes + right
  const width = shell(stage, 0, 1).left.length + 3 + shell(stage, 0, 1).right.length + PROPS + TRACK
  const isOdd = n % 2 === 1
  const body = {
    walk: marks.shiny ? `${face} ${SPARKLE[n % SPARKLE.length] ?? '*'}` : face,
    asleep: `${face} zZ`,
    write: face + (isOdd ? ' ✎~' : ' ~✎'),
    search: face + (isOdd ? '  ?' : ' ?'),
    run: isOdd ? `o-${face}-o` : `o=${face}=o`,
    commit: face + (isOdd ? ' +XP*' : ' +XP'),
    error: face + (isOdd ? " '" : ' ,'),
    party: isOdd ? `+${face}+` : `*${face}*`,
  }[look]
  if (look === 'asleep') return body.padEnd(width)
  // The Egg wobbles where it lies; the rest walk to and fro across the lane.
  const span = TRACK * 2
  const at = stage === 'Egg' ? n % 2 : (n % span <= TRACK ? n % span : span - (n % span))
  return (' '.repeat(at) + body).padEnd(width)
}

/** The spinner's word while the creature is out: "Gigachad is grinding". */
export function spinnerWord(stage: Stage, kind: Action['kind'] | null, mode: string): string {
  return `${stage} is ${kind !== null ? ACTION_VERBS[kind] : (MODE_VERBS[mode] ?? 'grinding')}`
}

function kindOf(tool: string): Action['kind'] | null {
  if (WRITE_TOOLS.has(tool)) return 'write'
  if (SEARCH_TOOLS.has(tool)) return 'search'
  if (tool === 'Bash') return 'run'
  return null
}

// The module's own moving parts: one ticker while something moves, and ids so a late timer
// never clears a newer action or burst. `$` is handed only to functions declared here, at the top.
let ticker: Timer | undefined
let nextId = 0

function startTicker($: EngineInterface): void {
  ticker ??= $.clock.every(TICK_MS, () => void update($, frame, n => (n + 1) % 100_000))
}

function stopTicker(): void {
  ticker?.cancel()
  ticker = undefined
}

/** Shows `kind` for a moment, unless something newer replaced it by then. */
async function flash($: EngineInterface, kind: Action['kind']): Promise<void> {
  const id = ++nextId
  await update($, action, () => ({ kind, id }))
  $.clock.after(LINGER_MS, () => void update($, action, a => (a?.id === id ? null : a)))
}

async function scan($: EngineInterface): Promise<void> {
  const at = await $.clock.now()
  await $.store.set('scanStartedAt', at)
  await update($, isScanning, () => true)
  try {
    const run = await $.process.run(
      ['python3', `${$.plugin.root}/skills/pet/scripts/cclevel.py`, '--json', '--no-save'],
      { timeoutMs: SCAN_TIMEOUT_MS },
    )
    if (run.exitCode !== 0) return
    const fresh = fromScan(JSON.parse(run.stdout), at)
    if (fresh === null) return
    const before = asCreature(await $.store.get('creature'))
    await $.store.set('creature', fresh)
    await update($, creature, () => fresh)
    // The first creature on a new machine hatches, once. A hidden band plays and records nothing.
    if (before === null && isNewMachine(fresh) && (await $.store.get('hatchShown')) !== true
        && (await $.store.get('hidden')) !== true) {
      const id = ++nextId
      const text = hatchText(fresh)
      const from = await read($, frame)
      await $.store.set('hatchShown', true)
      await update($, burst, () => ({ level: fresh.level, stage: fresh.stage, from: 'Egg' as Stage, id, hatch: text, frame: from }))
      startTicker($)
      $.clock.after(HATCH_MS, () => void update($, burst, b => (b?.id === id ? null : b)))
      $.ui.toast(text)
      return
    }
    // Back after two or more empty days: a welcome back, once a UTC day, with no toast. A hidden band
    // plays and records nothing.
    const day = utcDay(at)
    if (isBack(fresh) && (await $.store.get('greetedOn')) !== day && (await $.store.get('hidden')) !== true) {
      const id = ++nextId
      const from = await read($, frame)
      await $.store.set('greetedOn', day)
      await update($, burst, () => ({ level: fresh.level, stage: fresh.stage, from: fresh.stage, id, back: true, frame: from }))
      startTicker($)
      $.clock.after(BURST_MS, () => void update($, burst, b => (b?.id === id ? null : b)))
      return
    }
    if (before !== null && fresh.level > before.level) {
      const id = ++nextId
      await update($, burst, () => ({ level: fresh.level, stage: fresh.stage, from: before.stage, id }))
      startTicker($)
      $.clock.after(BURST_MS, () => void update($, burst, b => (b?.id === id ? null : b)))
      $.ui.toast(fresh.stage === before.stage
        ? `Level up! Your ${fresh.stage} is Lv ${fresh.level}.`
        : `Your ${before.stage} became a ${fresh.stage}! Lv ${fresh.level}. Post it: /pet evolve`)
    }
  } catch {
    // No python3, a scan past its timeout, output that is not JSON, or a surface with no host
    // commands: keep showing what was there.
  } finally {
    await update($, isScanning, () => false)
  }
}

/** Starts a background scan when the stored one is missing or old and no other session is on it. */
async function scanIfStale($: EngineInterface): Promise<void> {
  if ((await $.store.get('hidden')) === true) return
  const known = asCreature(await $.store.get('creature'))
  const now = await $.clock.now()
  const startedAt = await $.store.get('scanStartedAt')
  const isBusyElsewhere = typeof startedAt === 'number' && now - startedAt < SCAN_GUARD_MS
  if ((known === null || now - known.at > STALE_MS) && !isBusyElsewhere) {
    $.clock.after(0, () => void scan($))
  }
}

export const register: Register = on => {
  // A reload runs this again: start from no ticker.
  stopTicker()

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'creature',
      description: 'Show or hide your cclevel creature above the prompt (on, off, or no word to switch)',
    })
    const hidden = (await $.store.get('hidden')) === true
    await update($, isHidden, () => hidden)
    const known = asCreature(await $.store.get('creature'))
    if (known !== null) await update($, creature, () => known)
    await scanIfStale($)

    return next(e)
  })

  on('command.run', { command: 'creature' }, async ($, e) => {
    const word = e.args.trim().toLowerCase()
    if (word !== '' && word !== 'on' && word !== 'off') {
      return { text: 'Use /creature on, /creature off, or /creature to switch.' }
    }
    const wasHidden = (await $.store.get('hidden')) === true
    const hidden = word === '' ? !wasHidden : word === 'off'
    await $.store.set('hidden', hidden)
    await update($, isHidden, () => hidden)
    if (hidden) {
      stopTicker()
      return { text: 'Creature band off. /creature on brings it back.' }
    }
    await scanIfStale($)

    return { text: 'Creature band on.' }
  })

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined && (await $.store.get('hidden')) !== true) startTicker($)

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      stopTicker()
      await scanIfStale($)
    }

    return next(e)
  })

  // Acts out each tool call. The call itself is never held up or changed: what the band does
  // around it is best effort, and the tool's own result (or error) always goes on as it came.
  on('tool.call', async ($, e, next) => {
    const kind = kindOf(e.tool)
    const id = ++nextId
    if (kind !== null) await update($, action, () => ({ kind, id })).catch(() => undefined)
    const ran = await next(e)
    try {
      if (ran.isError === true) {
        await flash($, 'error')
      } else if (e.tool === 'Bash' && ran.deny === undefined && COMMIT_RE.test(e.command)) {
        await flash($, 'commit')
      } else if (kind !== null) {
        // A read or a search is over in a blink: keep its look up a moment so it can be seen.
        // A newer tool replaces it at once, and nothing waits for this.
        $.clock.after(HOLD_MS, () => void update($, action, a => (a?.id === id ? null : a)))
      }
    } catch {
      // The band missing one reaction is fine.
    }

    return ran
  }).catch(($, e, next) => next(e)) // never refuse or hold a tool for the band's sake: hand it on

  on('ui.render', { component: 'Spinner' }, async ($, e, next) => {
    // Only the terminal: the desktop's row says what the step is doing, which is worth more.
    if (e.surface !== 'terminal' || e.props.message !== null || (await read($, isHidden))) return next(e)
    const shown = await read($, creature)
    if (shown === null) return next(e)
    const doing = await read($, action)

    return next({ ...e, props: { ...e.props, word: spinnerWord(shown.stage, doing?.kind ?? null, e.props.mode) } })
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || (await read($, isHidden))) return next(e)
    const shown = await read($, creature)
    const { Box, Text } = $.ui.resolve(e)
    if (shown === null) {
      if (!(await read($, isScanning))) return next(e)

      return (
        <Box>
          <Text dimColor wrap="truncate-end">( ? )  cclevel is scoring your setup to hatch your creature…</Text>
        </Box>
      )
    }
    const party = await read($, burst)
    const isWorking = e.props.isWorking
    if (!isWorking && party === null) stopTicker()
    // Read the step and the action only while something moves, so an idle band never redraws.
    const n = isWorking || party !== null ? await read($, frame) : 0
    const doing = isWorking && party === null ? await read($, action) : null
    const look: Look = party !== null ? 'party' : !isWorking ? 'asleep' : (doing?.kind ?? 'walk')
    const cells = sprite(shown.stage, shown.level, n, look, shown)

    if (party?.hatch !== undefined) {
      const k = (n - (party.frame ?? 0) + 100_000) % 100_000

      return (
        <Box>
          <Text color="claude">{hatchSprite(shown, k)}</Text>
          <Text bold color="claude" wrap="truncate-end">{shown.stage !== 'Egg' && k < 4 ? '  …' : `  ${party.hatch}`}</Text>
        </Box>
      )
    }
    if (party?.back === true) {
      const k = (n - (party.frame ?? 0) + 100_000) % 100_000

      return (
        <Box>
          <Text color="claude">{backSprite(shown, k)}</Text>
          <Text bold color="claude" wrap="truncate-end">{`  ${backText(shown)}`}</Text>
        </Box>
      )
    }
    if (party !== null) {
      const news = party.stage === party.from
        ? `  LEVEL UP!  Lv ${party.level}`
        : party.from === 'Egg' ? `  HATCHED!  Lv ${party.level} ${party.stage}` : `  EVOLVED into a ${party.stage}!  Lv ${party.level}`

      return (
        <Box>
          <Text color="claude">{cells}</Text>
          <Text bold color="claude" wrap="truncate-end">{news}</Text>
        </Box>
      )
    }
    const filled = Math.round(progress(shown) * BAR)

    return (
      <Box>
        <Text color="claude">{cells}</Text>
        <Text dimColor>{`  ${shown.stage} · Lv ${shown.level} `}</Text>
        <Text color="claude">{'█'.repeat(filled)}</Text>
        <Text dimColor>{'░'.repeat(BAR - filled)}</Text>
        <Text dimColor wrap="truncate-end">{lineText(shown)}</Text>
      </Box>
    )
  })
}
