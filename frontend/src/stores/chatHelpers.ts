import type { ChatMessage, ForkData } from '../services/api'

export function cloneChatMessage(message: ChatMessage): ChatMessage {
  return {
    ...message,
    quotes: message.quotes?.map((quote) => ({ ...quote })),
  }
}

export function cloneChatMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map(cloneChatMessage)
}

export function sanitizeLoadedMessages(messages: ChatMessage[]): {
  messages: ChatMessage[]
  removedTrailingEmptyAssistant: boolean
} {
  const sanitizedMessages = cloneChatMessages(messages)
  const lastMessage = sanitizedMessages[sanitizedMessages.length - 1]

  // An empty truncated assistant means generation is still pending, so retain it.
  if (lastMessage?.role === 'assistant' && !lastMessage.content && !lastMessage.truncated) {
    sanitizedMessages.pop()
  }

  return {
    messages: sanitizedMessages,
    removedTrailingEmptyAssistant: sanitizedMessages.length !== messages.length,
  }
}

export function forkEditedMessage(
  messages: ChatMessage[],
  forks: Record<string, ForkData>,
  messageIndex: number,
  newContent: string,
): { messages: ChatMessage[]; forks: Record<string, ForkData> } | null {
  if (messages[messageIndex]?.role !== 'user') return null

  const tailFromIndex = messages.slice(messageIndex)
  const key = String(messageIndex)
  const currentFork = forks[key]
  const nextForks = { ...forks }

  if (currentFork) {
    const alternatives = [...currentFork.alternatives]
    alternatives[currentFork.active] = tailFromIndex
    alternatives.push([{ role: 'user', content: newContent }])
    nextForks[key] = {
      alternatives,
      active: alternatives.length - 1,
    }
  } else {
    nextForks[key] = {
      alternatives: [tailFromIndex, [{ role: 'user', content: newContent }]],
      active: 1,
    }
  }

  return {
    messages: messages.slice(0, messageIndex),
    forks: nextForks,
  }
}

export function switchMessageFork(
  messages: ChatMessage[],
  forks: Record<string, ForkData>,
  messageIndex: number,
  forkIndex: number,
): { messages: ChatMessage[]; forks: Record<string, ForkData> } | null {
  const key = String(messageIndex)
  const fork = forks[key]
  if (!fork || forkIndex < 0 || forkIndex >= fork.alternatives.length) return null

  const alternatives = [...fork.alternatives]
  alternatives[fork.active] = messages.slice(messageIndex)
  const nextForks = {
    ...forks,
    [key]: {
      alternatives,
      active: forkIndex,
    },
  }

  return {
    messages: [...messages.slice(0, messageIndex), ...alternatives[forkIndex]],
    forks: nextForks,
  }
}
