// Tests for the creature band (hooks/creature.tsx). Run with: claude plugin test .
import type { CommandRunInput, On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { asCreature, fromScan, progress, spinnerWord, sprite } from '../hooks/creature'
import type { Look } from '../hooks/creature'
import type { Creature, Stage } from '../types'

const HOUR = 60 * 60 * 1000
const NOW = 1_800_000_000_000
const SCAN = {
  level: 46, stage: 'Gigachad', mood: 'Vibing', class: 'Shipper', xp: 86339,
  xp_level_start: 84640, xp_next_level: 88360, xp_today_pending: 550,
}
const STORED: Creature = {
  level: 46, stage: 'Gigachad', mood: 'Vibing', xp: 86339, xpLevelStart: 84640, xpNextLevel: 88360, xpToday: 550, at: NOW,
}

const BAND = {
  plugin: 'cclevel',
  component: 'AbovePrompt',
  surface: 'terminal',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 9 },
    view: {},
  },
} as const
const WORKING = { ...BAND, props: { ...BAND.props, isWorking: true } }
const SPINNER = {
  plugin: 'cclevel',
  component: 'Spinner',
  surface: 'terminal',
  props: { word: 'Sauteing', message: null, suffix: '…', mode: 'thinking' },
} as const

const start = { cwd: '/', surface: 'terminal', isInteractive: true } as const

/** `/creature <args>` as the person types it; the engine stamps `origin` and `presentation` itself. */
const creatureCommand = (args: string) => ({ command: 'creature', args }) as unknown as CommandRunInput

/** The engine beneath the plugin: commands register, a session starts, tools answer, each scan is
 * recorded, and what the plugin leaves to the engine draws as "engine" (a spinner as its word). */
function engine(on: On, scan: { exitCode: number; stdout: string } = { exitCode: 0, stdout: JSON.stringify(SCAN) }) {
  const runs: (readonly string[])[] = []
  on('command.register', () => ({ value: { command: 'creature' } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => {
    runs.push(e.argv)
    return { value: { exitCode: scan.exitCode, stdout: scan.stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.toast', () => ({ value: undefined }) as never)
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    const word = (e.props as { word?: unknown }).word
    return <Text>{typeof word === 'string' ? word : 'engine'}</Text>
  })
  return runs
}

async function bandText(ui: { find: (q: { type: 'Text'; text: RegExp }) => Promise<{ text: string } | undefined> }, re: RegExp) {
  return (await ui.find({ type: 'Text', text: re }))?.text
}

test('a fresh install scans once, offline, and shows the creature asleep with its level bar', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on)
  const runs = engine(on)

  await $.session.start(start)
  await clock.advance(1)

  expect(runs.length).toBe(1)
  const argv = runs[0] ?? []
  expect(argv[0]).toBe('python3')
  expect(argv[1]?.endsWith('/skills/pet/scripts/cclevel.py')).toBe(true)
  expect(argv.slice(2)).toEqual(['--json', '--no-save'])

  const ui = await $.ui.mount(BAND)
  expect(await bandText(ui, /zZ/)).toBe('\\( - - )/ zZ'.padEnd(9 + 5 + 8))
  expect(await bandText(ui, /Lv/)).toBe('  Gigachad · Lv 46 ')
  expect(await bandText(ui, /^█+$/)).toBe('█████')
  expect(await bandText(ui, /^░+$/)).toBe('░░░░░')
  expect(await bandText(ui, /today/)).toBe(' +550 today · Vibing')
  await ui.unmount()
})

test('a scan from the last hour is shown at once and not repeated', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { ...STORED, level: 12, stage: 'Hatchling', at: NOW - HOUR / 2 } })
  const runs = engine(on)

  await $.session.start(start)
  await clock.advance(1)

  expect(runs.length).toBe(0)
  const ui = await $.ui.mount(WORKING)
  expect(await bandText(ui, /Lv/)).toBe('  Hatchling · Lv 12 ')
  expect((await bandText(ui, /o o/))?.trimEnd()).toBe('/o o\\')
  await ui.unmount()
})

test('an old scan is replaced, unless another session is already scanning', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, {
    creature: { ...STORED, level: 12, stage: 'Hatchling', at: NOW - 2 * HOUR },
    scanStartedAt: NOW - 60_000,
  })
  const runs = engine(on)

  await $.session.start(start)
  await clock.advance(1)
  expect(runs.length).toBe(0)

  await clock.advance(5 * 60_000)
  await $.session.start(start)
  await clock.advance(1)
  expect(runs.length).toBe(1)
})

test('a creature stored by the first version of the band is scanned again', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { level: 46, stage: 'Gigachad', mood: 'Vibing', at: NOW } })
  const runs = engine(on)

  await $.session.start(start)
  await clock.advance(1)
  expect(runs.length).toBe(1)
})

test('a scan that fails or prints something else keeps the creature that was there', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { ...STORED, level: 12, stage: 'Hatchling', at: NOW - 2 * HOUR } })
  const runs = engine(on, { exitCode: 0, stdout: 'not json' })

  await $.session.start(start)
  await clock.advance(1)
  expect(runs.length).toBe(1)

  const ui = await $.ui.mount(BAND)
  expect(await bandText(ui, /Lv/)).toBe('  Hatchling · Lv 12 ')
  await ui.unmount()
})

test('a level up bursts for a few seconds, then the band goes back to normal', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { ...STORED, level: 45, at: NOW - 2 * HOUR } })
  engine(on)

  await $.session.start(start)
  await clock.advance(1)
  let ui = await $.ui.mount(BAND)
  expect(await bandText(ui, /LEVEL UP/)).toBe('  LEVEL UP!  Lv 46')
  expect((await bandText(ui, /\^ \^/))?.trim()).toMatch(/^[*+]\\\( \^ \^ \)\/[*+]$/)
  await ui.unmount()

  await clock.advance(6_100)
  ui = await $.ui.mount(BAND)
  expect(await bandText(ui, /LEVEL UP/)).toBe(undefined)
  expect(await bandText(ui, /Lv/)).toBe('  Gigachad · Lv 46 ')
  await ui.unmount()
})

test('a new stage is an evolution, and the Egg hatches', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { ...STORED, level: 44, stage: 'Big Guy', at: NOW - 2 * HOUR } })
  engine(on)
  await $.session.start(start)
  await clock.advance(1)
  const ui = await $.ui.mount(BAND)
  expect(await bandText(ui, /EVOLVED/)).toBe('  EVOLVED into a Gigachad!  Lv 46')
  await ui.unmount()
})

test('an Egg that becomes a Hatchling hatches', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { ...STORED, level: 4, stage: 'Egg', at: NOW - 2 * HOUR } })
  engine(on, { exitCode: 0, stdout: JSON.stringify({ ...SCAN, level: 5, stage: 'Hatchling', xp: 1000, xp_level_start: 1000, xp_next_level: 1440 }) })
  await $.session.start(start)
  await clock.advance(1)
  const ui = await $.ui.mount(BAND)
  expect(await bandText(ui, /HATCHED/)).toBe('  HATCHED!  Lv 5 Hatchling')
  await ui.unmount()
})

test('it acts out tools: writing while a file is edited, then flexing on a commit and sweating on a failure', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: STORED })
  engine(on)
  let duringEdit: string | undefined
  let fails = false
  on('tool.call', async () => {
    const ui = await $.ui.mount(WORKING)
    duringEdit = await bandText(ui, /✎/)
    await ui.unmount()
    return fails ? { result: {}, isError: true } as never : { result: {} } as never
  })
  await $.session.start(start)

  // Called through a plain signature: the tool inputs' full types are too deep for the checker.
  const callTool = $.tool.call as unknown as (input: Record<string, unknown>) => Promise<unknown>
  await callTool({ tool: 'Edit', file_path: '/x', old_string: 'a', new_string: 'b' })
  expect(duringEdit?.trim()).toMatch(/^\\\( o o \)\/ (✎~|~✎)$/)

  await callTool({ tool: 'Bash', command: 'git commit -m "ship it"' })
  let ui = await $.ui.mount(WORKING)
  expect((await bandText(ui, /\+XP/))?.trim()).toMatch(/^\\\( \^ \^ \)\/ \+XP\*?$/)
  await ui.unmount()
  const spinner = await $.ui.mount(SPINNER)
  expect(await bandText(spinner, /is/)).toBe('Gigachad is flexing')
  await spinner.unmount()

  await clock.advance(2_600)
  ui = await $.ui.mount(WORKING)
  expect(await bandText(ui, /\+XP/)).toBe(undefined)
  await ui.unmount()

  fails = true
  await callTool({ tool: 'Bash', command: 'npm test' })
  ui = await $.ui.mount(WORKING)
  expect((await bandText(ui, /;_;/))?.trim()).toMatch(/^\\\( ;_; \)\/ [',]$/)
  await ui.unmount()
})

test('a quick read stays on screen a moment, then the creature walks on', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: STORED })
  engine(on)
  on('tool.call', () => ({ result: {} }) as never)
  await $.session.start(start)

  const callTool = $.tool.call as unknown as (input: Record<string, unknown>) => Promise<unknown>
  await callTool({ tool: 'Read', file_path: '/x' })
  let ui = await $.ui.mount(WORKING)
  expect((await bandText(ui, /\?/))?.trim()).toBe('\\( oo  )/ ?')
  await ui.unmount()

  await clock.advance(1_300)
  ui = await $.ui.mount(WORKING)
  expect(await bandText(ui, /\?/)).toBe(undefined)
  expect((await bandText(ui, /o o/))?.trim()).toBe('\\( o o )/')
  await ui.unmount()
})

test('the spinner word is the creature in the terminal, and left alone elsewhere or when hidden', async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on, { creature: STORED })
  engine(on)
  await $.session.start(start)

  let ui = await $.ui.mount(SPINNER)
  expect(await bandText(ui, /Gigachad|Sauteing/)).toBe('Gigachad is big-braining')
  await ui.unmount()
  const desktop = await $.ui.mount({ ...SPINNER, surface: 'desktop' })
  expect(await bandText(desktop, /Gigachad|Sauteing/)).toBe('Sauteing')
  await desktop.unmount()
  ui = await $.ui.mount({ ...SPINNER, props: { ...SPINNER.props, message: 'Compacting' } })
  expect(await bandText(ui, /Gigachad|Sauteing/)).toBe('Sauteing')
  await ui.unmount()

  await $.command.run(creatureCommand('off'))
  ui = await $.ui.mount(SPINNER)
  expect(await bandText(ui, /Gigachad|Sauteing/)).toBe('Sauteing')
  await ui.unmount()
})

test('/creature off hides it in this session and the next, and /creature on brings it back', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: STORED })
  const runs = engine(on)
  await $.session.start(start)

  expect((await $.command.run(creatureCommand('off'))).text).toMatch(/off/)
  let ui = await $.ui.mount(BAND)
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()

  // A later session: the choice was kept, and a hidden band never scans, however old its scan.
  await clock.advance(24 * HOUR)
  await $.session.start(start)
  await clock.advance(1)
  expect(runs.length).toBe(0)
  ui = await $.ui.mount(BAND)
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()

  expect((await $.command.run(creatureCommand('on'))).text).toMatch(/on/)
  ui = await $.ui.mount(BAND)
  expect(await bandText(ui, /Lv/)).toBe('  Gigachad · Lv 46 ')
  await ui.unmount()

  expect((await $.command.run(creatureCommand('please'))).text).toMatch(/Use \/creature on/)
})

test('a survey in the band comes first', async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on, { creature: STORED })
  engine(on)
  await $.session.start(start)

  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true } })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('each stage moves its own way and keeps one width', async () => {
  const looks: Look[] = ['walk', 'asleep', 'write', 'search', 'run', 'commit', 'error', 'party']
  const stages: Stage[] = ['Egg', 'Hatchling', 'Lil Guy', 'Big Guy', 'Gigachad', 'GOAT']
  for (const stage of stages) {
    const width = sprite(stage, 10, 0, 'walk').length
    for (const look of looks) for (let n = 0; n < 20; n++) expect(sprite(stage, 10, n, look).length).toBe(width)
  }
  // Gigachad walks the lane, pumping its arms.
  expect(sprite('Gigachad', 46, 0, 'walk').trimEnd()).toBe('\\( o o )/')
  expect(sprite('Gigachad', 46, 3, 'walk').trimEnd()).toBe('   _( o o )_')
  expect(sprite('Gigachad', 46, 13, 'walk').trimEnd()).toBe('   _( o o )_')
  // The Hatchling flaps, Lil Guy skips, Big Guy stomps.
  expect(sprite('Hatchling', 5, 1, 'walk').trimEnd()).toBe(' \\o o/')
  expect(sprite('Lil Guy', 15, 1, 'walk').trimEnd()).toBe(' ( ^ ^ )')
  expect(sprite('Big Guy', 30, 1, 'walk').trimEnd()).toBe(' |( o o )|')
  // The GOAT's crown sparkles.
  expect([0, 1, 2].map(n => sprite('GOAT', 60, n, 'walk').trim())).toEqual(['*( @ @ )*', '+( @ @ )+', '.( @ @ ).'])
  // The Egg wobbles where it lies and cracks as it nears hatching.
  expect(sprite('Egg', 1, 1, 'walk').trimEnd()).toBe(' ( . )')
  expect(sprite('Egg', 1, 2, 'walk').trimEnd()).toBe('( . )')
  expect(sprite('Egg', 3, 0, 'walk').trimEnd()).toBe("( .')")
  expect(sprite('Egg', 4, 0, 'walk').trimEnd()).toBe("(,.')")
  // Tools: eyes dart while searching, a barbell while running a command.
  expect(sprite('Gigachad', 46, 0, 'search').trimEnd()).toBe('\\( oo  )/ ?')
  expect(sprite('Gigachad', 46, 1, 'search').trimEnd()).toBe(' _(  oo )_  ?')
  expect(sprite('Gigachad', 46, 0, 'run').trimEnd()).toBe('o=\\( > < )/=o')
  expect(sprite('GOAT', 60, 0, 'asleep').trimEnd()).toBe('*( - - )* zZ')
})

test('the spinner word follows the tool, then what the turn is doing', async () => {
  expect(spinnerWord('Gigachad', 'search', 'tool-use')).toBe('Gigachad is sniffing around')
  expect(spinnerWord('Gigachad', 'run', 'tool-use')).toBe('Gigachad is lifting')
  expect(spinnerWord('Egg', null, 'responding')).toBe('Egg is cooking')
  expect(spinnerWord('GOAT', null, 'requesting')).toBe('GOAT is grinding')
})

test('values the mod does not control are checked before they are shown', async () => {
  expect(fromScan(SCAN, NOW)).toEqual(STORED)
  expect(asCreature(STORED)).toEqual(STORED)
  expect(fromScan({ ...SCAN, stage: 'Dragon' }, NOW)).toBe(null)
  expect(fromScan({ ...SCAN, level: 4.5 }, NOW)).toBe(null)
  expect(fromScan({ ...SCAN, mood: 'x'.repeat(41) }, NOW)).toBe(null)
  expect(fromScan({ ...SCAN, xp_today_pending: -1 }, NOW)).toBe(null)
  expect(fromScan({ ...SCAN, xp_level_start: undefined }, NOW)).toBe(null)
  expect(asCreature({ level: 46, stage: 'Gigachad', mood: 'Vibing', at: NOW })).toBe(null)
  expect(fromScan(null, NOW)).toBe(null)
})

test('the level bar runs from where the level began to the next one', async () => {
  expect(Math.abs(progress(STORED) - 1699 / 3720) < 1e-9).toBe(true)
  expect(progress({ ...STORED, xp: STORED.xpLevelStart })).toBe(0)
  expect(progress({ ...STORED, level: 99 })).toBe(1)
  expect(progress({ ...STORED, xpNextLevel: STORED.xpLevelStart })).toBe(0)
})

test('markings: the walk wears the look, every action keeps its eyes, and the width holds', async () => {
  const looks: Look[] = ['walk', 'asleep', 'write', 'search', 'run', 'commit', 'error', 'party']
  const stages: Stage[] = ['Egg', 'Hatchling', 'Lil Guy', 'Big Guy', 'Gigachad', 'GOAT']
  for (const stage of stages) {
    const width = sprite(stage, 10, 0, 'walk').length
    for (let mark = 0; mark < 64; mark++) for (const shiny of [false, true]) for (const look of looks) {
      for (let n = 0; n < 4; n++) expect(sprite(stage, 10, n, look, { look: mark, shiny }).length).toBe(width)
    }
  }
  // Look 0 is the classic creature; look 2 has wide eyes; look 32 marks the Egg's shell.
  expect(sprite('Gigachad', 46, 0, 'walk', { look: 0, shiny: false })).toBe(sprite('Gigachad', 46, 0, 'walk'))
  expect(sprite('Gigachad', 46, 0, 'walk', { look: 2, shiny: false }).trimEnd()).toBe('\\( O O )/')
  expect(sprite('Gigachad', 46, 0, 'run', { look: 2, shiny: false }).trimEnd()).toBe('o=\\( > < )/=o')
  expect(sprite('Gigachad', 46, 0, 'write', { look: 2, shiny: false })).toBe(sprite('Gigachad', 46, 0, 'write'))
  expect(sprite('Egg', 1, 2, 'walk', { look: 32, shiny: false }).trimEnd()).toBe('( o )')
  expect(sprite('GOAT', 60, 0, 'walk', { look: 3, shiny: false })).toBe(sprite('GOAT', 60, 0, 'walk'))
  // A shiny one twinkles beside itself while it walks.
  expect(sprite('Big Guy', 30, 0, 'walk', { look: 0, shiny: true }).trimEnd()).toBe('/( o o )\\ *')
})

test('the scan\'s markings are kept only when they are in range', async () => {
  expect(fromScan({ ...SCAN, marks: { look: 17, shiny: true } }, NOW)).toEqual({ ...STORED, look: 17, shiny: true })
  expect(fromScan({ ...SCAN, marks: { look: 64, shiny: true } }, NOW)).toEqual(STORED)
  expect(fromScan({ ...SCAN, marks: { look: 3, shiny: 'yes' } }, NOW)).toEqual(STORED)
  expect(fromScan({ ...SCAN, marks: null }, NOW)).toEqual(STORED)
  expect(asCreature({ ...STORED, look: -1, shiny: false })).toEqual(STORED)
})
