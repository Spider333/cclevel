// Tests for the creature band (hooks/creature.tsx). Run with: claude plugin test .
import type { CommandRunInput, On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { asCreature, sprite } from '../hooks/creature'

const HOUR = 60 * 60 * 1000
const NOW = 1_800_000_000_000
const SCAN = { level: 46, stage: 'Gigachad', mood: 'Vibing', class: 'Shipper', xp: 86339 }

const BAND = {
  plugin: 'cclevel',
  component: 'AbovePrompt',
  surface: 'terminal',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 9 },
    view: {},
  },
} as const

/** The engine beneath the plugin: commands register, a session starts, and each scan is recorded. */
function engine(on: On, scan: { exitCode: number; stdout: string } = { exitCode: 0, stdout: JSON.stringify(SCAN) }) {
  const runs: (readonly string[])[] = []
  on('command.register', () => ({ value: { command: 'creature' } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('process.run', (_, e) => {
    runs.push(e.argv)
    return { value: { exitCode: scan.exitCode, stdout: scan.stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })
  return runs
}

const start = { cwd: '/', surface: 'terminal', isInteractive: true } as const

/** `/creature <args>` as the person types it; the engine stamps `origin` and `presentation` itself. */
const creatureCommand = (args: string) => ({ command: 'creature', args }) as unknown as CommandRunInput

test('a fresh install scans once, offline, and shows the creature asleep', async ($, on) => {
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
  expect((await ui.find({ type: 'Text', text: /Lv/ }))?.text).toBe('  Gigachad · Lv 46 · Vibing')
  expect((await ui.find({ type: 'Text', text: /zZ/ }))?.text.trim()).toBe('\\( - - )/ zZ')
  await ui.unmount()
})

test('a scan from the last six hours is shown at once and not repeated', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { level: 12, stage: 'Hatchling', mood: 'Locked in', at: NOW - HOUR } })
  const runs = engine(on)

  await $.session.start(start)
  await clock.advance(1)

  expect(runs.length).toBe(0)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, isWorking: true } })
  expect((await ui.find({ type: 'Text', text: /Lv/ }))?.text).toBe('  Hatchling · Lv 12 · Locked in')
  expect((await ui.find({ type: 'Text', text: /o o/ }))?.text.trimEnd()).toBe('/o o\\')
  await ui.unmount()
})

test('an old scan is shown and replaced, unless another session is already scanning', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, {
    creature: { level: 12, stage: 'Hatchling', mood: 'Locked in', at: NOW - 7 * HOUR },
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

  const ui = await $.ui.mount(BAND)
  expect((await ui.find({ type: 'Text', text: /Lv/ }))?.text).toBe('  Gigachad · Lv 46 · Vibing')
  await ui.unmount()
})

test('a scan that fails or prints something else keeps the creature that was there', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { level: 12, stage: 'Hatchling', mood: 'Locked in', at: NOW - 7 * HOUR } })
  const runs = engine(on, { exitCode: 0, stdout: 'not json' })

  await $.session.start(start)
  await clock.advance(1)
  expect(runs.length).toBe(1)

  const ui = await $.ui.mount(BAND)
  expect((await ui.find({ type: 'Text', text: /Lv/ }))?.text).toBe('  Hatchling · Lv 12 · Locked in')
  await ui.unmount()
})

test('/creature off hides it in this session and the next, and /creature on brings it back', async ($, on) => {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on, { creature: { level: 46, stage: 'Gigachad', mood: 'Vibing', at: NOW } })
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
  expect((await ui.find({ type: 'Text', text: /Lv/ }))?.text).toBe('  Gigachad · Lv 46 · Vibing')
  await ui.unmount()

  expect((await $.command.run(creatureCommand('please'))).text).toMatch(/Use \/creature on/)
})

test('a survey in the band comes first', async ($, on) => {
  mock.clock(on, { now: NOW })
  mock.store(on, { creature: { level: 46, stage: 'Gigachad', mood: 'Vibing', at: NOW } })
  engine(on)
  await $.session.start(start)

  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true } })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine')
  await ui.unmount()
})

test('the creature walks to and fro, blinks, and keeps one width', async () => {
  const width = '\\( o o )/'.length + 8
  expect(sprite('Gigachad', 0, true)).toBe('\\( o o )/'.padEnd(width))
  expect(sprite('Gigachad', 3, true)).toBe('   \\( o o )/'.padEnd(width))
  expect(sprite('Gigachad', 8, true)).toBe('        \\( - - )/')
  expect(sprite('Gigachad', 13, true)).toBe('   \\( o o )/'.padEnd(width))
  expect(sprite('GOAT', 0, false)).toBe('*( - - )* zZ'.padEnd('*( @ @ )*'.length + 8))
  for (let n = 0; n < 40; n++) expect(sprite('Egg', n, true).length).toBe('( . )'.length + 8)
})

test('values the mod does not control are checked before they are shown', async () => {
  expect(asCreature(SCAN, NOW)).toEqual({ level: 46, stage: 'Gigachad', mood: 'Vibing', at: NOW })
  expect(asCreature({ ...SCAN, stage: 'Dragon' }, NOW)).toBe(null)
  expect(asCreature({ ...SCAN, level: 4.5 }, NOW)).toBe(null)
  expect(asCreature({ ...SCAN, mood: 'x'.repeat(41) }, NOW)).toBe(null)
  expect(asCreature(SCAN, undefined)).toBe(null)
  expect(asCreature(null, NOW)).toBe(null)
})
