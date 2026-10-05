export type Choice = { label: string; description: string | null }

export type Answer = {
  selected: string[]
  text: string | null
  skipped: boolean
  created_at: string
}

export type Step = { idx: number; n: number; text: string; done: boolean }

export type Review = {
  look_at: string | null
  run_cmd: string | null
  pass_when: string | null
  fail_when: string | null
  then_do: string | null
}

export type RunResult = { exit: number | null; tail: string[]; log: string | null }

export type Row = {
  key: string
  text: string
  act: string
  kind: string
  agent: string | null
  thread: string | null
  word: string | null
  status: string
  blocked: boolean
  context: string | null
  choices: Choice[]
  allow_free: boolean
  recommend: string[] | null
  confidence: string | null
  recommend_why: string | null
  chosen: string | null
  files: string[]
  steps: Step[]
  review: Review | null
  result: RunResult | null
  answers: Answer[]
  elaborate: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'cactus-pane': {
      rows: Row[]
      picks: Record<string, string[]>
      error: string | null
      selected: string | null
      previews: Record<string, string>
      undo: string[]
      modes: Record<string, 'elaborate'>
      flips: Record<string, true>
      editing: string | null
      drafts: Record<string, string>
    }
  }
}
