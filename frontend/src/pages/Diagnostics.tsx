import { useEffect, useRef, useState } from "react";
import { askDiagnostic, getDiagnosticStatus } from "../api/diagnostics";
import type { DiagnosticStatus, DiagnosticStep } from "../api/types";

const EXAMPLE_QUESTIONS = [
  "Which containers are using the most memory?",
  "Why did an alert fire recently?",
  "What does carevora/api depend on?",
  "Are any containers behaving abnormally?",
];

interface Turn {
  question: string;
  answer: string | null;
  error: string | null;
  steps: DiagnosticStep[];
  model: string | null;
  pending: boolean;
}

export function Diagnostics() {
  const [status, setStatus] = useState<DiagnosticStatus | undefined>(undefined);
  const [statusError, setStatusError] = useState<string | undefined>(undefined);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asking, setAsking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    getDiagnosticStatus()
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((err) => {
        if (!cancelled) setStatusError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, asking]);

  const disabled = asking || status?.enabled === false;

  const handleAsk = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text || disabled) return;

    setQuestion("");
    setAsking(true);
    setTurns((prev) => [
      ...prev,
      { question: text, answer: null, error: null, steps: [], model: null, pending: true },
    ]);

    try {
      const res = await askDiagnostic(text);
      setTurns((prev) =>
        prev.map((t, i) =>
          i === prev.length - 1
            ? { ...t, answer: res.answer, error: res.error, steps: res.steps ?? [], model: res.model, pending: false }
            : t,
        ),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setTurns((prev) =>
        prev.map((t, i) => (i === prev.length - 1 ? { ...t, error: message, pending: false } : t)),
      );
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="page diagnostics-page">
      <header className="page-header">
        <h1>Ask DockIQ</h1>
        <p className="page-subtitle">Ask questions about your fleet in plain language — DockIQ investigates live metrics, logs, and topology.</p>
      </header>

      {statusError && <div className="state state-error">Error checking diagnostics status: {statusError}</div>}

      {status && !status.enabled && (
        <div className="diagnostics-banner">
          Set <code>ANTHROPIC_API_KEY</code> in the backend to enable AI diagnostics.
        </div>
      )}

      <div className="diagnostics-transcript">
        {turns.length === 0 && (
          <div className="state state-empty">Ask a question below to get started.</div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="diagnostics-turn">
            <div className="diagnostics-question">
              <span className="diagnostics-avatar diagnostics-avatar-user">You</span>
              <div className="diagnostics-bubble">{t.question}</div>
            </div>
            <div className="diagnostics-answer">
              <span className="diagnostics-avatar diagnostics-avatar-bot">AI</span>
              <div className="diagnostics-bubble diagnostics-bubble-answer">
                {t.pending && (
                  <div className="diagnostics-thinking">
                    <span className="diagnostics-spinner" />
                    Investigating… querying metrics, logs, topology
                  </div>
                )}
                {!t.pending && t.error && <div className="state state-error">{t.error}</div>}
                {!t.pending && !t.error && t.answer && (
                  <div className="diagnostics-answer-text">{t.answer}</div>
                )}
                {!t.pending && !t.error && !t.answer && (
                  <div className="state state-empty">No answer returned.</div>
                )}
                {!t.pending && t.steps.length > 0 && (
                  <details className="diagnostics-steps">
                    <summary>How I investigated ({t.steps.length} step{t.steps.length === 1 ? "" : "s"})</summary>
                    <ol>
                      {t.steps.map((s, si) => (
                        <li key={si} className="mono">
                          {s.tool}({JSON.stringify(s.input)})
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="diagnostics-examples">
        {EXAMPLE_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            className="chip"
            disabled={disabled}
            onClick={() => handleAsk(q)}
          >
            {q}
          </button>
        ))}
      </div>

      <form
        className="diagnostics-input-bar"
        onSubmit={(e) => {
          e.preventDefault();
          handleAsk();
        }}
      >
        <textarea
          className="diagnostics-input"
          placeholder={
            status?.enabled === false
              ? "AI diagnostics is not configured"
              : "Ask about hosts, containers, alerts, or dependencies…"
          }
          value={question}
          disabled={disabled}
          rows={2}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleAsk();
            }
          }}
        />
        <button type="submit" className="btn" disabled={disabled || !question.trim()}>
          {asking ? "Asking…" : "Send"}
        </button>
      </form>
    </div>
  );
}
