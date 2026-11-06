export type Stage = 'Egg' | 'Hatchling' | 'Lil Guy' | 'Big Guy' | 'Gigachad' | 'GOAT'

/** What the creature band shows: the last offline scan, as `cclevel.py --json --no-save` printed it. */
export type Creature = {
  level: number
  stage: Stage
  mood: string
  xp: number
  /** XP where this level began and where the next one begins: the level bar's two ends. */
  xpLevelStart: number
  xpNextLevel: number
  /** XP earned today so far; it is banked when the day is over. */
  xpToday: number
  /** When the scan that gave these values started, in epoch milliseconds. */
  at: number
  /** The creature's markings (0 to 63) and whether it is shiny, from the scan's `marks`. Missing means the classic look. */
  look?: number
  shiny?: boolean
  /** The class from the scan (`class`), for the hatch's words. */
  cls?: string
  /** The ledger's first day from the scan, or null before there is a ledger: whether this machine is new. */
  hatched?: string | null
}

/** What the creature is acting out: the kind of tool Claude is using, or how the last one ended. */
export type Action = { kind: 'write' | 'search' | 'run' | 'commit' | 'error'; id: number }

/** A level up (or a new stage) to celebrate for a few seconds. */
export type Burst = {
  level: number; stage: Stage; from: Stage; id: number
  /** The first creature hatching on a new machine: its words, and the frame it started on. */
  hatch?: string; frame?: number
}

declare module 'claude-code' {
  interface PluginState {
    cclevel: {
      creature: Shaped<Creature | null>
      frame: number
      isHidden: boolean
      isScanning: boolean
      action: Shaped<Action | null>
      burst: Shaped<Burst | null>
    }
  }
}
