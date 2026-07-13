import { useEffect, useRef, useState } from 'react'
import { RetellWebClient } from 'retell-client-js-sdk'
import type {
  AddedLuggageItem,
  BookingContext,
  ChatMessage,
  ChatResponse,
  EscalationInfo,
  LuggageOption,
  PendingConfirmation,
  ToolResult,
} from '../types'
import { CloseIcon, MicIcon, SendIcon, SuitcaseIcon } from './icons'
import './ConciergeWidget.css'

const CHAT_ENDPOINT = '/api/chat'
// `||` (not `??`) deliberately — an empty string from an unfilled .env
// entry should also fall back to the local default, not become "".
const VOICE_API_BASE = import.meta.env.VITE_VOICE_API_BASE || 'http://127.0.0.1:8002'

type Mode = 'chat' | 'voice'
type CallState = 'idle' | 'connecting' | 'active' | 'ended' | 'error'

interface TranscriptLine {
  role: string
  content: string
}

function uid() {
  return Math.random().toString(36).slice(2)
}

function formatMoney(amount: number, currency: string) {
  const symbol = currency === 'GBP' ? '£' : currency + ' '
  return `${symbol}${amount}`
}

// -----------------------------------------------------------------------
// Shared reducer: both chat mode (from /api/chat's tool_results) and voice
// mode (from the /functions/stream SSE feed) funnel through this, so a
// luggage-option card or a booking context strip is backed by the exact
// same real tool.py return dict regardless of which channel produced it.
// -----------------------------------------------------------------------
interface ConciergeState {
  booking: BookingContext | null
  luggageOptions: LuggageOption[]
  pendingConfirmation: PendingConfirmation | null
  addedItems: AddedLuggageItem[]
  escalation: EscalationInfo | null
}

function applyToolResult(state: ConciergeState, tr: ToolResult): ConciergeState {
  const r = tr.result as any
  switch (tr.name) {
    case 'get_booking_details':
      if (!r.found) return state
      return {
        ...state,
        booking: {
          bookingReference: r.bookingReference,
          found: true,
          customerName: r.customerName,
          airline: r.airline,
          destination: r.destination,
          departureDate: r.departureDate,
          canAddLuggage: r.canAddLuggage,
          luggagePolicy: r.luggagePolicy,
          passengers: r.passengers ?? [],
        },
        escalation: null,
      }
    case 'get_luggage_options':
      return { ...state, luggageOptions: r.options ?? [], pendingConfirmation: null }
    case 'add_luggage':
      if (r.needs_confirmation && r.option_id && r.error !== 'not_yet_confirmed') {
        return {
          ...state,
          pendingConfirmation: {
            option_id: r.option_id,
            name: r.name,
            price: r.price,
            currency: r.currency,
            passenger_ref_ids: r.passenger_ref_ids ?? [],
          },
        }
      }
      if (r.success) {
        return {
          ...state,
          pendingConfirmation: null,
          addedItems: [...state.addedItems, ...(r.addedItems ?? [])],
          // Drop the option that was just added — otherwise it keeps showing
          // as "still available" even though it's now on the booking.
          luggageOptions: state.luggageOptions.filter((o) => o.option_id !== r.option_id),
        }
      }
      if (r.remaining_options) {
        return { ...state, luggageOptions: r.remaining_options, pendingConfirmation: null }
      }
      return state
    case 'escalate_to_human':
      return {
        ...state,
        escalation: { escalated: true, already_escalated: r.already_escalated, reason: r.reason },
      }
    default:
      return state
  }
}

function passengerName(booking: BookingContext | null, refId: string): string {
  const p = booking?.passengers.find((p) => p.passengerId === refId)
  return p ? p.firstName : refId
}

// -----------------------------------------------------------------------

export default function ConciergeWidget() {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('chat')
  const [showHint, setShowHint] = useState(false)

  // Chat
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [chatStarted, setChatStarted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sessionId = useRef<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Voice
  const [callState, setCallState] = useState<CallState>('idle')
  const [agentTalking, setAgentTalking] = useState(false)
  const [muted, setMuted] = useState(false)
  const [transcript, setTranscript] = useState<TranscriptLine[]>([])
  const [volume, setVolume] = useState(0)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const clientRef = useRef<RetellWebClient | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const volumeFrameRef = useRef<number | null>(null)

  // Shared concierge state (booking, luggage, confirmation, success, escalation)
  const [state, setState] = useState<ConciergeState>({
    booking: null,
    luggageOptions: [],
    pendingConfirmation: null,
    addedItems: [],
    escalation: null,
  })

  const applyResults = (results: ToolResult[] | undefined) => {
    if (!results?.length) return
    setState((prev) => results.reduce(applyToolResult, prev))
  }

  // Idle-scroll hint on the collapsed dock, per the concierge-dock spec —
  // only once the visitor has actually scrolled the page (not just opened
  // it) and stayed idle a moment, and only while the panel is still closed.
  useEffect(() => {
    if (open) {
      setShowHint(false)
      return
    }
    let scrolled = false
    let timer: number | null = null
    const onScroll = () => {
      if (scrolled) return
      scrolled = true
      timer = window.setTimeout(() => setShowHint(true), 3000)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (timer) window.clearTimeout(timer)
    }
  }, [open])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  // ---- Chat ----

  async function sendMessage(text: string): Promise<ChatResponse> {
    const res = await fetch(CHAT_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId.current ?? undefined }),
    })
    if (!res.ok) throw new Error(`Chat request failed (${res.status})`)
    return res.json()
  }

  function startChatIfNeeded() {
    if (chatStarted) return
    setChatStarted(true)
    setLoading(true)
    sendMessage('Hi')
      .then((res) => {
        sessionId.current = res.session_id
        setMessages([{ id: uid(), role: 'assistant', text: res.reply }])
        applyResults(res.tool_results)
      })
      .catch(() => setError('Sorry, I could not connect. Please make sure the chat service is running.'))
      .finally(() => setLoading(false))
  }

  async function handleSend(overrideText?: string) {
    const text = (overrideText ?? input).trim()
    if (!text || loading) return

    setMessages((prev) => [...prev, { id: uid(), role: 'user', text }])
    if (!overrideText) setInput('')
    setLoading(true)
    setError(null)

    try {
      const res = await sendMessage(text)
      sessionId.current = res.session_id
      setMessages((prev) => [...prev, { id: uid(), role: 'assistant', text: res.reply }])
      applyResults(res.tool_results)
    } catch {
      setError('Sorry, something went wrong sending that. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  function handleAddOption(option: LuggageOption) {
    const names = option.passenger_ref_ids.map((id) => passengerName(state.booking, id)).join(' and ')
    handleSend(`Add the ${option.name} for ${names}`)
  }

  function handleConfirm() {
    handleSend('Yes, go ahead')
  }

  function handleCancelPending() {
    setState((prev) => ({ ...prev, pendingConfirmation: null }))
    handleSend("No, don't add that")
  }

  // ---- Voice ----

  useEffect(() => {
    const client = new RetellWebClient()
    clientRef.current = client

    client.on('call_started', () => setCallState('active'))
    client.on('call_ended', () => {
      setCallState('ended')
      eventSourceRef.current?.close()
    })
    client.on('agent_start_talking', () => setAgentTalking(true))
    client.on('agent_stop_talking', () => setAgentTalking(false))
    client.on('update', (update: { transcript?: TranscriptLine[] }) => {
      if (update.transcript) setTranscript(update.transcript)
    })
    client.on('error', (err: unknown) => {
      console.error('Retell call error', err)
      setVoiceError('The call ran into a problem and had to stop.')
      setCallState('error')
      client.stopCall()
    })

    return () => {
      client.stopCall()
      eventSourceRef.current?.close()
      if (volumeFrameRef.current) cancelAnimationFrame(volumeFrameRef.current)
    }
  }, [])

  // Polls the SDK's real AnalyserNode-backed volume reading while a call is
  // live, so the orb's motion reflects actual audio amplitude instead of a
  // canned CSS loop.
  useEffect(() => {
    if (callState !== 'active') {
      setVolume(0)
      return
    }
    const tick = () => {
      const v = clientRef.current?.analyzerComponent?.calculateVolume?.() ?? 0
      setVolume(v)
      volumeFrameRef.current = requestAnimationFrame(tick)
    }
    volumeFrameRef.current = requestAnimationFrame(tick)
    return () => {
      if (volumeFrameRef.current) cancelAnimationFrame(volumeFrameRef.current)
    }
  }, [callState])

  async function startCall() {
    setVoiceError(null)
    setTranscript([])
    setCallState('connecting')
    try {
      const res = await fetch(`${VOICE_API_BASE}/create-web-call`, { method: 'POST' })
      if (!res.ok) throw new Error(`create-web-call failed (${res.status})`)
      const { access_token, call_id } = await res.json()

      // Real tool-call results for this call, streamed from the backend —
      // see voiceagent/main.py's /functions/stream/{call_id}. Retell's own
      // client SDK never exposes these, only the spoken transcript.
      const es = new EventSource(`${VOICE_API_BASE}/functions/stream/${call_id}`)
      es.onmessage = (ev) => {
        try {
          const parsed = JSON.parse(ev.data) as ToolResult
          applyResults([parsed])
        } catch {
          // ignore malformed/keepalive frames
        }
      }
      eventSourceRef.current = es

      await clientRef.current?.startCall({ accessToken: access_token })
    } catch {
      setVoiceError('Could not start the call. Please make sure the voice service is running.')
      setCallState('error')
    }
  }

  function endCall() {
    clientRef.current?.stopCall()
    eventSourceRef.current?.close()
    setCallState('ended')
  }

  function toggleMute() {
    if (!clientRef.current) return
    if (muted) clientRef.current.unmute()
    else clientRef.current.mute()
    setMuted((m) => !m)
  }

  const isCallLive = callState === 'active' || callState === 'connecting'

  function switchMode(next: Mode) {
    setMode(next)
    if (next === 'chat') startChatIfNeeded()
  }

  function openPanel(initialMode: Mode) {
    setOpen(true)
    setMode(initialMode)
    if (initialMode === 'chat') startChatIfNeeded()
  }

  const hasConciergeContent =
    state.luggageOptions.length > 0 ||
    state.pendingConfirmation ||
    state.addedItems.length > 0 ||
    state.escalation

  return (
    <div className="concierge">
      {/* Signature moment: page dims slightly while a voice call is live */}
      {open && mode === 'voice' && isCallLive && <div className="concierge-dim" />}

      {open && (
        <div className="concierge-panel" role="dialog" aria-label="loveholidays concierge">
          <header className="concierge-header">
            <div className="concierge-header-top">
              <div className="concierge-identity">
                <span className="concierge-avatar">
                  <SuitcaseIcon size={18} />
                </span>
                <div>
                  <div className="concierge-name">Sunny</div>
                  <div className="concierge-status">
                    <span className="status-dot" /> Online · replies instantly
                  </div>
                </div>
              </div>
              <button className="concierge-close" onClick={() => setOpen(false)} aria-label="Close concierge">
                <CloseIcon size={16} />
              </button>
            </div>

            <div className="concierge-controls">
              <div className="mode-toggle" role="tablist" aria-label="Concierge mode">
                <button
                  role="tab"
                  aria-selected={mode === 'chat'}
                  className={mode === 'chat' ? 'mode-btn active' : 'mode-btn'}
                  onClick={() => switchMode('chat')}
                >
                  Chat
                </button>
                <button
                  role="tab"
                  aria-selected={mode === 'voice'}
                  className={mode === 'voice' ? 'mode-btn active' : 'mode-btn'}
                  onClick={() => switchMode('voice')}
                >
                  Voice
                </button>
                <span className={mode === 'voice' ? 'mode-thumb thumb-voice' : 'mode-thumb thumb-chat'} />
              </div>
            </div>
          </header>

          {state.booking && (
            <div className="booking-strip">
              <div className="booking-strip-ref">{state.booking.bookingReference}</div>
              <div className="booking-strip-row">
                {state.booking.destination && <span>✈ {state.booking.destination}</span>}
                {state.booking.departureDate && <span>{state.booking.departureDate}</span>}
              </div>
              <div className="booking-strip-row muted">
                {state.booking.passengers.length} passenger{state.booking.passengers.length === 1 ? '' : 's'}
                {' · '}
                {state.booking.passengers.map((p) => p.firstName).join(', ')}
              </div>
              {state.addedItems.length > 0 && (
                <div className="booking-strip-row luggage-summary">
                  🧳 {state.addedItems.map((i) => i.name).join(', ')}
                </div>
              )}
            </div>
          )}

          <div className="concierge-body">
            {mode === 'chat' ? (
              <div className="chat-view">
                <div className="chat-stream" ref={scrollRef}>
                  {messages.map((m) => (
                    <div key={m.id} className={`concierge-row ${m.role}`}>
                      <div className={`concierge-bubble ${m.role}`}>{m.text}</div>
                    </div>
                  ))}
                  {loading && (
                    <div className="concierge-row assistant">
                      <div className="concierge-bubble assistant typing">
                        <span className="dot" />
                        <span className="dot" />
                        <span className="dot" />
                      </div>
                    </div>
                  )}
                  {hasConciergeContent && (
                    <ConciergeContent
                      state={state}
                      onAdd={handleAddOption}
                      onConfirm={handleConfirm}
                      onCancel={handleCancelPending}
                    />
                  )}
                  {error && <div className="concierge-error">{error}</div>}
                </div>
                <div className="composer">
                  <input
                    className="composer-input"
                    type="text"
                    placeholder="Type your message..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                    disabled={loading}
                  />
                  <button
                    className="composer-mic"
                    onClick={() => openPanel('voice')}
                    aria-label="Switch to voice"
                    title="Switch to voice"
                  >
                    <MicIcon size={16} />
                  </button>
                  <button
                    className="composer-send"
                    onClick={() => handleSend()}
                    disabled={loading || !input.trim()}
                    aria-label="Send message"
                  >
                    <SendIcon size={16} />
                  </button>
                </div>
              </div>
            ) : (
              <div className="voice-view">
                <div
                  className={`orb ${isCallLive ? 'live' : ''} ${agentTalking ? 'talking' : ''}`}
                  style={{ '--vol': volume } as React.CSSProperties}
                >
                  <div className="orb-ring" />
                  <div className="orb-core">
                    <MicIcon size={30} />
                  </div>
                </div>

                <div className="orb-caption">
                  {callState === 'idle' && 'Tap below to start a call'}
                  {callState === 'connecting' && 'Connecting…'}
                  {callState === 'active' && (agentTalking ? 'Sunny is speaking…' : 'Listening…')}
                  {callState === 'ended' && 'Call ended'}
                  {callState === 'error' && 'Something went wrong'}
                </div>

                {voiceError && <div className="concierge-error">{voiceError}</div>}

                <div className="voice-transcript">
                  {transcript.map((line, i) => (
                    <div key={i} className={`transcript-line ${line.role === 'agent' ? 'agent' : 'user'}`}>
                      <span className="transcript-role">{line.role === 'agent' ? 'Sunny' : 'You'}:</span>{' '}
                      {line.content}
                    </div>
                  ))}
                </div>

                {hasConciergeContent && (
                  <ConciergeContent
                    state={state}
                    onAdd={() => {}}
                    onConfirm={() => {}}
                    onCancel={() => {}}
                    readOnly
                  />
                )}

                <div className="voice-controls">
                  {!isCallLive ? (
                    <button className="voice-call-btn start" onClick={startCall}>
                      {callState === 'ended' || callState === 'error' ? 'Call again' : 'Start call'}
                    </button>
                  ) : (
                    <>
                      <button className="voice-mute-btn" onClick={toggleMute} disabled={callState !== 'active'}>
                        {muted ? 'Unmute' : 'Mute'}
                      </button>
                      <button className="voice-call-btn end" onClick={endCall}>
                        End call
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>

          <footer className="concierge-footer">
            <span className="trust-badge">ATOL protected</span>
            <span className="trust-sep">·</span>
            <span>Secure — your booking data stays private</span>
          </footer>
        </div>
      )}

      <div className="concierge-dock">
        {showHint && <div className="dock-hint">Need a hand with your booking?</div>}
        <div className="dock-pill">
          <span className="dock-icon">
            <SuitcaseIcon size={20} />
          </span>
          <button className="dock-chip" onClick={() => openPanel('chat')}>
            Chat
          </button>
          <span className="dock-divider" />
          <button className="dock-chip" onClick={() => openPanel('voice')}>
            Talk
          </button>
        </div>
      </div>
    </div>
  )
}

// -----------------------------------------------------------------------
// Renders whatever the current tool state actually contains — luggage
// cards, a pending-confirmation card, a success (boarding-pass) card, or
// an escalation notice. Shared between chat and voice mode so the same
// real data renders identically in both.
// -----------------------------------------------------------------------
function ConciergeContent({
  state,
  onAdd,
  onConfirm,
  onCancel,
  readOnly,
}: {
  state: ConciergeState
  onAdd: (option: LuggageOption) => void
  onConfirm: () => void
  onCancel: () => void
  readOnly?: boolean
}) {
  return (
    <div className="concierge-content">
      {state.escalation && (
        <div className="escalation-banner">
          👤 {state.escalation.already_escalated ? 'A human agent is already on this' : "You're being connected to a human agent"}
        </div>
      )}

      {state.pendingConfirmation && (
        <div className="confirm-card">
          <div className="confirm-card-title">Confirm luggage</div>
          <div className="confirm-card-item">
            {state.pendingConfirmation.name} for {passengerName(state.booking, state.pendingConfirmation.passenger_ref_ids[0])}
          </div>
          <div className="confirm-card-price">
            {formatMoney(state.pendingConfirmation.price, state.pendingConfirmation.currency)}
          </div>
          {!readOnly && (
            <div className="confirm-card-actions">
              <button className="confirm-btn go" onClick={onConfirm}>
                Add it
              </button>
              <button className="confirm-btn cancel" onClick={onCancel}>
                Not now
              </button>
            </div>
          )}
        </div>
      )}

      {!state.pendingConfirmation && state.luggageOptions.length > 0 && (
        <div className="option-grid">
          {state.luggageOptions.map((opt) => (
            <div className="option-card" key={opt.option_id}>
              <div className="option-card-name">{opt.name}</div>
              <div className="option-card-passenger">for {passengerName(state.booking, opt.passenger_ref_ids[0])}</div>
              <div className="option-card-price">{formatMoney(opt.price, opt.currency)}</div>
              {!readOnly && (
                <button className="option-card-add" onClick={() => onAdd(opt)}>
                  Add
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {state.addedItems.length > 0 && (
        <div className="boarding-pass">
          <div className="boarding-pass-front">
            <div className="boarding-pass-title">Added to your booking</div>
            {state.addedItems.map((item, i) => (
              <div className="boarding-pass-item" key={i}>
                <span>{item.name}</span>
                <span>{formatMoney(item.totalPrice, item.currency)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
