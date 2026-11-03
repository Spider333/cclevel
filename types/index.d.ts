/** What the creature band shows: the last offline scan, as `cclevel.py --json --no-save` printed it. */
export type Creature = {
  level: number
  stage: 'Egg' | 'Hatchling' | 'Lil Guy' | 'Big Guy' | 'Gigachad' | 'GOAT'
  mood: string
  /** When the scan that gave these values started, in epoch milliseconds. */
  at: number
}

declare module 'claude-code' {
  interface PluginState {
    cclevel: {
      creature: Shaped<Creature | null>
      frame: number
      isHidden: boolean
      isScanning: boolean
    }
  }
}
