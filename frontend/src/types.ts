export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

// Raw result of one tool call this turn — shape depends on `name`, mirrors
// backend/chatagent/tool.py's (and voiceagent/luggage_api.py's) return
// dicts exactly, since that's literally where this comes from.
export interface ToolResult {
  name: 'get_booking_details' | 'get_luggage_options' | 'add_luggage' | 'escalate_to_human'
  result: Record<string, unknown>
}

export interface ChatResponse {
  session_id: string
  reply: string
  tool_results?: ToolResult[]
}

export interface Passenger {
  passengerId: string
  firstName: string
  surname: string
  passengerType: string
}

// From get_booking_details's result — only the fields the UI actually
// reads; the real payload has more (flights, flightSegments, etc).
export interface BookingContext {
  bookingReference: string
  found?: boolean
  customerName?: string
  airline?: string
  destination?: string
  departureDate?: string
  canAddLuggage?: boolean
  luggagePolicy?: string
  passengers: Passenger[]
}

// From get_luggage_options's flattened `options` list.
export interface LuggageOption {
  option_id: string
  name: string
  price: number
  currency: string
  passenger_ref_ids: string[]
}

// From add_luggage when needs_confirmation is true.
export interface PendingConfirmation {
  option_id: string
  name: string
  price: number
  currency: string
  passenger_ref_ids: string[]
}

// From add_luggage's success payload (addedItems[]).
export interface AddedLuggageItem {
  name: string
  passengerRefIds: string[]
  totalPrice: number
  currency: string
  confirmationCode?: string
}

// From escalate_to_human's result.
export interface EscalationInfo {
  escalated: boolean
  already_escalated?: boolean
  reason?: string
}
