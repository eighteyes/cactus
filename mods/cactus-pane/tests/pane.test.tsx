// pane.test: cactus-pane against a fake `cactus` binary.
// - a one-row feed draws the row's key, text and choice buttons
// - pressing a choice runs `cactus answer KEY -s LABEL`
// - a multi row toggles picks and sends them all from the input

import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

const ROW = {
  key: 'q7',
  text: 'Which auth backend?',
  act: 'ask',
  kind: 'choice',
  agent: 'a1',
  status: 'open',
  choices: [
    { label: 'oidc', description: 'existing IdP\n+ tenant provisioned\n- IdP uptime' },
    { label: 'local', description: 'bcrypt table' },
  ],
  allow_free: true,
  recommend: ['oidc'],
  confidence: 'high',
  recommend_why: 'tenant exists',
  thread: 'auth',
  word: null,
  blocked: true,
  context: 'Staging tenant is provisioned.',
  chosen: null,
  files: [] as string[],
  steps: [] as { idx: number; n: number; text: string; done: boolean }[],
  review: null,
  result: null,
  answers: [] as { selected: string[]; text: string | null; skipped: boolean; created_at: string }[],
  elaborate: null as string | null,
}

const RUN = {
  command: 'cactus-pane',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: false, columns: 120 },
} as const

const PANE = {
  plugin: 'cactus-pane',
  component: 'Pane',
  requestId: 'cactus-pane',
  props: {
    title: 'cactus',
    isFocused: true,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

// Type into a row's editor key by key, as the person would.
async function typeIn(ui: { key: (e: { key: string; in?: string }) => Promise<void> }, row: string, text: string) {
  for (const ch of text) await ui.key({ key: ch, in: `${row}:editor` })
}

function fakeCactus(row: typeof ROW, calls: string[][]) {
  let answered = false
  return (argv: readonly string[]) => {
    calls.push([...argv])
    if (argv[1] === 'answer') {
      answered = true
      return { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false }
    }
    if (argv[1] === 'get') {
      const label = calls.find(c => c[1] === 'answer')?.[4] ?? ''
      const settled = {
        ...row,
        status: 'answered',
        answers: [{ selected: [label], text: null, skipped: false, created_at: '' }],
      }
      return {
        exitCode: 0,
        stdout: JSON.stringify([settled]),
        stderr: '',
        isStdoutTruncated: false,
        isStderrTruncated: false,
      }
    }
    const questions = answered ? [] : [row]
    return {
      exitCode: 0,
      stdout: JSON.stringify({ cursor: { n: answered ? 1 : 0 }, questions }),
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    }
  }
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`a choice press answers the row (${surface})`, async ($, on) => {
    const calls: string[][] = []
    const fake = fakeCactus(ROW, calls)
    on('process.run', (_$, e) => ({ value: fake(e.argv) }))
    on('session.cwd', () => ({ value: '/repo' }))
    on('session.id', () => ({ value: 'a1' }))
    on('ui.open', () => ({ value: { isPlaced: true } }))
    on('ui.toast', () => ({ value: undefined }))

    await $.command.run(RUN)
    const ui = await $.ui.mount({ ...PANE, surface })

    expect((await ui.find({ text: /Which auth backend/ }))?.text).toContain('q7')
    expect(await ui.find({ key: 'q7:oidc' })).toBeDefined()

    await ui.press({ key: 'q7:local' })
    expect(calls).toContainEqual(['cactus', 'answer', 'q7', '-s', 'local'])
    expect(await ui.find({ text: /Inbox empty/ })).toBeDefined()
  })

  test(`a multi row sends every pick (${surface})`, async ($, on) => {
    const calls: string[][] = []
    const fake = fakeCactus({ ...ROW, kind: 'multi' }, calls)
    on('process.run', (_$, e) => ({ value: fake(e.argv) }))
    on('session.cwd', () => ({ value: '/repo' }))
    on('session.id', () => ({ value: 'a1' }))
    on('ui.open', () => ({ value: { isPlaced: true } }))
    on('ui.toast', () => ({ value: undefined }))

    await $.command.run(RUN)
    const ui = await $.ui.mount({ ...PANE, surface })

    // oidc, the recommendation, starts ticked; ticking local adds it.
    await ui.press({ key: 'q7:local' })
    expect(calls.some(c => c[1] === 'answer')).toBe(false)

    await ui.key({ key: 's', ctrl: true, in: 'q7:editor' })
    expect(calls).toContainEqual(['cactus', 'answer', 'q7', '-s', 'oidc', '-s', 'local'])
  })
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`the card shows context, tradeoffs and the recommendation (${surface})`, async ($, on) => {
    const calls: string[][] = []
    const fake = fakeCactus(ROW, calls)
    on('process.run', (_$, e) => ({ value: fake(e.argv) }))
    on('session.cwd', () => ({ value: '/repo' }))
    on('session.id', () => ({ value: 'a1' }))
    on('ui.open', () => ({ value: { isPlaced: true } }))
    on('ui.toast', () => ({ value: undefined }))

    await $.command.run(RUN)
    const ui = await $.ui.mount({ ...PANE, surface })

    expect(await ui.find({ text: /Staging tenant is provisioned/ })).toBeDefined()
    expect(await ui.find({ text: /✓ tenant provisioned/ })).toBeDefined()
    expect(await ui.find({ text: /✗ IdP uptime/ })).toBeDefined()
    expect(await ui.find({ text: /recommend oidc .* tenant exists/ })).toBeDefined()

    await ui.press({ key: 'q7:clear' })
    expect(calls).toContainEqual(['cactus', 'clear', 'q7', '--agent', 'a1'])
  })
}

async function mounted($: Parameters<TestBody>[0], on: Parameters<TestBody>[1], row: typeof ROW, calls: string[][], surface: 'terminal' | 'desktop') {
  const fake = fakeCactus(row, calls)
  on('process.run', (_$, e) => ({ value: fake(e.argv) }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.id', () => ({ value: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.focus', () => ({}))
  await $.command.run(RUN)
  return $.ui.mount({ ...PANE, surface })
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`undo withdraws the answer the pane just sent (${surface})`, async ($, on) => {
    const calls: string[][] = []
    const ui = await mounted($, on, ROW, calls, surface)
    await ui.press({ key: 'q7:oidc' })
    await ui.press({ key: 'undo' })
    expect(calls).toContainEqual(['cactus', 'undo', 'q7'])
  })

  test(`elaborate sends the typed hint; break up decomposes (${surface})`, async ($, on) => {
    const calls: string[][] = []
    const ui = await mounted($, on, ROW, calls, surface)
    await ui.press({ key: 'q7:elaborate' })
    await typeIn(ui, 'q7', 'say what local costs')
    await ui.key({ key: 's', ctrl: true, in: 'q7:editor' })
    expect(calls).toContainEqual(['cactus', 'elaborate', 'q7', 'say what local costs'])
    await ui.press({ key: 'q7:decompose' })
    expect(calls).toContainEqual(['cactus', 'elaborate', 'q7', '--decompose'])
  })

  test(`approving a run row runs it (${surface})`, async ($, on) => {
    const calls: string[][] = []
    const runRow = {
      ...ROW,
      act: 'run',
      kind: 'confirm',
      text: 'echo hi',
      choices: [
        { label: 'approve', description: null as unknown as string },
        { label: 'deny', description: null as unknown as string },
      ],
    }
    const ui = await mounted($, on, runRow, calls, surface)
    await ui.press({ key: 'q7:approve' })
    expect(calls).toContainEqual(['cactus', 'exec', 'q7'])
    expect(calls.some(c => c[1] === 'answer')).toBe(false)
  })
}

test('hard-wrapped context reflows; blank lines and lists keep their breaks', async ($, on) => {
  const calls: string[][] = []
  const row = { ...ROW, context: 'The staging tenant\nis provisioned.\n\nCosts:\n- one\n- two' }
  const ui = await mounted($, on, row, calls, 'terminal')
  expect(await ui.find({ text: 'The staging tenant is provisioned.' })).toBeDefined()
  expect(await ui.find({ text: /Costs:\n- one\n- two/ })).toBeDefined()
})

test('answering this session’s own row wakes it with the verdict', async ($, on) => {
  const calls: string[][] = []
  const woke: string[] = []
  on('prompt.submit', (_$, e) => {
    woke.push(e.text)
    return { value: { turnId: 't' } } as never
  })
  const ui = await mounted($, on, ROW, calls, 'terminal')
  await ui.press({ key: 'q7:local' })
  expect(woke.join('\n')).toContain('answer: local')
  expect(woke.join('\n')).toContain('(cleared)')
  expect(calls).toContainEqual(['cactus', 'clear', 'q7', '--agent', 'a1'])
})

test('j and k move the selection between questions', async ($, on) => {
  const calls: string[][] = []
  const two = { ...ROW }
  const fake = (argv: readonly string[]) => {
    calls.push([...argv])
    const second = { ...two, key: 'q8', text: 'Second question?' }
    return {
      exitCode: 0,
      stdout: JSON.stringify({ cursor: { n: 0 }, questions: [two, second] }),
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    }
  }
  on('process.run', (_$, e) => ({ value: fake(e.argv) }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.id', () => ({ value: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.focus', () => ({}))
  on('ui.scroll', () => ({}))
  await $.command.run(RUN)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ key: 'q7:card' })).toBeDefined()
  await ui.press({ key: 'next' })
  expect(await ui.find({ key: 'q8:card' })).toBeDefined()
  expect(await ui.find({ key: 'q7:card' })).toBeUndefined()
  await ui.press({ key: 'prev' })
  expect(await ui.find({ key: 'q7:card' })).toBeDefined()
})

test('the editor takes several lines; return is a newline, ctrl+s sends', async ($, on) => {
  const calls: string[][] = []
  const ui = await mounted($, on, ROW, calls, 'terminal')
  await typeIn(ui, 'q7', 'line one')
  await ui.key({ key: 'return', in: 'q7:editor' })
  await typeIn(ui, 'q7', 'line two')
  expect(calls.some(c => c[1] === 'answer')).toBe(false)
  await ui.key({ key: 's', ctrl: true, in: 'q7:editor' })
  expect(calls).toContainEqual(['cactus', 'answer', 'q7', 'line one\nline two'])
})

test('a multi row starts with its recommendation ticked; send or enter on the header submits', async ($, on) => {
  const calls: string[][] = []
  const ui = await mounted($, on, { ...ROW, kind: 'multi' }, calls, 'terminal')
  expect((await ui.find({ key: 'q7:send' }))?.text).toContain('send 1 picked')
  await ui.press({ key: 'q7:local' })
  await ui.press({ key: 'q7:sel' })
  expect(calls).toContainEqual(['cactus', 'answer', 'q7', '-s', 'oidc', '-s', 'local'])
})

test('m turns a single-choice row into pick-several for one answer', async ($, on) => {
  const calls: string[][] = []
  const ui = await mounted($, on, ROW, calls, 'terminal')
  await ui.press({ key: 'q7:flip' })
  await ui.press({ key: 'q7:local' })
  expect(calls.some(c => c[1] === 'answer')).toBe(false)
  await ui.press({ key: 'q7:send' })
  expect(calls).toContainEqual(['cactus', 'answer', 'q7', '-s', 'oidc', '-s', 'local'])
})
