import { describe, expect, it } from 'vitest'
import { parseSseStream } from './sseParser'

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

async function collect<T>(stream: ReadableStream<Uint8Array>): Promise<T[]> {
  const events: T[] = []
  for await (const event of parseSseStream<T>(stream)) events.push(event)
  return events
}

describe('parseSseStream', () => {
  it('reassembles an event split across chunks', async () => {
    const events = await collect<{ type: string; content: string }>(
      streamFromChunks(['data: {"type":"chunk","con', 'tent":"你好"}\n']),
    )

    expect(events).toEqual([{ type: 'chunk', content: '你好' }])
  })

  it('skips malformed and non-data lines', async () => {
    const events = await collect<{ type: string }>(
      streamFromChunks([
        'event: message\n',
        'data: not-json\n',
        'data: {"type":"done"}\n',
      ]),
    )

    expect(events).toEqual([{ type: 'done' }])
  })

  it('flushes the final event without a trailing newline', async () => {
    const events = await collect<{ type: string }>(
      streamFromChunks(['data: {"type":"stopped"}']),
    )

    expect(events).toEqual([{ type: 'stopped' }])
  })
})
