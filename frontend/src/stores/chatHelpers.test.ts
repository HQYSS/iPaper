import { describe, expect, it } from 'vitest'
import type { ChatMessage, ForkData } from '../services/api'
import {
  forkEditedMessage,
  sanitizeLoadedMessages,
  switchMessageFork,
} from './chatHelpers'

describe('sanitizeLoadedMessages', () => {
  it('removes an empty completed assistant placeholder', () => {
    const input: ChatMessage[] = [
      { role: 'user', content: 'question' },
      { role: 'assistant', content: '' },
    ]

    expect(sanitizeLoadedMessages(input)).toEqual({
      messages: [{ role: 'user', content: 'question', quotes: undefined }],
      removedTrailingEmptyAssistant: true,
    })
    expect(input).toHaveLength(2)
  })

  it('retains an empty truncated assistant while generation is pending', () => {
    const input: ChatMessage[] = [
      { role: 'user', content: 'question' },
      { role: 'assistant', content: '', truncated: true },
    ]

    const result = sanitizeLoadedMessages(input)
    expect(result.messages).toHaveLength(2)
    expect(result.messages[1]).toMatchObject({ role: 'assistant', truncated: true })
    expect(result.removedTrailingEmptyAssistant).toBe(false)
  })
})

describe('chat forks', () => {
  it('creates a fork and switches while preserving the current branch', () => {
    const original: ChatMessage[] = [
      { role: 'assistant', content: 'intro' },
      { role: 'user', content: 'old question' },
      { role: 'assistant', content: 'old answer' },
    ]
    const forked = forkEditedMessage(original, {}, 1, 'new question')
    expect(forked).not.toBeNull()

    const activeMessages: ChatMessage[] = [
      { role: 'assistant', content: 'intro' },
      { role: 'user', content: 'new question' },
      { role: 'assistant', content: 'new answer' },
    ]
    const switched = switchMessageFork(
      activeMessages,
      forked!.forks as Record<string, ForkData>,
      1,
      0,
    )

    expect(switched?.messages).toEqual(original)
    expect(switched?.forks['1'].alternatives[1]).toEqual(activeMessages.slice(1))
  })
})
