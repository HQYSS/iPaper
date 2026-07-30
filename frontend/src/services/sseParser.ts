export function parseSseLines<T>(raw: string): T[] {
  const events: T[] = []

  for (const rawLine of raw.split('\n')) {
    const line = rawLine.trim()
    if (!line.startsWith('data: ')) continue

    try {
      events.push(JSON.parse(line.slice(6)) as T)
    } catch {
      // Ignore malformed event lines without interrupting the stream.
    }
  }

  return events
}

export async function* parseSseStream<T>(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<T> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const event of parseSseLines<T>(lines.join('\n'))) {
      yield event
    }
  }

  buffer += decoder.decode()
  for (const event of parseSseLines<T>(buffer)) {
    yield event
  }
}
