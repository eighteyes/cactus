// cactus-pane: a live cactus inbox pane for the session's project.
// - polls `cactus feed --json --here` and keeps the open/live/elaborate rows
// - draws a one-line rail per row and a TUI-style card for the selected one
// - the card's buttons carry the TUI's row keys (1-9, y/n, s, i, c, x, d, p)
// - acts through the `cactus` CLI, so cli.py stays the only validator
// - /cactus-pane opens the pane focused; it also opens unasked at session start
// - wakes this session when its own rows move, and turns its cactus waits off

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Answer, Row } from '../types'

const PANE = 'cactus-pane'
const POLL_MS = 3000
const PREVIEW_LINES = 40
const HISTORY = 3
const rows = atom({ plugin: 'cactus-pane', key: 'rows' } as const, [])
const picks = atom({ plugin: 'cactus-pane', key: 'picks' } as const, {})
const error = atom({ plugin: 'cactus-pane', key: 'error' } as const, null)
const selected = atom({ plugin: 'cactus-pane', key: 'selected' } as const, null)
const previews = atom({ plugin: 'cactus-pane', key: 'previews' } as const, {})
const undo = atom({ plugin: 'cactus-pane', key: 'undo' } as const, [])
const modes = atom({ plugin: 'cactus-pane', key: 'modes' } as const, {})
const flips = atom({ plugin: 'cactus-pane', key: 'flips' } as const, {})
const editing = atom({ plugin: 'cactus-pane', key: 'editing' } as const, null)
const drafts = atom({ plugin: 'cactus-pane', key: 'drafts' } as const, {})
const DRAFT_ROWS = 3
const UNDO_DEPTH = 20
const RUN_TIMEOUT_MS = 600_000

const ACT_COLOUR: Record<string, string> = {
  ask: 'cyan',
  steer: 'blue',
  run: 'red',
  review: 'magenta',
  plan: 'green',
  data: 'yellow',
  notify: 'gray',
}
const CONFIDENCE: Record<string, string> = { low: '○', med: '◐', high: '●' }
const PERSISTENT = new Set(['review', 'plan', 'data'])
const QUIET = new Set(['open', 'live'])

// The feed's change token; '' forces the next poll to rewrite the rows.
let lastCursor = ''

function firstLine(s: string | null | undefined): string {
  return (s ?? '').split('\n')[0] ?? ''
}

// Rows arrive hard-wrapped for an 80-column terminal; the pane is narrower,
// so soft breaks are joined and the pane wraps to its own width. A blank
// line, a list or tradeoff marker, an indent, or a line after a colon keeps
// its break.
const KEEP_BREAK = /^(\s|[-+*•>]\s|\d+[.)]\s|→)/

function reflow(s: string | null | undefined): string {
  const out: string[] = []
  for (const line of (s ?? '').split('\n')) {
    const prev = out[out.length - 1]
    const joins =
      prev !== undefined && prev.trim() !== '' && line.trim() !== '' &&
      !KEEP_BREAK.test(line) && !prev.trimEnd().endsWith(':')
    if (joins) out[out.length - 1] = `${prev.trimEnd()} ${line.trim()}`
    else out.push(line)
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

function verdict(a: Answer): string {
  if (a.skipped) return 'skipped'
  const label = a.selected.join(', ')
  if (label !== '' && a.text) return `${label} — ${a.text}`
  return label || a.text || ''
}

async function poll($: EngineInterface): Promise<void> {
  const ran = await $.process.run(['cactus', 'feed', '--json', '--here'], {
    cwd: await $.session.cwd(),
  })
  if (ran.exitCode === 3) {
    if (lastCursor !== 'empty') {
      lastCursor = 'empty'
      await update($, rows, () => [])
      await update($, error, () => null)
      await wake($, []).catch(() => undefined)
    }
    return
  }
  if (ran.exitCode !== 0) {
    await update($, error, () => firstLine(ran.stderr) || `feed exit ${ran.exitCode}`)
    return
  }
  const doc = JSON.parse(ran.stdout) as { cursor: unknown; questions: Row[] }
  const cursor = JSON.stringify(doc.cursor)
  if (cursor === lastCursor) return
  lastCursor = cursor
  await update($, rows, () => doc.questions)
  await update($, error, () => null)
  await wake($, doc.questions).catch(() => undefined)
}

// This session's own rows as last seen: key -> status and verdict count.
// Null until the first poll seeds it, so rows already settled never wake.
let watched: { sid: string; rows: Map<string, { status: string; n: number }> } | null = null

// What a wake says about one row, and what is left for the agent to do. A
// proper answer arrives whole and is cleared here, so it needs no get/clear.
type Moved = { row: Row; text: string; clears: boolean; heard: boolean }

function describe(row: Row): Moved {
  const last = row.answers[row.answers.length - 1]
  const asked = `${row.key} ${firstLine(row.text)}`
  if (row.status === 'cleared') {
    return { row, text: `${asked}\n  declined: the human cleared it`, clears: false, heard: false }
  }
  if (row.status === 'elaborate') {
    const hint = row.elaborate ?? 'no hint: rewrite plainly, add numbers and costs'
    return {
      row,
      text: `${asked}\n  sent back for a rewrite: ${hint}\n  rewrite it with \`cactus edit ${row.key}\``,
      clears: false,
      heard: false,
    }
  }
  if (last === undefined) return { row, text: `${asked}\n  ${row.status}`, clears: false, heard: false }
  const ran = row.result ? `\n  ran: exit ${String(row.result.exit)}${row.result.log ? `, log ${row.result.log}` : ''}` : ''
  if (PERSISTENT.has(row.act)) {
    return {
      row,
      text: `${asked}\n  verdict: ${verdict(last)}${ran}\n  respond with \`cactus ${row.act === 'plan' ? 'plan' : row.act === 'review' ? 'review' : 'edit'} ${row.key}\` once acted on`,
      clears: false,
      heard: true,
    }
  }
  if (last.skipped) {
    return { row, text: `${asked}\n  skipped: act on your stated default\n  (cleared)`, clears: true, heard: false }
  }
  return { row, text: `${asked}\n  answer: ${verdict(last)}${ran}\n  (cleared)`, clears: true, heard: false }
}

// The client end of delivery: when one of this session's rows moves, start a
// turn (queued behind a running one). A prompt the mod submits replaces the
// backgrounded wait while the mod is loaded.
async function wake($: EngineInterface, list: Row[]): Promise<void> {
  const sid = await $.session.id()
  const now = new Map(
    list.filter(r => r.agent === sid).map(r => [r.key, { status: r.status, n: r.answers.length }]),
  )
  if (watched === null || watched.sid !== sid) {
    watched = { sid, rows: now }
    return
  }
  const moved: Row[] = []
  const gone: string[] = []
  for (const [key, before] of watched.rows) {
    const after = now.get(key)
    if (after === undefined) gone.push(key)
    // A move back to open/live with no new verdict is this agent's own edit
    // answering an elaborate request: never wake on it (q334's echo rule).
    else if (after.n > before.n || (after.status !== before.status && !QUIET.has(after.status))) {
      const row = list.find(r => r.key === key)
      if (row !== undefined) moved.push(row)
    }
  }
  watched = { sid, rows: now }
  if (gone.length > 0) {
    const got = await $.process.run(['cactus', 'get', ...gone, '--json'], {
      cwd: await $.session.cwd(),
    })
    const parsed: unknown = got.exitCode === 0 ? JSON.parse(got.stdout) : null
    if (Array.isArray(parsed)) {
      // A row this agent cleared itself is not the human declining it.
      for (const row of parsed as Row[]) {
        if (row.status === 'cleared' && selfCleared.delete(row.key)) continue
        moved.push(row)
      }
    }
  }
  if (moved.length === 0) return
  const told = moved.map(describe)
  const cwd = await $.session.cwd()
  const clears = told.filter(t => t.clears).map(t => t.row.key)
  if (clears.length > 0) await $.process.run(['cactus', 'clear', ...clears, '--agent', sid], { cwd })
  // A read under the owner's --agent is what tells the human the verdict was
  // heard; the wake carries it, so the mod reads it on the agent's behalf.
  const heard = told.filter(t => t.heard).map(t => t.row.key)
  if (heard.length > 0) await $.process.run(['cactus', 'get', ...heard, '--agent', sid, '--json'], { cwd })
  // Bare, as the person's own words: no plugin frame, no header, just the rows.
  await $.prompt.submit({ text: told.map(t => t.text).join('\n\n'), asUser: true })
}

// The cactus workflow in mod mode, injected into the system prompt for as long
// as the mod is loaded; unloading it restores the session-start hook's waits.
function guide(sid: string): string {
  return [
    '# cactus (mod mode)',
    'cactus-pane is loaded: this session runs cactus in mod mode. It overrides the',
    "session-start hook's wait instructions for as long as the mod is loaded.",
    '',
    `Identity: pass \`--agent ${sid}\` on every ask, edit, plan, review and clear.`,
    '',
    '1 ask    post every decision the human makes with `cactus ask`, not chat or',
    '         AskUserQuestion: one -c per direction, --recommend LABEL --confidence L',
    '         when you have a pick, -f for every file it is about.',
    '2 post   post with --no-wait (the mod adds it when missing) and keep working.',
    '         Never background-wait: no `cactus get --wait`, no waiting ask.',
    '3 wake   the mod starts a turn, worded as the human, listing each row that moved',
    '         is answered, gets a verdict, is sent back for a rewrite, or is cleared.',
    '4 act    the wake carries each answer in full. An answered or skipped row is',
    '         already cleared: act on the answer, or on your stated default.',
    `         An elaborate row: rewrite it with \`cactus edit KEY --agent ${sid}\`.`,
    '         A review/plan verdict (already marked heard): act, then respond with',
    '         `cactus plan|review|edit`. `cactus get` only for more detail.',
    '5 clear  the rows the mod did not clear (steer, notify, review, plan, data),',
    '         by key, once acted on.',
    '',
    'The Stop hook stays quiet while you have an open row; end a turn with one open.',
  ].join('\n')
}

// Blocking `cactus ask`/`cactus run` gain --no-wait: the mod is the wait.
// Keys the agent clears through Bash, so their clear never reads as a decline.
const selfCleared = new Set<string>()

function noteClears(command: string): void {
  for (const m of command.matchAll(/\bcactus\s+clear\b([^\n;&|]*)/g)) {
    for (const word of (m[1] ?? '').split(/\s+/)) {
      if (/^([\w.-]+:)?q\d+$/.test(word)) selfCleared.add(word.replace(/^.*:/, ''))
    }
  }
}

function noWait(command: string): string {
  return command.replace(/\bcactus\s+(ask|run)\b(?![^\n;&|]*--no-wait)/g, 'cactus $1 --no-wait')
}

async function cactus(
  $: EngineInterface,
  key: string,
  args: string[],
  timeoutMs?: number,
): Promise<string | null> {
  const ran = await $.process.run(['cactus', ...args], {
    cwd: await $.session.cwd(),
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
  })
  if (ran.exitCode !== 0) {
    $.ui.toast(`cactus ${key}: ${firstLine(ran.stderr) || `exit ${ran.exitCode}`}`)
    return null
  }
  await update($, picks, all => {
    const { [key]: _gone, ...rest } = all
    return rest
  })
  lastCursor = ''
  await poll($)
  return ran.stdout
}

// An answer or verdict the pane recorded goes on the undo stack: `u` pops it.
async function answerRow($: EngineInterface, key: string, args: string[]): Promise<void> {
  if ((await cactus($, key, ['answer', key, ...args])) !== null) {
    await update($, undo, stack => [...stack.filter(k => k !== key), key].slice(-UNDO_DEPTH))
  }
}

async function undoLast($: EngineInterface): Promise<void> {
  const stack = await read($, undo)
  const key = stack[stack.length - 1]
  if (key === undefined) return
  await update($, undo, s => s.slice(0, -1))
  if ((await cactus($, key, ['undo', key])) !== null) {
    $.ui.toast(`cactus ${key}: answer withdrawn`)
    await select($, key)
  }
}

// The TUI's `R`: run the row's command; on a run row that is the approval.
async function runRow($: EngineInterface, key: string, isRunAct: boolean): Promise<void> {
  $.ui.toast(`cactus ${key}: running`)
  const out = await cactus($, key, ['exec', key], RUN_TIMEOUT_MS)
  if (out === null) return
  if (isRunAct) {
    await update($, undo, stack => [...stack.filter(k => k !== key), key].slice(-UNDO_DEPTH))
  }
  $.ui.toast(`cactus ${key}: ran — ${firstLine(out.trim().split('\n').slice(-1)[0])}`)
}

// The flip is the pane's alone: `cactus answer -s a -s b` already records
// several picks on a choice row, so the row itself never changes.
async function setFlip($: EngineInterface, key: string, on: boolean): Promise<void> {
  await update($, flips, all => {
    const { [key]: _gone, ...rest } = all
    return on ? { ...rest, [key]: true as const } : rest
  })
  await update($, picks, all => {
    const { [key]: _gone, ...rest } = all
    return rest
  })
}

// The draft is the hooks module's: the editor box and the line input both
// write it. `revs` bumps when the hooks module changes it (a line appended, a
// send clearing it), which tells the editor to adopt the new text.
const revs = new Map<string, number>()

function editorProps(key: string, label: string, text: string, active = false) {
  const what = label === 'hint' ? 'what should the rewrite say?' : label === 'note' ? 'optional note' : 'click to edit'
  return {
    label,
    placeholder: `${what} · enter newline · ctrl+s send · ctrl+x leave`,
    rev: revs.get(key) ?? 0,
    text,
    rows: DRAFT_ROWS,
    active,
  }
}

async function setDraft($: EngineInterface, key: string, text: string, bump: boolean): Promise<void> {
  if (bump) revs.set(key, (revs.get(key) ?? 0) + 1)
  await update($, drafts, all => {
    const { [key]: _gone, ...rest } = all
    return text === '' ? rest : { ...rest, [key]: text }
  })
}

// The line input: a line appends to the draft; an empty line sends the draft.
async function submitLine($: EngineInterface, key: string, line: string): Promise<void> {
  const draft = (await read($, drafts))[key] ?? ''
  if (line.trim() === '') {
    if (await submitText($, key, draft)) await setDraft($, key, '', true)
    return
  }
  await setDraft($, key, draft === '' ? line : `${draft}\n${line}`, true)
  await showDraft($, key)
}

// The draft lives in the editor box above the line input; a box scrolled out
// of view makes appended lines look lost, so bring it (and the line) in.
async function showDraft($: EngineInterface, key: string): Promise<void> {
  await $.ui.scroll({ to: { key: `${key}:editbox` }, block: 'nearest' }).catch(() => undefined)
  await $.ui.scroll({ to: { key: `${key}:line` }, block: 'nearest' }).catch(() => undefined)
}

async function leaveEditor($: EngineInterface, key: string): Promise<void> {
  await update($, editing, () => null)
  await $.ui.focus({ requestId: PANE, key: `${key}:sel` }).catch(() => undefined)
}

// One send path for the editor and the single-line fallback.
async function submitText($: EngineInterface, key: string, value: string): Promise<boolean> {
  const row = (await read($, rows)).find(r => r.key === key)
  if (row === undefined) return false
  const typed = value.trim() === '' ? [] : [value]
  if ((await read($, modes))[key] === 'elaborate') {
    await setMode($, key, null)
    await cactus($, key, ['elaborate', key, ...typed])
    return true
  }
  const isMulti = row.kind === 'multi' || (await read($, flips))[key] === true
  const mine = (await read($, picks))[key] ?? (isMulti ? (row.recommend ?? []) : [])
  const sel = isMulti ? mine.flatMap(l => ['-s', l]) : []
  if (sel.length === 0 && typed.length === 0) {
    $.ui.toast(`cactus ${key}: nothing picked or typed`)
    return false
  }
  await answerRow($, key, [...sel, ...typed])
  return true
}

async function setMode($: EngineInterface, key: string, mode: 'elaborate' | null): Promise<void> {
  await update($, modes, all => {
    const { [key]: _gone, ...rest } = all
    return mode === null ? rest : { ...rest, [key]: mode }
  })
}

async function toggle(
  $: EngineInterface,
  key: string,
  label: string,
  start: readonly string[],
): Promise<void> {
  await update($, picks, all => {
    const mine = all[key] ?? [...start]
    return {
      ...all,
      [key]: mine.includes(label) ? mine.filter(l => l !== label) : [...mine, label],
    }
  })
}

async function select($: EngineInterface, key: string): Promise<void> {
  if ((await read($, selected)) !== key) await update($, selected, () => key)
}

// The TUI's j/k: move the selection one row and bring its card into view.
async function step($: EngineInterface, by: number): Promise<void> {
  const list = await read($, rows)
  if (list.length === 0) return
  const current = await read($, selected)
  const at = Math.max(0, list.findIndex(r => r.key === current))
  const to = list[Math.min(list.length - 1, Math.max(0, at + Math.sign(by)))]
  if (to === undefined) return
  await select($, to.key)
  await $.ui.focus({ requestId: PANE, key: `${to.key}:sel` }).catch(() => undefined)
  await $.ui.scroll({ to: { key: `${to.key}:card` }, block: 'nearest' }).catch(() => undefined)
}

// Diff against HEAD when the file changed, else its head: the TUI's `o`.
async function togglePreview($: EngineInterface, path: string): Promise<void> {
  const shown = await read($, previews)
  if (path in shown) {
    await update($, previews, all => {
      const { [path]: _gone, ...rest } = all
      return rest
    })
    return
  }
  const dir = path.slice(0, path.lastIndexOf('/')) || '/'
  const diff = await $.process.run(['git', '-C', dir, 'diff', 'HEAD', '--', path], {
    timeoutMs: 2000,
  }).catch(() => null)
  const body =
    diff !== null && diff.exitCode === 0 && diff.stdout.trim() !== ''
      ? diff.stdout
      : (await $.process.run(['head', '-n', String(PREVIEW_LINES), path])).stdout
  const text = body.split('\n').slice(0, PREVIEW_LINES).join('\n')
  await update($, previews, all => ({ ...all, [path]: text }))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'cactus-pane',
      description: "Show this project's cactus inbox in a pane",
    })
    $.clock.every(POLL_MS, () => poll($))
    void poll($)
    if (e.isInteractive) void $.ui.open({ id: PANE, title: 'cactus' })

    return next(e)
  })

  on('command.run', { command: 'cactus-pane' }, async $ => {
    lastCursor = ''
    await poll($)
    await $.ui.open({ id: PANE, title: 'cactus', focus: true })

    return { text: 'cactus pane opened.' }
  })

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    const text = guide(await $.session.id())
    return {
      ...composed,
      sections: [...composed.sections, { id: 'cactus-pane:guide', text, scope: 'session' }],
    }
  })

  on('tool.call', { tool: 'Bash' }, ($, e, next) => {
    noteClears(e.command)
    return next({ ...e, command: noWait(e.command) })
  })

  // The editor posts { active } when it takes keys, { leave } on ctrl+x and
  // { submit } on ctrl+s. Esc is unreliable in a pane, so leaving and sending
  // move the ring back to the question header from here; a send also bumps
  // `reset`, which clears the draft on the next draw.
  on('ui.message', async ($, e, next) => {
    if (e.requestId !== PANE || !e.element.endsWith(':editor')) return next(e)
    const key = e.element.split(':')[0] ?? ''
    const data = (e.data ?? {}) as { submit?: unknown; leave?: unknown; active?: unknown; text?: unknown }
    if (data.active === true) {
      await update($, editing, () => key)
    } else if (data.leave === true) {
      await leaveEditor($, key)
    } else if (typeof data.submit === 'string') {
      if (await submitText($, key, data.submit)) {
        await setDraft($, key, '', true)
        await leaveEditor($, key)
      }
    }
    if (typeof data.text === 'string') await setDraft($, key, data.text, false)
    return {}
  })

  // Up/down arrive as a one-row scroll with no pointer; they move the
  // selection instead. A wheel tick carries a pointer and still scrolls.
  on('ui.scroll', async ($, e, next) => {
    if (e.requestId !== PANE || e.pointer !== undefined || Math.abs(e.by) !== 1) return next(e)
    await step($, e.by)
    return { deny: 'cactus-pane: arrows move the selection' }
  })

  // Walking the ring onto any of a row's elements selects that row.
  // The person's ring (tab or arrows; the mod cannot tell which, q479) only
  // lands on question headers: stepping into the open card jumps to the next
  // question instead. Options are picked by their keys; `i` (a plugin focus)
  // still reaches the text box.
  on('ui.focus', async ($, e, next) => {
    if (e.requestId !== PANE) return next(e)
    // The ring landing anywhere but the active editor means it was left.
    const ed = await read($, editing)
    if (ed !== null && e.element !== `${ed}:editor`) await update($, editing, () => null)
    if (e.element === undefined) return next(e)
    const [key, part] = e.element.split(':')
    if (key === undefined || key === '') return next(e)
    if (e.origin.kind === 'person' && part !== undefined && part !== 'sel') {
      const list = await read($, rows)
      const after = list[list.findIndex(r => r.key === key) + 1]
      if (after === undefined) return { deny: 'cactus-pane: last question' }
      await select($, after.key)
      return next({ ...e, element: `${after.key}:sel` })
    }
    await select($, key)
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els = $.ui.resolve(e)
    const { Box, Text, Button } = els
    const Input = 'Input' in els ? els.Input : undefined
    const Client = 'Client' in els ? els.Client : undefined
    const list = await read($, rows)
    const picked = await read($, picks)
    const failed = await read($, error)
    const shown = await read($, previews)
    const wanted = await read($, selected)
    const stack = await read($, undo)
    const modeOf = await read($, modes)
    const flipped = await read($, flips)
    const editingKey = await read($, editing)
    const drafted = await read($, drafts)
    const current = list.find(r => r.key === wanted) ?? list[0]

    const card = (row: Row) => {
      // m turns a single-choice row into pick-several for this one answer.
      const canFlip = row.kind === 'choice' && row.act !== 'data' && row.act !== 'run' && row.choices.length > 1
      const isFlipped = canFlip && flipped[row.key] === true
      const isMulti = row.kind === 'multi' || isFlipped
      const isConfirm = row.kind === 'confirm'
      const isData = row.act === 'data'
      const isPlan = row.act === 'plan'
      const isRunAct = row.act === 'run'
      const isElaborate = row.status === 'elaborate'
      const isHinting = modeOf[row.key] === 'elaborate'
      const canRun = isRunAct || Boolean(row.review?.run_cmd)
      const hasInput =
        Input !== undefined && (row.allow_free || isMulti || PERSISTENT.has(row.act) || isHinting) && !isData
      const rec = row.recommend ?? []
      // A multi row starts with its recommended set ticked, as the TUI does.
      const mine = picked[row.key] ?? (isMulti ? rec : [])
      const inputLabel = isHinting ? 'hint' : isMulti ? 'note' : PERSISTENT.has(row.act) ? 'verdict' : 'answer'
      const owner = row.agent ? ['--agent', row.agent] : []
      const pick = (label: string, surface: typeof e.surface) => {
        if (isData) {
          const body = row.choices.find(c => c.label === label)?.description ?? ''
          void $.ui.copy({ text: body, surface })
          void answerRow($, row.key, ['-s', label])
        } else if (isMulti) {
          // Park the ring on send so the next Enter submits the picks.
          void toggle($, row.key, label, rec).then(() =>
            $.ui.focus({ requestId: PANE, key: `${row.key}:send` }).catch(() => undefined),
          )
        } else if (isRunAct && label === 'approve') {
          void runRow($, row.key, true)
        } else {
          void answerRow($, row.key, ['-s', label])
        }
      }
      const confirmKey = (i: number) => (i === 0 ? 'y' : 'n')

      return (
        <Box key={`${row.key}:card`} flexDirection="column" borderStyle="round" paddingX={1}>
          <Text bold wrap="wrap">{reflow(row.text)}</Text>
          <Text dimColor>
            {[
              row.thread ? `thread ${row.thread}` : null,
              row.agent ? `agent ${row.agent.slice(0, 8)}` : null,
              row.blocked ? 'blocking' : null,
              row.status === 'open' ? null : row.status,
              row.files.length > 0 ? `${row.files.length} file(s)` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </Text>
          {row.context && (
            <Box marginTop={1} flexDirection="column">
              {reflow(row.context).split('\n\n').map((para, j) => (
                <Box key={String(j)} marginTop={j === 0 ? 0 : 1}>
                  <Text dimColor wrap="wrap">{para}</Text>
                </Box>
              ))}
            </Box>
          )}
          {isElaborate && (
            <Text color="yellow">
              waiting on a rewrite{row.elaborate ? `: ${firstLine(row.elaborate)}` : ''}
            </Text>
          )}

          {row.choices.length > 0 && (
            <Box flexDirection="column" marginTop={1}>
              {row.choices.map((c, i) => {
                const lines = (isData ? c.description ?? '' : reflow(c.description)).split('\n')
                const isPicked = mine.includes(c.label)
                return (
                  <Box key={`${row.key}:c${i}`} flexDirection="column">
                    <Box flexDirection="row" columnGap={2}>
                      <Button
                        key={`${row.key}:${c.label}`}
                        label={`${isPicked ? '✓ ' : ''}${c.label}`}
                        hotkey={isConfirm && i < 2 ? confirmKey(i) : i < 9 ? String(i + 1) : undefined}
                        plain
                        variant={rec.includes(c.label) ? 'primary' : undefined}
                        onPress={press => pick(c.label, press.surface)}
                      />
                      {rec.includes(c.label) && <Text color="yellow">recommended</Text>}
                      {row.chosen === c.label && <Text color="blue">chosen</Text>}
                      {!isData && lines[0] && <Text dimColor wrap="wrap">{lines[0]}</Text>}
                    </Box>
                    {isData && <Text dimColor>   {firstLine(c.description)}</Text>}
                    {!isData &&
                      lines.slice(1).map((l, j) =>
                        l.startsWith('+ ') ? (
                          <Text key={String(j)} color="green" wrap="wrap">   ✓ {l.slice(2)}</Text>
                        ) : l.startsWith('- ') ? (
                          <Text key={String(j)} color="red" wrap="wrap">   ✗ {l.slice(2)}</Text>
                        ) : (
                          <Text key={String(j)} dimColor wrap="wrap">   {l}</Text>
                        ),
                      )}
                  </Box>
                )
              })}
            </Box>
          )}

          {rec.length > 0 && (
            <Text color="yellow">
              recommend {rec.join(', ')} {CONFIDENCE[row.confidence ?? ''] ?? ''} {row.confidence ?? ''}
              {row.recommend_why ? ` — ${row.recommend_why}` : ''}
            </Text>
          )}

          {isPlan && row.steps.length > 0 && (
            <Box flexDirection="column" marginTop={1}>
              {row.steps.map(s => (
                <Button
                  key={`${row.key}:step${s.n}`}
                  label={`[${s.done ? 'x' : ' '}] ${s.text}`}
                  hotkey={s.n <= 9 ? String(s.n) : undefined}
                  plain
                  onPress={() =>
                    void cactus($, row.key, ['plan', row.key, s.done ? '--undone' : '--done', String(s.n)])
                  }
                />
              ))}
            </Box>
          )}

          {row.review && (
            <Box flexDirection="column" marginTop={1}>
              {row.review.look_at && <Text>look at  <Text dimColor>{row.review.look_at}</Text></Text>}
              {row.review.run_cmd && <Text>run      <Text color="cyan">{row.review.run_cmd}</Text></Text>}
              {row.review.pass_when && <Text>pass     <Text color="green">{row.review.pass_when}</Text></Text>}
              {row.review.fail_when && <Text>fail     <Text color="red">{row.review.fail_when}</Text></Text>}
              {row.review.then_do && <Text>then     <Text dimColor>{row.review.then_do}</Text></Text>}
            </Box>
          )}

          {row.result && (
            <Box flexDirection="column" marginTop={1}>
              <Text color={row.result.exit === 0 ? 'green' : 'red'}>exit {String(row.result.exit)}</Text>
              {row.result.tail.slice(-8).map((l, j) => (
                <Text key={String(j)} dimColor>{l}</Text>
              ))}
            </Box>
          )}

          {row.files.length > 0 && (
            <Box flexDirection="column" marginTop={1}>
              {row.files.map((f, j) => (
                <Box key={`${row.key}:f${j}`} flexDirection="column">
                  <Box flexDirection="row" columnGap={2}>
                    <Button
                      key={`${row.key}:open${j}`}
                      label="view"
                      hotkey={j === 0 ? 'f' : undefined}
                      plain
                      onPress={() => void $.process.run(['open', f])}
                    />
                    <Button
                      key={`${row.key}:prev${j}`}
                      label={f in shown ? 'hide' : 'preview'}
                      hotkey={j === 0 ? 'o' : undefined}
                      plain
                      onPress={() => void togglePreview($, f)}
                    />
                    <Text dimColor>{f}</Text>
                  </Box>
                  {f in shown && <Text dimColor>{shown[f]}</Text>}
                </Box>
              ))}
            </Box>
          )}

          {row.answers.length > 0 && (
            <Box flexDirection="column" marginTop={1}>
              {row.answers.slice(-HISTORY).map((a, j) => (
                <Text key={String(j)} dimColor>→ {verdict(a)}</Text>
              ))}
            </Box>
          )}

          {hasInput && Client !== undefined && (
            <Box key={`${row.key}:editbox`} marginTop={1}>
              <Client
                key={`${row.key}:editor`}
                module="./editor.tsx"
                props={editorProps(row.key, inputLabel, drafted[row.key] ?? '', editingKey === row.key)}
              />
            </Box>
          )}
          {hasInput && Client === undefined && (drafted[row.key] ?? '') !== '' && (
            <Box key={`${row.key}:draft`} borderStyle="single" paddingX={1} marginTop={1}>
              <Text wrap="wrap">{drafted[row.key]}</Text>
            </Box>
          )}
          {hasInput && Input !== undefined && (
            <Input
              key={`${row.key}:line`}
              label="line"
              placeholder="i to type · enter adds the line · enter on an empty line sends"
              submitLabel="add"
              onSubmit={(value: string) => void submitLine($, row.key, value)}
            />
          )}

          <Box flexDirection="row" columnGap={2} marginTop={1}>
            {canFlip && (
              <Button
                key={`${row.key}:flip`}
                label={isFlipped ? 'single choice' : 'multiple choice'}
                hotkey="m"
                plain
                onPress={() => void setFlip($, row.key, !isFlipped)}
              />
            )}
            {isMulti && (
              <Button
                key={`${row.key}:send`}
                label={`send ${mine.length} picked (or enter)`}
                hotkey="g"
                plain
                onPress={() =>
                  mine.length === 0
                    ? $.ui.toast(`cactus ${row.key}: nothing picked`)
                    : void answerRow($, row.key, mine.flatMap(l => ['-s', l]))
                }
              />
            )}
            {hasInput && (
              <Button
                key={`${row.key}:type`}
                label="type"
                hotkey="i"
                plain
                onPress={() =>
                  void $.ui
                    .focus({ requestId: PANE, key: `${row.key}:line` })
                    .catch(() => undefined)
                    .then(() => showDraft($, row.key))
                }
              />
            )}
            {row.act === 'notify' ? (
              <Button
                key={`${row.key}:dismiss`}
                label="dismiss"
                hotkey="d"
                plain
                onPress={() => void answerRow($, row.key, ['--dismiss'])}
              />
            ) : (
              <Button
                key={`${row.key}:skip`}
                label="skip"
                hotkey="s"
                plain
                onPress={() => void answerRow($, row.key, ['--skip'])}
              />
            )}
            {canRun && (
              <Button
                key={`${row.key}:run`}
                label="run"
                hotkey="r"
                plain
                onPress={() => void runRow($, row.key, isRunAct)}
              />
            )}
            {isElaborate ? (
              <Button
                key={`${row.key}:withdraw`}
                label="withdraw"
                hotkey="u"
                plain
                onPress={() => void cactus($, row.key, ['elaborate', row.key, '--withdraw'])}
              />
            ) : (
              <>
                <Button
                  key={`${row.key}:elaborate`}
                  label={isHinting ? 'cancel' : 'elaborate'}
                  hotkey="e"
                  plain
                  onPress={() => {
                    void setMode($, row.key, isHinting ? null : 'elaborate')
                    if (!isHinting) void $.ui.focus({ requestId: PANE, key: `${row.key}:line` }).catch(() => undefined)
                  }}
                />
                <Button
                  key={`${row.key}:decompose`}
                  label="break up"
                  hotkey="b"
                  plain
                  onPress={() => void cactus($, row.key, ['elaborate', row.key, '--decompose'])}
                />
              </>
            )}
            <Button
              key={`${row.key}:clear`}
              label={row.act === 'review' || isPlan ? 'close' : 'clear'}
              hotkey={row.act === 'review' || isPlan ? 'x' : 'c'}
              plain
              onPress={() => void cactus($, row.key, ['clear', row.key, ...owner])}
            />
            {row.agent && (
              <Button
                key={`${row.key}:poke`}
                label="poke"
                hotkey="p"
                plain
                onPress={() => void cactus($, row.key, ['poke', row.key])}
              />
            )}
          </Box>
        </Box>
      )
    }

    return (
      <Box flexDirection="column">
        {failed !== null && <Text color="red">{failed}</Text>}
        {stack.length > 0 && (
          <Box flexDirection="row" columnGap={2}>
            <Button
              key="undo"
              label={`undo ${stack[stack.length - 1]}`}
              hotkey={current?.status === 'elaborate' ? undefined : 'u'}
              plain
              onPress={() => void undoLast($)}
            />
          </Box>
        )}
        {list.length === 0 && <Text dimColor>Inbox empty.</Text>}
        {list.length > 1 && (
          <Box flexDirection="row" columnGap={2}>
            <Button key="prev" label="up" hotkey="k" plain onPress={() => void step($, -1)} />
            <Button key="next" label="down" hotkey="j" plain onPress={() => void step($, 1)} />
          </Box>
        )}
        {list.map(row => {
          const isCurrent = row === current
          return (
            <Box key={row.key} flexDirection="column">
              <Box flexDirection="row" columnGap={2}>
                <Button
                  key={`${row.key}:sel`}
                  label={`${isCurrent ? '▸' : ' '} ${row.key}`}
                  plain
                  onPress={() => {
                    // Enter on the open multi row's header sends its picks.
                    const chosen = picked[row.key] ?? row.recommend ?? []
                    if (isCurrent && (row.kind === 'multi' || flipped[row.key] === true) && chosen.length > 0) {
                      void answerRow($, row.key, chosen.flatMap(l => ['-s', l]))
                    } else void select($, row.key)
                  }}
                />
                <Text color={ACT_COLOUR[row.act] ?? 'white'}>{row.act.padEnd(6)}</Text>
                <Text wrap="truncate-end" dimColor={!isCurrent} bold={isCurrent}>
                  {row.word ? `${row.word}  ` : ''}
                  {firstLine(row.text)}
                </Text>
              </Box>
              {isCurrent && card(row)}
            </Box>
          )
        })}
      </Box>
    )
  })
}
