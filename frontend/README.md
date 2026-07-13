# Frontend

A loveholidays-styled demo site (React + Vite + TypeScript) with two floating
support widgets: text chat and live voice call. It's a shell to demonstrate
the two backend agents (`../backend/chatagent`, `../backend/voiceagent`) —
the search form is a static mockup, not a real booking flow.

## Run

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173`. Requires both backend services running
(see the root [README.md](../README.md)):

- Chat agent on `:8001` — the dev server proxies `/api/*` to it
  (`vite.config.ts`), so `ChatWidget.tsx` just calls `/api/chat`.
- Voice agent on `:8002` — `VoiceWidget.tsx` calls it directly at
  `http://127.0.0.1:8002` (not proxied, since it also needs to work from a
  deployed static build later).

## Structure

```
src/
├── App.tsx                    # landing page shell (header, search mockup)
├── components/
│   ├── ChatWidget.tsx/.css    # floating text chat, calls /api/chat
│   ├── VoiceWidget.tsx/.css   # floating voice call, retell-client-js-sdk
│   ├── icons.tsx              # shared inline SVG icons (no icon library)
│   └── widget-launcher.css    # shared launcher button/tooltip/pulse styles
└── types.ts                   # ChatMessage / ChatResponse types
```

## Notes

- No component library or CSS framework — plain CSS files per component,
  a handful of CSS custom properties (`App.css`) for the shared brand
  colors. Deliberately kept this way for a project this size; see
  `DESIGN_NOTES.md` at the repo root for the reasoning on other choices.
- Icons are hand-written inline SVG (`components/icons.tsx`), not an icon
  library — kept the bundle dependency-free for four icons.
