// The creature band: a one-row band above the prompt with your cclevel creature, its level and
// mood. It walks while Claude works and sleeps when Claude is idle. `/creature` turns it off or on.
//
// It shows the last offline scan (`cclevel.py --json --no-save`), kept in this plugin's own store,
// and starts a new scan in the background only when that one is more than six hours old. It makes
// no network call, and the scan writes nothing: it is the same offline card `/pet` prints.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { Creature } from '../types'

const STAGES: readonly Creature['stage'][] = ['Egg', 'Hatchling', 'Lil Guy', 'Big Guy', 'Gigachad', 'GOAT']
// One-row faces, taken from each stage's head in the card art.
const FACES: Record<Creature['stage'], string> = {
  Egg: '( . )',
  Hatchling: '/o o\\',
  'Lil Guy': '( o o )',
  'Big Guy': '/( o o )\\',
  Gigachad: '\\( o o )/',
  GOAT: '*( @ @ )*',
}
const TRACK = 8                            // cells the creature walks across while Claude works
const TICK_MS = 300                        // one step per tick
const STALE_MS = 6 * 60 * 60 * 1000        // scan again when the last scan is older than this
const SCAN_GUARD_MS = 3 * 60 * 1000        // another session started a scan this recently: leave it to that one
const SCAN_TIMEOUT_MS = 2 * 60 * 1000

// Change a shape tag when its value's fields change: it declines what an earlier version stored.
const creature = atom({ plugin: 'cclevel', key: 'creature' } as const, null, { shape: 'creature-1' })
const frame = atom({ plugin: 'cclevel', key: 'frame' } as const, 0)
const isHidden = atom({ plugin: 'cclevel', key: 'isHidden' } as const, false)
const isScanning = atom({ plugin: 'cclevel', key: 'isScanning' } as const, false)

/** A creature from data this mod does not control (the scan's output, the store), or null. */
export function asCreature(value: unknown, at: unknown): Creature | null {
  if (typeof value !== 'object' || value === null) return null
  const { level, stage, mood } = value as Record<string, unknown>
  if (typeof at !== 'number' || !Number.isFinite(at)) return null
  if (typeof level !== 'number' || !Number.isInteger(level) || level < 1 || level > 999) return null
  if (typeof stage !== 'string' || !(STAGES as readonly string[]).includes(stage)) return null
  if (typeof mood !== 'string' || mood.length === 0 || mood.length > 40) return null
  return { level, stage: stage as Creature['stage'], mood, at }
}

/** The creature's cells for step `n`: walking to and fro while Claude works, asleep otherwise. */
export function sprite(stage: Creature['stage'], n: number, isWorking: boolean): string {
  const awake = FACES[stage]
  const asleep = awake.replace(/[o@]/g, '-')
  const width = awake.length + TRACK
  if (!isWorking) return `${asleep} zZ`.padEnd(width)
  const step = n % (TRACK * 2)
  const at = step <= TRACK ? step : TRACK * 2 - step
  const isBlinking = n % 9 === 8
  return (' '.repeat(at) + (isBlinking ? asleep : awake)).padEnd(width)
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
    const fresh = asCreature(JSON.parse(run.stdout), at)
    if (fresh === null) return
    await $.store.set('creature', fresh)
    await update($, creature, () => fresh)
  } catch {
    // No python3, a scan past its timeout, output that is not JSON, or a surface with no host
    // commands: keep showing what was there.
  } finally {
    await update($, isScanning, () => false)
  }
}

/** Starts a background scan when the stored one is missing or old and no other session is on it. */
async function scanIfStale($: EngineInterface, known: Creature | null): Promise<void> {
  const now = await $.clock.now()
  const startedAt = await $.store.get('scanStartedAt')
  const isBusyElsewhere = typeof startedAt === 'number' && now - startedAt < SCAN_GUARD_MS
  if ((known === null || now - known.at > STALE_MS) && !isBusyElsewhere) {
    $.clock.after(0, () => void scan($))
  }
}

export const register: Register = on => {
  let ticker: Timer | undefined
  const stopTicker = () => {
    ticker?.cancel()
    ticker = undefined
  }

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'creature',
      description: 'Show or hide your cclevel creature above the prompt (on, off, or no word to switch)',
    })
    const hidden = (await $.store.get('hidden')) === true
    await update($, isHidden, () => hidden)
    const stored = await $.store.get('creature')
    const known = asCreature(stored, (stored as { at?: unknown } | undefined)?.at)
    if (known !== null) await update($, creature, () => known)
    if (!hidden) await scanIfStale($, known)

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
    const stored = await $.store.get('creature')
    await scanIfStale($, asCreature(stored, (stored as { at?: unknown } | undefined)?.at))

    return { text: 'Creature band on.' }
  })

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined && ticker === undefined && (await $.store.get('hidden')) !== true) {
      ticker = $.clock.every(TICK_MS, () => void update($, frame, n => (n + 1) % 100_000))
    }

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) stopTicker()

    return next(e)
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
    const isWorking = e.props.isWorking
    if (!isWorking) stopTicker()
    // Read the step only while working, so the idle band does not redraw on every tick.
    const n = isWorking ? await read($, frame) : 0

    return (
      <Box>
        <Text color="claude">{sprite(shown.stage, n, isWorking)}</Text>
        <Text dimColor wrap="truncate-end">{`  ${shown.stage} · Lv ${shown.level} · ${shown.mood}`}</Text>
      </Box>
    )
  })
}
