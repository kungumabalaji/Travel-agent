import { useState } from 'react'
import ConciergeWidget from './components/ConciergeWidget'
import logo from './assets/loveholiday-logo-2024.webp'
import './App.css'

function App() {
  const [tab, setTab] = useState<'flights-hotel' | 'hotels'>('flights-hotel')

  return (
    <>
      <header className="top-bar">
        <div className="top-bar-inner">
          <img className="logo" src={logo} alt="loveholidays" />

          <div className="badges">
            <div className="badge">
              <span className="badge-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M8.5 12.5l2.2 2.2L15.8 9.5" />
                </svg>
              </span>
              <span>ATOL protected</span>
            </div>
            <div className="badge">
              <span className="badge-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                  <rect x="3" y="6" width="18" height="13" rx="2" />
                  <path d="M3 10h18M7 15h4" />
                </svg>
              </span>
              <span>Super-flexible payments</span>
            </div>
            <div className="badge">
              <span className="badge-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                  <path d="M5 13l4 4L19 7" />
                </svg>
              </span>
              <span>Best Price Promise</span>
            </div>
          </div>

          <div className="top-bar-icons">
            <button aria-label="Saved">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path d="M12 20s-7-4.35-9.5-8.5C.8 8.2 2.3 5 5.6 5c1.9 0 3.3 1 4.4 2.4C11.1 6 12.5 5 14.4 5c3.3 0 4.8 3.2 3.1 6.5C19 15.65 12 20 12 20z" />
              </svg>
            </button>
            <button aria-label="Account">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <circle cx="12" cy="8" r="3.2" />
                <path d="M5 20c1.5-4 4.2-6 7-6s5.5 2 7 6" />
              </svg>
            </button>
            <button aria-label="Menu">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path d="M4 7h16M4 12h16M4 17h16" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      <div className="sub-bar">
        <a href="#">Manage My Booking</a>
        <span className="sub-bar-divider">|</span>
        <a href="#">FAQs &amp; Travel Information</a>
      </div>

      <main>
        <section className="search-section">
          <div className="tabs">
            <button
              className={tab === 'flights-hotel' ? 'tab active' : 'tab'}
              onClick={() => setTab('flights-hotel')}
            >
              Flights + Hotel
            </button>
            <button className={tab === 'hotels' ? 'tab active' : 'tab'} onClick={() => setTab('hotels')}>
              Hotels
            </button>
          </div>

          <div className="search-card">
            <div className="search-field wide">
              <label>Destination(s) or Hotel name</label>
              <div className="search-input">
                <span className="field-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <path d="M12 21s-6.5-5.7-6.5-11A6.5 6.5 0 0 1 18.5 10c0 5.3-6.5 11-6.5 11z" />
                    <circle cx="12" cy="10" r="2.2" />
                  </svg>
                </span>
                <input type="text" placeholder="Any destination" />
              </div>
            </div>

            <div className="search-field">
              <label>Departure airport</label>
              <div className="search-input">
                <span className="field-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <path d="M3 13l7-2 4-8 2 1-2.5 7.5L21 10l1 2-7.5 3L13 21l-2-1 1-5.5z" />
                  </svg>
                </span>
                <input type="text" placeholder="Any departure airport" />
              </div>
            </div>

            <div className="search-field">
              <label>Departure date</label>
              <div className="search-input">
                <span className="field-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <rect x="3" y="5" width="18" height="16" rx="2" />
                    <path d="M3 10h18M8 3v4M16 3v4" />
                  </svg>
                </span>
                <input type="text" placeholder="Any date" />
              </div>
            </div>

            <div className="search-field">
              <label>How long</label>
              <div className="search-input">
                <span className="field-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <path d="M20 12.5A8 8 0 1 1 11.5 4a6.5 6.5 0 0 0 8.5 8.5z" />
                  </svg>
                </span>
                <input type="text" defaultValue="7 nights" />
              </div>
            </div>

            <div className="search-field">
              <label>Rooms</label>
              <div className="search-input">
                <span className="field-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <circle cx="9" cy="8" r="2.2" />
                    <circle cx="17" cy="9" r="1.8" />
                    <path d="M4 19c0-3 2.2-5 5-5s5 2 5 5M14 19c0-2.2 1.6-3.8 3.5-3.8s3.5 1.6 3.5 3.8" />
                  </svg>
                </span>
                <input type="text" defaultValue="1 Room / 2 Ad..." />
              </div>
            </div>

            <button className="search-button">Search</button>
          </div>
        </section>

        <section className="help-banner">
          <h2>Already booked?</h2>
          <p>
            Need to add luggage to an existing booking? Chat or start a voice call with our support
            assistant in the corner.
          </p>
        </section>
      </main>

      <footer className="site-footer">
        <p>Demo UI for the luggage support agent — not a real booking site.</p>
      </footer>

      <ConciergeWidget />
    </>
  )
}

export default App
