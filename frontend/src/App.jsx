import { useEffect, useState } from 'react'
import './App.css'

const VERDICT_LABEL = {
  potwierdzone: '✅ Potwierdzone',
  fałszywe: '❌ Fałsz',
  wprowadzające_w_błąd: '⚠️ Wprowadza w błąd',
  brak_wystarczających_dowodów: '❔ Brak wystarczających dowodów',
  nie_podlega_weryfikacji: '💬 Nie podlega weryfikacji',
}

const STANCE_LABEL = {
  supports: 'Potwierdza',
  refutes: 'Zaprzecza',
  context: 'Kontekst',
}

const SOURCE_TYPE_LABEL = {
  official: 'źródło urzędowe',
  dataset: 'dane publiczne',
  factcheck: 'fact-checking',
  media: 'media',
}

function sessionId() {
  // Per-browser pseudonymous id, so the user can delete their own demo data.
  try {
    let id = localStorage.getItem('tapcheck-session')
    if (!id) {
      id = 'web-' + crypto.randomUUID()
      localStorage.setItem('tapcheck-session', id)
    }
    return id
  } catch {
    return undefined
  }
}

function formatDate(value) {
  return value ? new Date(value).toLocaleDateString('pl-PL') : 'brak daty'
}

function Evidence({ item }) {
  return (
    <div className={`evidence ${item.stance}`}>
      <div className="meta">
        <strong>{STANCE_LABEL[item.stance]}</strong> · {item.publisher} ({SOURCE_TYPE_LABEL[item.source_type]}) ·
        opublikowano {formatDate(item.published_at)} · wiarygodność {item.credibility}/5
        {item.role === 'context_only' ? ' · tylko kontekst' : ` · waga ${item.weight.toFixed(2)}`}
        {item.archival_warning && ' · ⚠️ materiał archiwalny'}
      </div>
      <q>{item.quote}</q>
      <a href={item.url} target="_blank" rel="noopener noreferrer">
        {item.title}
      </a>
    </div>
  )
}

function ScoreBar({ score }) {
  // -1 (sources refute) … +1 (sources confirm); the marker sits on a 0-100% track.
  const position = ((score + 1) / 2) * 100
  const text = score.toFixed(2).replace('.', ',')
  return (
    <div className="score" aria-label={`Wynik dowodów ${text} w skali od minus 1 do plus 1`}>
      <div className="score-track" aria-hidden="true">
        <span className="score-zone" />
        <span className="score-marker" style={{ left: `${position}%` }} />
      </div>
      <div className="score-labels" aria-hidden="true">
        <span>−1 zaprzeczają</span>
        <strong>{score > 0 ? '+' : ''}{text}</strong>
        <span>potwierdzają +1</span>
      </div>
    </div>
  )
}

function Claim({ claim, index }) {
  return (
    <article className="claim">
      <span className={`badge ${claim.verdict}`}>{VERDICT_LABEL[claim.verdict]}</span>
      {claim.score !== null && <ScoreBar score={claim.score} />}
      <blockquote>
        {index + 1}. „{claim.text}”
      </blockquote>
      <p>{claim.explanation}</p>

      {claim.reasons.length > 0 && (
        <>
          <h3>Na czym opiera się ocena</h3>
          <ul>
            {claim.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}

      {claim.evidence.length > 0 && (
        <>
          <h3>Źródła (cytaty dosłowne)</h3>
          {claim.evidence.map((e, i) => (
            <Evidence key={i} item={e} />
          ))}
        </>
      )}

      {claim.source_warnings.length > 0 && (
        <>
          <h3>Informacje o źródle doniesienia</h3>
          <ul>
            {claim.source_warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </>
      )}

      {claim.limitations && (
        <>
          <h3>Ograniczenia</h3>
          <p>{claim.limitations}</p>
        </>
      )}
    </article>
  )
}

function Result({ data }) {
  if (data.status !== 'ok') {
    return (
      <div className="notice" role="status">
        ℹ️ {data.status_detail}
      </div>
    )
  }
  return (
    <section aria-live="polite">
      {data.claims.map((c, i) => (
        <Claim key={i} claim={c} index={i} />
      ))}
      {data.security_events.length > 0 && (
        <p className="security">🛡️ Wykryto i zignorowano polecenia ukryte w treści. Zdarzenie zostało zapisane.</p>
      )}
    </section>
  )
}

export default function App() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Shared result links (/r/<id>) from Discord or the SMS demo open the stored result.
  useEffect(() => {
    const match = window.location.pathname.match(/^\/r\/([a-f0-9]+)$/)
    if (!match) return
    fetch(`/api/check/${match[1]}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then(setResult)
      .catch(() => setError('Nie znaleziono wyniku — mógł zostać usunięty.'))
  }, [])

  async function submit(event) {
    event.preventDefault()
    if (!text.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const resp = await fetch('/api/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, channel: 'web', session_id: sessionId() }),
      })
      if (resp.status === 429) throw new Error('Zbyt wiele zapytań. Spróbuj ponownie za minutę.')
      if (!resp.ok) throw new Error('Usługa jest chwilowo niedostępna. To błąd techniczny, nie wynik sprawdzenia.')
      setResult(await resp.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function deleteMyData() {
    const id = sessionId()
    if (!id) return
    const resp = await fetch(`/api/session/${id}`, { method: 'DELETE' })
    const body = await resp.json()
    setResult(null)
    setError(`Usunięto zapisane sprawdzenia: ${body.deleted}.`)
  }

  return (
    <main className="page">
      <header>
        <h1>Tap &amp; Check</h1>
        <p>Sprawdź, zanim udostępnisz. Odpowiadamy tylko na podstawie jawnych, wiarygodnych źródeł.</p>
      </header>

      <form onSubmit={submit}>
        <label htmlFor="input">Wklej doniesienie, wiadomość albo link</label>
        <textarea
          id="input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Np. „Od przyszłego miesiąca wszyscy obywatele muszą…” albo https://…"
          maxLength={5000}
        />
        <div className="row">
          <button type="submit" disabled={loading}>
            {loading ? 'Sprawdzam…' : 'Sprawdź'}
          </button>
          <span className="hint">Nie wpisuj danych osobowych. Sprawdzenie trwa zwykle kilkanaście sekund.</span>
        </div>
      </form>

      {error && (
        <div className="notice" role="alert">
          ℹ️ {error}
        </div>
      )}
      {result && <Result data={result} />}

      <footer>
        <p>
          Tap &amp; Check pomaga ocenić informacje, ale nie jest „sędzią prawdy”. Zawsze możesz samodzielnie
          przeczytać źródła. Odpowiedzi przygotowuje system wykorzystujący sztuczną inteligencję.
        </p>
        <button type="button" className="secondary" onClick={deleteMyData}>
          Usuń moje dane z tej przeglądarki
        </button>
      </footer>
    </main>
  )
}
