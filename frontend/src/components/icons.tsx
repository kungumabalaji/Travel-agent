type IconProps = { size?: number }

export function ChatIcon({ size = 24 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8A2.5 2.5 0 0 1 17.5 16H10l-4.4 3.3c-.6.45-1.5.02-1.5-.73V16h-.1A2.5 2.5 0 0 1 4 13.5v-8Z"
        fill="currentColor"
      />
      <circle cx="8.5" cy="9.5" r="1.15" fill="var(--icon-contrast, white)" />
      <circle cx="12" cy="9.5" r="1.15" fill="var(--icon-contrast, white)" />
      <circle cx="15.5" cy="9.5" r="1.15" fill="var(--icon-contrast, white)" />
    </svg>
  )
}

export function CloseIcon({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M5 5l14 14M19 5L5 19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function SendIcon({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M3.4 11.3 20 4l-6.3 16.6c-.2.5-.9.6-1.2.1l-2.9-5-5-2.9c-.5-.3-.4-1 .1-1.2l-1.3-.3Z"
        fill="currentColor"
      />
      <path d="M9.8 14.2 20 4" stroke="var(--icon-contrast, white)" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

export function MicIcon({ size = 32 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* small cap + main body, separated by a hairline gap for a soft
          "seam" detail — pure geometry, so it reads correctly on any
          background color without needing a separate contrast fill */}
      <rect x="9.3" y="2.6" width="5.4" height="2.7" rx="1.35" fill="currentColor" />
      <rect x="9.3" y="6.3" width="5.4" height="8.3" rx="2.7" fill="currentColor" />
      <path
        d="M6 11.4v1a6 6 0 0 0 12 0v-1"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path d="M12 18.4v2.8M9 21.2h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

export function SuitcaseIcon({ size = 22 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3.5" y="8" width="17" height="12" rx="2" fill="currentColor" />
      <path
        d="M9 8V6a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 6v2"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path d="M3.5 13h17" stroke="var(--icon-contrast, white)" strokeWidth="1.2" />
    </svg>
  )
}
