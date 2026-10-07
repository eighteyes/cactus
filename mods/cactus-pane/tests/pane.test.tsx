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
    expect(await ui.find({ text: /Cactus inbox empty/ })).toBeDefined()
    expect(await ui.find({ text: /Decisions incoming/ })).toBeDefined()
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

    await ui.input({ key: 'q7:text', text: '' })
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
    await ui.input({ key: 'q7:text', text: 'say what local costs' })
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
    return { text: e.text }
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




test('enter sends one line; a trailing backslash keeps the line for a multi-line answer', async ($, on) => {
  const calls: string[][] = []
  const ui = await mounted($, on, ROW, calls, 'terminal')
  await ui.input({ key: 'q7:text', text: 'first line\\' })
  expect(calls.some(c => c[1] === 'answer')).toBe(false)
  expect((await ui.find({ key: 'q7:draft' }))?.text).toContain('first line')
  await ui.input({ key: 'q7:text', text: 'second line' })
  expect(calls).toContainEqual(['cactus', 'answer', 'q7', 'first line\nsecond line'])
})

test('a stale row marks its header with how long it sat untouched', async ($, on) => {
  const calls: string[][] = []
  const ui = await mounted($, on, { ...ROW, stale: true, idle_hours: 50.2 } as typeof ROW, calls, 'terminal')
  expect((await ui.find({ key: 'q7:stale' }))?.text).toContain('stale 2d')
})

test('a fresh row has no stale mark', async ($, on) => {
  const calls: string[][] = []
  const ui = await mounted($, on, ROW, calls, 'terminal')
  expect(await ui.find({ key: 'q7:stale' })).toBeUndefined()
})

test('a pass that closed a review wakes with the verdict, not a decline', async ($, on) => {
  const woke: string[] = []
  on('prompt.submit', (_$, e) => {
    woke.push(e.text)
    return { text: e.text }
  })
  const choices = [{ label: 'pass', description: null }, { label: 'fail', description: null }]
  const review = { ...ROW, act: 'review', kind: 'choice', status: 'live', choices, recommend: null, confidence: null, answers: [] as typeof ROW.answers }
  const closed = { ...review, status: 'cleared', closed_by_pass: true, answers: [{ selected: ['pass'], text: null, skipped: false, created_at: 't' }] }
  let served: unknown = review
  let n = 0
  on('process.run', (_$, e) => {
    if (e.argv.includes('answer')) served = closed
    n += 1
    return { value: { exitCode: 0, stdout: JSON.stringify({ cursor: { n }, questions: [served] }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.id', () => ({ value: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.focus', () => ({}))
  await $.command.run(RUN)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'q7:pass' })
  const all = woke.join('\n')
  expect(all).toContain('verdict: pass')
  expect(all).not.toContain('declined')
})
