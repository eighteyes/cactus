// cactus-pane: a live cactus inbox pane for the session's project.
// - polls `cactus feed --json --here` and keeps the open/live/elaborate rows
// - draws a one-line rail per row and a TUI-style card for the selected one
// - the card's buttons carry the TUI's row keys (1-9, y/n, s, i, c, x, d, e, b, r, m)
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
// Headers drawn at once, centred on the selection, so its card stays in view.
const LIST_WINDOW = 7
const rows = atom({ plugin: 'cactus-pane', key: 'rows' } as const, [])
const picks = atom({ plugin: 'cactus-pane', key: 'picks' } as const, {})
const error = atom({ plugin: 'cactus-pane', key: 'error' } as const, null)
const selected = atom({ plugin: 'cactus-pane', key: 'selected' } as const, null)
const previews = atom({ plugin: 'cactus-pane', key: 'previews' } as const, {})
const undo = atom({ plugin: 'cactus-pane', key: 'undo' } as const, [])
const modes = atom({ plugin: 'cactus-pane', key: 'modes' } as const, {})
const flips = atom({ plugin: 'cactus-pane', key: 'flips' } as const, {})
const drafts = atom({ plugin: 'cactus-pane', key: 'drafts' } as const, {})
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
  if (row.status === 'cleared' && row.closed_by_pass === true && last !== undefined) {
    return { row, text: `${asked}\n  verdict: ${verdict(last)}\n  (the pass closed it)`, clears: false, heard: false }
  }
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
  const before = (await read($, rows)).map(r => r.key)
  lastCursor = ''
  await poll($)
  await refocus($, key, before)
  return ran.stdout
}

// A row that left the inbox takes the focus ring with it, and a pane with no
// ring hears no arrows. Land it on the header of the row now in that place.
async function refocus($: EngineInterface, key: string, before: string[]): Promise<void> {
  const now = (await read($, rows)).map(r => r.key)
  if (now.includes(key)) return
  const at = before.indexOf(key)
  const after = before.slice(at + 1).find(k => now.includes(k))
  const prior = before.slice(0, Math.max(0, at)).reverse().find(k => now.includes(k))
  const target = after ?? prior
  if (target === undefined) return
  await select($, target)
  await $.ui.focus({ requestId: PANE, key: `${target}:sel` }).catch(() => undefined)
  await pinTop($, target)
}

// An answer or verdict the pane recorded goes on the undo stack: `u` pops it.
async function answerRow($: EngineInterface, key: string, args: string[]): Promise<void> {
  const row = (await read($, rows)).find(r => r.key === key)
  if ((await cactus($, key, ['answer', key, ...args])) !== null) {
    await update($, undo, stack => [...stack.filter(k => k !== key), key].slice(-UNDO_DEPTH))
    // A review or plan stays open after a verdict; move on to the next
    // question so the one just sent does not sit under the reader.
    if (row !== undefined && PERSISTENT.has(row.act)) await advancePast($, key)
  }
}

// Select the question after `key`, wrapping to the top; a no-op when `key` is
// not the selected one any more or is the only question left.
async function advancePast($: EngineInterface, key: string): Promise<void> {
  const list = await read($, rows)
  // Nothing stored yet means the first question is the open one.
  if (((await read($, selected)) ?? list[0]?.key) !== key || list.length < 2) return
  const at = list.findIndex(r => r.key === key)
  const to = list[(at + 1) % list.length]
  if (to === undefined || to.key === key) return
  await select($, to.key)
  await $.ui.focus({ requestId: PANE, key: `${to.key}:sel` }).catch(() => undefined)
  await pinTop($, to.key)
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
async function setFlip($: EngineInterface, key: string, flipOn: boolean): Promise<void> {
  await update($, flips, all => {
    const { [key]: _gone, ...rest } = all
    return flipOn ? { ...rest, [key]: true as const } : rest
  })
  await update($, picks, all => {
    const { [key]: _gone, ...rest } = all
    return rest
  })
}

async function setDraft($: EngineInterface, key: string, text: string): Promise<void> {
  await update($, drafts, all => {
    const { [key]: _gone, ...rest } = all
    return text === '' ? rest : { ...rest, [key]: text }
  })
}

// One input line; enter sends. Multi-line is hidden until asked for: a line
// ending in `\` is kept (without the `\`) and shown above the input, and the
// next plain enter sends every kept line plus that one.
async function submitLine($: EngineInterface, key: string, line: string): Promise<void> {
  const draft = (await read($, drafts))[key] ?? ''
  if (line.endsWith('\\')) {
    const kept = line.slice(0, -1)
    await setDraft($, key, draft === '' ? kept : `${draft}\n${kept}`)
    return
  }
  const full = draft === '' ? line : line === '' ? draft : `${draft}\n${line}`
  if (await submitText($, key, full)) await setDraft($, key, '')
}

// Enter on the open question never answers on its own: an enter meant to open
// the next question sent its recommendation (q622). It sends only a note you
// typed and kept as a draft (with any ticks on a multi row); otherwise a digit
// answers, `g` sends a multi pick, and the text line sends on its own enter.
async function enterOnOpen($: EngineInterface, row: Row): Promise<void> {
  const draft = (await read($, drafts))[row.key] ?? ''
  if (draft !== '') {
    if (await submitText($, row.key, draft)) await setDraft($, row.key, '')
    return
  }
  if (row.choices.length === 0 && row.act !== 'run') {
    await $.ui.focus({ requestId: PANE, key: `${row.key}:text` }).catch(() => undefined)
    return
  }
  $.ui.toast(`cactus ${row.key}: enter does not answer; press a digit or type a note${row.kind === 'multi' ? ', then g to send' : ''}`)
}

// The send path behind the input line.
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

// Keep the open question's header in view.
// The empty inbox: a braille sunset drawn at the pane's width. Sky dots
// thicken toward the horizon around a half-set sun; an armed saguaro stands on
// the left and a stand of single stalks on the right. Every cactus is lit on
// the side facing the sun and shadowed on the other (solid outline, solid rib,
// sparse shadow column), and casts a long ground shadow away from it.
const ART_ROWS = 9
const ART_MIN_COLUMNS = 20
const GROVE_STALKS = 3
// Dot row each stalk's top reaches: tall, middle, short (the sky is 28 dots).
const GROVE_TOPS = [5, 12, 19]
const HORIZON = 28
const SKY_COLOURS = ['#4b2a6b', '#6e2f6e', '#9a3468', '#c4405e', '#e05a4f', '#f07f45', '#f9a640']
const SUN_COLOUR = '#ffd166'
const CACTUS_LIT = '#3f9a5c'
const CACTUS_SHADE = '#24603a'
const GROUND_COLOUR = '#8a5a3c'
const SHADOW_COLOUR = '#4a2c2a'
const BRAILLE_BITS: [number, number, number][] = [
  [0, 0, 0x01], [0, 1, 0x02], [0, 2, 0x04], [1, 0, 0x08],
  [1, 1, 0x10], [1, 2, 0x20], [0, 3, 0x40], [1, 3, 0x80],
]
const STIPPLE: Record<number, number[]> = { 1: [0], 2: [0, 2], 3: [0, 1, 2], 4: [0, 1, 2, 3] }

// A cactus part: dot rectangles [x0, x1, y0, y1] inclusive, how many of every
// 4 rows each interior column draws (absent: all 4), and its base span on the
// ground, which casts the shadow.
type Part = { rects: [number, number, number, number][]; cols: Record<number, number>; base: [number, number] }
// Stipple phase counts from each part's left edge, so every stalk shades alike.

// Fixed hash in [0, 1): the same art at the same width, every draw.
function noise(x: number, y: number): number {
  let mix = (Math.imul(x, 374761393) + Math.imul(y, 668265263)) >>> 0
  mix = Math.imul(mix ^ (mix >>> 13), 1274126177) >>> 0
  return ((mix ^ (mix >>> 16)) >>> 0) / 2 ** 32
}

// The armed saguaro on the left, lit from the right (the sun is east of it).
function saguaro(): Part[] {
  const base: [number, number] = [17, 22]
  return [
    { rects: [[17, 22, 5, 99], [18, 21, 4, 4]], cols: { 18: 1, 19: 4, 20: 2, 21: 4 }, base },
    { rects: [[10, 14, 13, 23], [11, 13, 12, 12]], cols: { 11: 1, 12: 2, 13: 1 }, base },
    { rects: [[10, 17, 21, 24]], cols: { 11: 1, 12: 1, 13: 1, 14: 1, 15: 1, 16: 1 }, base },
    { rects: [[25, 29, 9, 19], [26, 28, 8, 8]], cols: { 26: 2, 27: 4, 28: 3 }, base },
    { rects: [[22, 29, 17, 20]], cols: { 23: 3, 24: 3, 25: 3, 26: 3, 27: 4, 28: 3 }, base },
  ]
}

// Three single stalks bunched on the right, past the sun: each lit on
// the side facing it (west), shadowed on the east, heights from the hash.
// Tallest first, so a shorter stalk in front keeps its own outline.
function grove(dotWidth: number, sunX: number): Part[] {
  const out: Part[] = []
  // Even columns only: every stalk then splits into braille cells the same way.
  // Laid right to left from the pane's edge; a stalk too close to the sun is
  // dropped, so a narrow pane gets fewer.
  let x = (dotWidth - 9) & ~1
  // Three clearly different heights (tall, middle, short), dealt in an order
  // the width picks, so the stand never reads as one height.
  const turn = Math.floor(noise(dotWidth, 3) * GROVE_TOPS.length)
  for (let i = 0; i < GROVE_STALKS && x >= sunX + 12; i++) {
    const top = GROVE_TOPS[(i + turn) % GROVE_TOPS.length] ?? 12
    const lit = x + 2 < sunX
    const cols = lit ? { [x + 1]: 1, [x + 2]: 4, [x + 3]: 3 } : { [x + 1]: 3, [x + 2]: 4, [x + 3]: 1 }
    out.push({ rects: [[x, x + 4, top, 99], [x + 1, x + 3, top - 1, top - 1]], cols, base: [x, x + 4] })
    x -= 6 + 2 * Math.floor(noise(x, 7) * 2)
  }
  return out.sort((p, q) => (q.rects[0]?.[2] ?? 0) - (p.rects[0]?.[2] ?? 0))
}

function sunsetArt(columns: number): [string, string | undefined][][] {
  const dotWidth = columns * 2
  const dotHeight = ART_ROWS * 4
  const sunX = Math.round(dotWidth * 0.52)
  const sunR = 10
  const parts = [...saguaro(), ...grove(dotWidth, sunX)]
  const partAt = (x: number, y: number) =>
    y < dotHeight ? parts.find(p => p.rects.some(([x0, x1, y0, y1]) => x >= x0 && x <= x1 && y >= y0 && y <= y1)) : undefined
  const sides: [number, number][] = [[1, 0], [-1, 0], [0, 1], [0, -1]]
  const cactusDot = (x: number, y: number): boolean | undefined => {
    const p = partAt(x, y)
    if (p === undefined) return undefined
    // An edge against open sky or another cactus: stalks in a stand stay apart.
    if (sides.some(([dx, dy]) => y + dy < dotHeight && partAt(x + dx, y + dy) !== p && !sameCactus(p, partAt(x + dx, y + dy)))) return true
    return (STIPPLE[p.cols[x] ?? 4] ?? []).includes((y + x - p.base[0]) % 4)
  }
  // The saguaro's parts are one plant: no outline between trunk and arm.
  const plant = new Set(parts.slice(0, 5))
  const sameCactus = (p: Part, q: Part | undefined) => q !== undefined && plant.has(p) && plant.has(q)
  // Long evening shadows on the ground, cast away from the sun, thinning out.
  const shadow = (x: number, y: number) =>
    y >= HORIZON && parts.some(({ base: [x0, x1] }) => {
      const away = x0 > sunX ? x - x1 : x0 - x
      const reach = 18 - (y - HORIZON)
      return away > 0 && away <= reach
    })
  const sun = (x: number, y: number) => y < HORIZON && (x - sunX) ** 2 + (y - HORIZON) ** 2 <= sunR * sunR
  const sky = (x: number, y: number) => {
    const t = y / HORIZON
    const glow = Math.max(0, 1 - Math.hypot(x - sunX, (y - HORIZON) * 1.8) / 22)
    return noise(x, y) < Math.min(0.9, 0.02 + 0.6 * t ** 2.4 + 0.35 * glow)
  }
  const ground = (x: number, y: number) => {
    const t = (y - HORIZON) / (dotHeight - HORIZON)
    const reflect = Math.abs(x - sunX) < 8 - 2 * (y - HORIZON) && y % 2 === 0
    return reflect || y === HORIZON || noise(x + 91, y) < 0.18 - 0.12 * t
  }
  const lines: [string, string | undefined][][] = []
  for (let cy = 0; cy < ART_ROWS; cy++) {
    const line: [string, string | undefined][] = []
    for (let cx = 0; cx < columns; cx++) {
      let cactusBits = 0, inCactus = false, sunBits = 0, skyBits = 0, groundBits = 0, shadeBits = 0
      for (const [dx, dy, bit] of BRAILLE_BITS) {
        const x = cx * 2 + dx, y = cy * 4 + dy
        const c = cactusDot(x, y)
        if (c !== undefined) {
          inCactus = true
          if (c) cactusBits |= bit
        } else if (sun(x, y)) sunBits |= bit
        else if (y < HORIZON && sky(x, y)) skyBits |= bit
        else if (y >= HORIZON && shadow(x, y)) {
          if ((x + y) % 2 === 0) shadeBits |= bit
        } else if (y >= HORIZON && ground(x, y)) groundBits |= bit
      }
      let cell: [string, string | undefined] = [' ', undefined]
      if (inCactus) {
        const lit = cactusBits.toString(2).split('1').length - 1 >= 5
        cell = [String.fromCharCode(0x2800 | cactusBits), lit ? CACTUS_LIT : CACTUS_SHADE]
      } else if (sunBits) cell = [String.fromCharCode(0x2800 | sunBits), SUN_COLOUR]
      else if (skyBits) cell = [String.fromCharCode(0x2800 | skyBits), SKY_COLOURS[Math.min(SKY_COLOURS.length - 1, cy)]]
      else if (shadeBits) cell = [String.fromCharCode(0x2800 | shadeBits), SHADOW_COLOUR]
      else if (groundBits) {
        const nearSun = Math.abs(cx * 2 - sunX) < 8
        cell = [String.fromCharCode(0x2800 | groundBits), nearSun ? SUN_COLOUR : GROUND_COLOUR]
      }
      const last = line[line.length - 1]
      if (last !== undefined && last[1] === cell[1]) last[0] += cell[0]
      else line.push([cell[0], cell[1]])
    }
    const tail = line[line.length - 1]
    if (tail !== undefined && tail[1] === undefined) tail[0] = tail[0].trimEnd()
    lines.push(line.filter(([text]) => text !== ''))
  }
  return lines
}

// One drawing per width: the art only changes when the pane is resized.
const artCache = new Map<number, [string, string | undefined][][]>()
function sunsetAt(columns: number): [string, string | undefined][][] {
  const hit = artCache.get(columns)
  if (hit !== undefined) return hit
  const art = sunsetArt(columns)
  artCache.set(columns, art)
  return art
}

// cactus's own idle label: whole days from 48h up, else whole hours.
function idleLabel(hours: number): string {
  const whole = Math.floor(hours)
  return whole >= 48 ? `${Math.floor(whole / 24)}d` : `${whole}h`
}

async function pinTop($: EngineInterface, key: string): Promise<void> {
  await $.ui.scroll({ to: { key: `${key}:sel` }, block: 'nearest' }).catch(() => undefined)
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
  await pinTop($, to.key)
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
    const first = (await read($, selected)) ?? (await read($, rows))[0]?.key
    if (first !== undefined) await pinTop($, first)

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

  // Walking the ring onto any of a row's elements selects that row.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els = $.ui.resolve(e)
    const { Box, Text, Button } = els
    // The pane's inner width, redrawn on resize; the sunset is drawn to fit it.
    const width = Math.min(200, e.props.bodyColumns)
    const Input = 'Input' in els ? els.Input : undefined
    const list = await read($, rows)
    const picked = await read($, picks)
    const failed = await read($, error)
    const shown = await read($, previews)
    const wanted = await read($, selected)
    const stack = await read($, undo)
    const modeOf = await read($, modes)
    const flipped = await read($, flips)
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
          // The ring stays on the header, where enter sends.
          void toggle($, row.key, label, rec).then(() =>
            $.ui.focus({ requestId: PANE, key: `${row.key}:sel` }).catch(() => undefined),
          )
        } else if (isRunAct && label === 'approve') {
          void runRow($, row.key, true)
        } else {
          void answerRow($, row.key, ['-s', label])
        }
      }
      const choiceKey = (i: number) => (isConfirm && i < 2 ? (i === 0 ? 'y' : 'n') : String(i + 1))

      // The keys the hidden Buttons below carry, named once in the card.
      const legend = [
        hasInput ? 'i type' : null,
        row.act === 'notify' ? 'd dismiss' : 's skip',
        canRun ? 'r run' : null,
        isElaborate ? 'u withdraw' : `e ${isHinting ? 'cancel' : 'elaborate'} · b break up`,
        row.act === 'review' || isPlan ? 'x close' : 'c clear',
        canFlip ? `m ${isFlipped ? 'single' : 'multiple'}` : null,
        isMulti ? `g send ${mine.length}` : null,
        row.files.length > 0 ? 'f view · o preview' : null,
        stack.length > 0 && !isElaborate ? 'u undo' : null,
        list.length > 1 ? 'j/k move' : null,
      ]
        .filter(Boolean)
        .join(' · ')
      const body = (
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
                      <Text bold={isPicked}>
                        <Text color="cyan">{choiceKey(i)}:</Text> {isPicked ? '✓ ' : ''}
                        {c.label}
                      </Text>
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
                <Text key={`step${s.n}`}>
                  <Text color="cyan">{s.n <= 9 ? `${s.n}:` : '  '}</Text> [{s.done ? 'x' : ' '}] {s.text}
                </Text>
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
                    <Text dimColor>{j === 0 ? 'f/o ' : '    '}{f}</Text>
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

          <Box marginTop={1}>
            <Text dimColor wrap="wrap">{legend}</Text>
          </Box>
        </Box>
      )
      const input = hasInput ? (
        <Box key={`${row.key}:input`} flexDirection="column" marginTop={1}>
          {(drafted[row.key] ?? '') !== '' && (
            <Box key={`${row.key}:draft`}>
              <Text wrap="wrap" dimColor>{drafted[row.key]}</Text>
            </Box>
          )}
          {Input !== undefined && (
            <Input
              key={`${row.key}:text`}
              label={inputLabel}
              placeholder="i to type · enter sends · end a line with \ for another line"
              submitLabel="send"
              onSubmit={(value: string) => void submitLine($, row.key, value)}
            />
          )}
        </Box>
      ) : null
      // Probe (q555): every key Button sits in a display:none Box, so nothing
      // draws, and the question is whether its hotkey still presses it.
      const controls = (
        <Box key={`${row.key}:controls`} display="none" flexDirection="column">
          {row.choices.length > 0 && (
            <Box flexDirection="row" flexWrap="wrap" columnGap={2}>
              {row.choices.slice(0, 9).map((c, i) => (
                <Button
                  key={`${row.key}:${c.label}`}
                  label={c.label.length > 14 ? `${c.label.slice(0, 13)}…` : c.label}
                  hotkey={choiceKey(i)}
                  plain
                  onPress={press => pick(c.label, press.surface)}
                />
              ))}
            </Box>
          )}
          {isPlan && row.steps.length > 0 && (
            <Box flexDirection="row" flexWrap="wrap" columnGap={2}>
              {row.steps.filter(s => s.n <= 9).map(s => (
                <Button
                  key={`${row.key}:step${s.n}`}
                  label={s.done ? 'undo step' : 'step'}
                  hotkey={String(s.n)}
                  plain
                  onPress={() =>
                    void cactus($, row.key, ['plan', row.key, s.done ? '--undone' : '--done', String(s.n)])
                  }
                />
              ))}
            </Box>
          )}
          <Box flexDirection="row" flexWrap="wrap" columnGap={2}>
            {hasInput && (
              <Button
                key={`${row.key}:type`}
                label="type"
                hotkey="i"
                plain
                onPress={() =>
                  void $.ui
                    .focus({ requestId: PANE, key: `${row.key}:text` })
                    .catch(() => undefined)
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
                    if (!isHinting) void $.ui.focus({ requestId: PANE, key: `${row.key}:text` }).catch(() => undefined)
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
                label={`send ${mine.length} picked`}
                hotkey="g"
                plain
                onPress={() =>
                  mine.length === 0
                    ? $.ui.toast(`cactus ${row.key}: nothing picked`)
                    : void answerRow($, row.key, mine.flatMap(l => ['-s', l]))
                }
              />
            )}
          </Box>
          {row.files.length > 0 && (
            <Box flexDirection="row" columnGap={2}>
              <Button key={`${row.key}:open0`} label="view file" hotkey="f" plain onPress={() => void $.process.run(['open', row.files[0] ?? ''])} />
              <Button
                key={`${row.key}:prev0`}
                label={(row.files[0] ?? '') in shown ? 'hide preview' : 'preview'}
                hotkey="o"
                plain
                onPress={() => void togglePreview($, row.files[0] ?? '')}
              />
            </Box>
          )}
        </Box>
      )
      return { body, controls, input, legend }
    }

    const at = Math.max(0, list.findIndex(r => r === current))
    const above = Math.max(0, Math.min(at - (LIST_WINDOW >> 1), list.length - LIST_WINDOW))

    return (
      <Box flexDirection="column">
        {failed !== null && <Text color="red">{failed}</Text>}
        {list.length === 0 && (
          <Box key="empty" flexDirection="column">
            {width >= ART_MIN_COLUMNS && (
              <Box key="sunset" flexDirection="column" marginBottom={1}>
              {sunsetAt(width).map((line, i) => (
                <Box key={`sunset:${i}`}>
                  <Text>
                    {line.map(([part, color], j) => (
                      <Text key={String(j)} color={color}>{part}</Text>
                    ))}
                  </Text>
                </Box>
              ))}
              </Box>
            )}
            <Text bold>Cactus inbox empty.</Text>
            <Text dimColor>Decisions incoming...</Text>
          </Box>
        )}
        {above > 0 && <Text dimColor>  ↑ {above} more (k)</Text>}
        {list.slice(above, above + LIST_WINDOW).map(row => {
          const isCurrent = row === current
          return (
            <Box key={row.key} flexDirection="column">
              <Box flexDirection="row" columnGap={2}>
                <Button
                  key={`${row.key}:sel`}
                  label={`${isCurrent ? '▸' : ' '} ${row.key}`}
                  plain
                  onPress={() => {
                    if (!isCurrent) return void select($, row.key).then(() => pinTop($, row.key))
                    void enterOnOpen($, row)
                  }}
                />
                {/* Sent back for a rewrite (elaborate or break up): the agent owes
                    the next move, so the act reads wait.. until it answers. */}
                <Box key={`${row.key}:act`}>
                  {row.status === 'elaborate' ? (
                    <Text color="yellow">{'wait..'.padEnd(6)}</Text>
                  ) : (
                    <Text color={ACT_COLOUR[row.act] ?? 'white'}>{row.act.padEnd(6)}</Text>
                  )}
                </Box>
                {row.stale === true && (
                  <Box key={`${row.key}:stale`}>
                    <Text dimColor>stale {idleLabel(row.idle_hours ?? 0)}</Text>
                  </Box>
                )}
                <Text wrap="truncate-end" dimColor={!isCurrent || row.stale === true} bold={isCurrent}>
                  {row.word ? `${row.word}  ` : ''}
                  {firstLine(row.text)}
                </Text>
              </Box>
            </Box>
          )
        })}
        {list.length - above - LIST_WINDOW > 0 && (
          <Text dimColor>  ↓ {list.length - above - LIST_WINDOW} more (j)</Text>
        )}
        {/* The list on top, the open question's card under it: arrows walk the
            headers, and the focus hook keeps them out of the card and keys. */}
        {current !== undefined && card(current).body}
        {current !== undefined && card(current).input}
        {current !== undefined && card(current).controls}
        <Box display="none" flexDirection="row" columnGap={2}>
          {stack.length > 0 && (
            <Button
              key="undo"
              label={`undo ${stack[stack.length - 1]}`}
              hotkey={current?.status === 'elaborate' ? undefined : 'u'}
              plain
              onPress={() => void undoLast($)}
            />
          )}
          {list.length > 1 && <Button key="prev" label="up" hotkey="k" plain onPress={() => void step($, -1)} />}
          {list.length > 1 && <Button key="next" label="down" hotkey="j" plain onPress={() => void step($, 1)} />}
        </Box>
      </Box>
    )
  })

  // Arrows and tab are the person's focus steps. Only question headers may
  // take them; the keys below the list stay reachable by hotkey (and `i` puts
  // the ring in the input), so a step onto them is refused and the ring stays.
  on('ui.focus', async ($, e, next) => {
    if (e.requestId !== PANE || e.origin.kind !== 'person') return next(e)
    if (e.element !== undefined && !e.element.endsWith(':sel')) return { deny: 'cactus-pane: headers only' }
    return next(e)
  })
}
