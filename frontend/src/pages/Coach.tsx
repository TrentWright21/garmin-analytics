import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { api, type ChatMessage, type ConversationSummary } from "../api";
import PaceCoach from "./PaceCoach";

const SUGGESTIONS = [
  "How's my training load looking this week?",
  "Am I recovering well lately?",
  "Should I run hard today or take it easy?",
  "What stands out in my sleep this month?",
];

/** Coach hub: the AI chat and the VDOT Pace Coach as sibling tabs (Phase 3b).
 * Tabs are real routes (/coach, /coach/pace) so each is linkable/bookmarkable. */
export default function Coach({ tab = "chat" }: { tab?: "chat" | "pace" }) {
  const chip = ({ isActive }: { isActive: boolean }) => `chip ${isActive ? "on" : ""}`;
  return (
    <>
      <div className="topbar">
        <div>
          <h1>Coach</h1>
          <div className="sub">
            {tab === "pace"
              ? "VDOT-based goal setting & a plan to get there — Jack Daniels' running-science model"
              : "Ask about your own Garmin trends — it reads your real numbers"}
          </div>
        </div>
        <div className="chips">
          <NavLink to="/coach" end className={chip}>
            AI Chat
          </NavLink>
          <NavLink to="/coach/pace" className={chip}>
            Pace Coach
          </NavLink>
        </div>
      </div>
      {tab === "pace" ? <PaceCoach /> : <ChatPanel />}
    </>
  );
}

function ChatPanel() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.coachStatus().then((s) => setConfigured(s.configured)).catch(() => setConfigured(null));
    refreshConversations();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function refreshConversations() {
    try {
      const r = await api.conversations();
      setConversations(r.conversations);
    } catch {
      /* listing is non-critical */
    }
  }

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setError(null);
  }

  async function openConversation(id: string) {
    if (id === activeId) return;
    setError(null);
    try {
      const r = await api.conversation(id);
      setActiveId(id);
      setMessages(r.messages);
    } catch {
      setError("Couldn't load that conversation.");
    }
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending) return;
    setInput("");
    setError(null);
    setMessages((m) => [...m, { role: "user", content: message }]);
    setSending(true);
    try {
      const res = await api.chat(message, activeId);
      if (res.conversation_id) setActiveId(res.conversation_id);
      setMessages((m) => [...m, { role: "assistant", content: res.reply }]);
      if (res.configured) refreshConversations();
    } catch {
      setError("The Coach couldn't reply just now — is the backend running? Try again.");
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  return (
    <div className="coach-layout">
      <aside className="coach-convs">
        <button className="btn primary coach-new" onClick={newChat}>
          + New chat
        </button>
        <div className="coach-conv-list">
          {conversations.length === 0 && (
            <div className="muted" style={{ padding: "8px 4px", fontSize: 13 }}>
              No conversations yet.
            </div>
          )}
          {conversations.map((c) => (
            <button
              key={c.id}
              className={`conv-item ${c.id === activeId ? "active" : ""}`}
              onClick={() => openConversation(c.id)}
              title={c.title}
            >
              <span className="conv-title">{c.title}</span>
              <span className="conv-count">{c.message_count}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="coach-panel">
        <div className="coach-head">
          <div>
            <div className="card-title" style={{ marginBottom: 2 }}>
              AI Coach
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              Ask about your own Garmin trends — it reads your real numbers.
            </div>
          </div>
        </div>

        {configured === false && (
          <div className="coach-banner">
            The AI Coach isn't set up yet. Add <code>GA_ANTHROPIC_API_KEY=sk-ant-…</code> to your{" "}
            <code>.env</code> file (get a key at platform.claude.com), then restart the app.
          </div>
        )}

        <div className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="chat-empty">
              <div className="chat-empty-title">What would you like to know?</div>
              <div className="chat-empty-chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="prompt-chip" onClick={() => send(s)} disabled={sending}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="msg-role">{m.role === "user" ? "You" : "Coach"}</div>
              <div className="msg-body">{m.content}</div>
            </div>
          ))}
          {sending && (
            <div className="msg assistant">
              <div className="msg-role">Coach</div>
              <div className="msg-body typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
        </div>

        {error && <div className="coach-error">{error}</div>}

        <div className="chat-input-row">
          <textarea
            className="chat-textarea"
            placeholder="Ask your coach…  (Enter to send, Shift+Enter for a new line)"
            value={input}
            rows={1}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            className="btn primary"
            onClick={() => send(input)}
            disabled={sending || !input.trim()}
          >
            {sending ? "…" : "Send"}
          </button>
        </div>
      </section>
    </div>
  );
}
