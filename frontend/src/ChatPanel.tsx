import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { ChatMessage } from "./types";

const PROMPTS = ["Gold price", "Bitcoin and Ethereum", "Portfolio", "Open positions"];

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .chatHistory()
      .then((thread) => {
        if (!cancelled) setMessages(thread.messages);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const node = logRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, busy]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true);
    setError("");
    setDraft("");
    try {
      const thread = await api.chatSend(message);
      setMessages(thread.messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed");
      setDraft(message);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Trading chat</h1>
          <p>Ask about gold, Bitcoin, Ethereum, positions, and the agent. Chat cannot place orders.</p>
        </div>
      </div>
      <div className="card chat-panel">
        <div className="chat-log" ref={logRef}>
          {messages.length === 0 && (
            <div className="chat-empty">
              Ask for a live quote or the portfolio. Orders still go through the risk engine.
            </div>
          )}
          {messages.map((message) => (
            <div key={message.id} className={`chat-bubble ${message.role}`}>
              <div className="chat-role">{message.role === "user" ? "You" : "Desk"}</div>
              <p>{message.content}</p>
            </div>
          ))}
          {busy && <div className="chat-bubble assistant">Checking the desk…</div>}
        </div>
        {error && <div className="alert error chat-error">{error}</div>}
        <div className="chat-prompts">
          {PROMPTS.map((prompt) => (
            <button key={prompt} type="button" className="btn btn-sm" disabled={busy} onClick={() => void send(prompt)}>
              {prompt}
            </button>
          ))}
        </div>
        <form className="chat-composer" onSubmit={onSubmit}>
          <input
            aria-label="Message"
            value={draft}
            placeholder="Ask about gold, BTC, or ETH"
            onChange={(event) => setDraft(event.target.value)}
            disabled={busy}
          />
          <button className="btn btn-primary" type="submit" disabled={busy || !draft.trim()}>
            Send
          </button>
        </form>
      </div>
    </>
  );
}
