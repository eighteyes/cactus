// editor: a multi-line text editor drawn inside the cactus pane (terminal only).
// - keeps the draft and cursor as the instance's local state
// - return inserts a newline; ctrl+s posts { submit } to the hooks module
// - arrows, home/end, backspace/delete edit; esc hands the keys back (engine)
// - a new `reset` prop from the hooks module clears the draft after a send

import type { ClientKeyEvent, ClientModule, ClientSurface } from 'claude-code'

type Props = { label: string; placeholder: string; reset: number; rows: number }
type State = { text: string; cursor: number; reset: number }

function lineStart(text: string, at: number): number {
  return text.lastIndexOf('\n', at - 1) + 1
}

function lineEnd(text: string, at: number): number {
  const end = text.indexOf('\n', at)
  return end === -1 ? text.length : end
}

// Move up or down one line, keeping the column where the line is long enough.
function verticalMove(text: string, at: number, dir: -1 | 1): number {
  const start = lineStart(text, at)
  const column = at - start
  if (dir === -1) {
    if (start === 0) return 0
    const prevStart = lineStart(text, start - 1)
    return Math.min(prevStart + column, start - 1)
  }
  const end = lineEnd(text, at)
  if (end === text.length) return text.length
  return Math.min(end + 1 + column, lineEnd(text, end + 1))
}

function edit(st: State, k: ClientKeyEvent): State | 'submit' {
  const { text, cursor } = st
  if (k.ctrl && k.key === 's') return 'submit'
  if (k.ctrl || k.meta) return st
  const put = (s: string) => ({ ...st, text: text.slice(0, cursor) + s + text.slice(cursor), cursor: cursor + s.length })
  switch (k.key) {
    case 'return':
      return put('\n')
    case 'backspace':
      return cursor === 0 ? st : { ...st, text: text.slice(0, cursor - 1) + text.slice(cursor), cursor: cursor - 1 }
    case 'delete':
      return { ...st, text: text.slice(0, cursor) + text.slice(cursor + 1) }
    case 'left':
      return { ...st, cursor: Math.max(0, cursor - 1) }
    case 'right':
      return { ...st, cursor: Math.min(text.length, cursor + 1) }
    case 'up':
      return { ...st, cursor: verticalMove(text, cursor, -1) }
    case 'down':
      return { ...st, cursor: verticalMove(text, cursor, 1) }
    case 'home':
      return { ...st, cursor: lineStart(text, cursor) }
    case 'end':
      return { ...st, cursor: lineEnd(text, cursor) }
    case 'tab':
      return put('  ')
    default:
      return k.key.length === 1 ? put(k.key) : st
  }
}

const Editor: ClientModule<Props, State> = (props, surface: ClientSurface<State>) => {
  const { Box, Text } = surface.elements
  const current = (): State => {
    const st = surface.state
    return st === undefined || st.reset !== props.reset ? { text: '', cursor: 0, reset: props.reset } : st
  }
  surface.onKey(k => {
    const next = edit(current(), k)
    if (next === 'submit') {
      surface.post({ submit: current().text })
      return
    }
    surface.setState(next)
  })

  const { text, cursor } = current()
  const lines = text.split('\n')
  let offset = 0
  const drawn = lines.map((line, i) => {
    const from = offset
    offset += line.length + 1
    const here = cursor >= from && cursor <= from + line.length
    if (!here) return Text({ children: line === '' ? ' ' : line })
    const at = cursor - from
    return Text({
      children: [
        line.slice(0, at),
        Text({ inverse: true, children: line[at] ?? ' ' }),
        line.slice(at + 1),
      ],
    })
  })
  while (drawn.length < props.rows) drawn.push(Text({ children: ' ' }))

  return Box({
    flexDirection: 'column',
    borderStyle: 'single',
    paddingX: 1,
    children: [
      Text({ dimColor: true, children: text === '' ? `${props.label}: ${props.placeholder}` : props.label }),
      ...drawn,
    ],
  })
}

export default Editor
