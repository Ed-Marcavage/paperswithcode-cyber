import { assistantEvent } from "@/lib/catalogAnalytics";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { assistantApi, assistantKeys, type AssistantSummary } from "@/lib/api/assistant";
import { AssistantConversationView } from "./AssistantConversation";
import { useAssistant } from "./context";
import { AssistantIcon } from "./icons";
import { friendlyDate } from "./format";

export default function AssistantPage() {
  const chat = useAssistant();
  useEffect(() => { assistantEvent("opened", "chat_page"); }, []);
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const applied = useRef<string>();
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<AssistantSummary | null>(null);
  const [title, setTitle] = useState("");
  const [removing, setRemoving] = useState<AssistantSummary | null>(null);
  const list = useQuery({ queryKey: assistantKeys.list, queryFn: assistantApi.list });
  const rename = useMutation({ mutationFn: ({ id, title }: { id: string; title: string }) => assistantApi.rename(id, title),
    onSuccess: () => { assistantEvent("chat_renamed", "chat_page"); setEditing(null); void queryClient.invalidateQueries({ queryKey: assistantKeys.list }); } });
  const remove = useMutation({ mutationFn: assistantApi.delete, onSuccess: (_result, id) => {
    assistantEvent("chat_deleted", "chat_page");
    setRemoving(null); queryClient.removeQueries({ queryKey: assistantKeys.conversation(id) });
    void queryClient.invalidateQueries({ queryKey: assistantKeys.list });
    if (chat.currentId === id) { chat.newChat("chat_page"); navigate("/chat", { replace: true }); }
  } });
  useEffect(() => {
    if (sessionId !== applied.current) {
      applied.current = sessionId;
      if (sessionId) { chat.selectConversation(sessionId); return; }
    }
    if (!chat.loading && chat.currentId && chat.conversation.id === chat.currentId && sessionId !== chat.currentId) {
      navigate(`/chat/${chat.currentId}`, { replace: true });
    }
  }, [sessionId, chat, navigate]);
  const start = () => { chat.newChat("chat_page"); setDrawer(false); navigate("/chat"); };
  const listed = list.data?.find(item => item.id === chat.currentId)?.title;
  const chatTitle = chat.conversation.messages.length ? listed ?? (chat.conversation.title === "New chat" ? "" : chat.conversation.title) : "";
  return <section className="assistant-page" aria-label="Your chats">
    <div className="assistant-page-bar">
      <button className="assistant-history-toggle" type="button" aria-expanded={drawer} aria-controls="assistant-history" onClick={() => setDrawer(!drawer)}>
        <AssistantIcon name="chats" /><span>Your chats</span></button>
      {/* No title attribute: replay masks text in .ph-mask but records attributes as written. */}
      {chatTitle && <p className="assistant-page-title ph-mask">{chatTitle}</p>}
    </div>
    {drawer && <button className="assistant-drawer-backdrop" aria-label="Close chat list" onClick={() => setDrawer(false)} />}
    <aside id="assistant-history" className={`assistant-history ${drawer ? "is-open" : ""}`} aria-label="Chat history"
      onKeyDown={event => { if (event.key === "Escape" && drawer) { event.preventDefault(); setDrawer(false); } }}>
      <div className="assistant-history-heading">
        <h1>Your chats</h1>
        <button type="button" className="assistant-new-chat" onClick={start}><AssistantIcon name="plus" size={14} /><span>New chat</span></button>
      </div>
      {list.isPending && <p className="assistant-history-state">Loading chats…</p>}
      {list.isError && <p role="alert" className="assistant-history-state">Your chats could not be loaded. <button type="button" onClick={() => void list.refetch()}>Try again</button></p>}
      {list.data?.length === 0 && <p className="assistant-history-state">Your chats will appear here. Each is kept for 90 days after its last message.</p>}
      <ul className="ph-mask">{list.data?.map(item => {
        const current = chat.currentId === item.id;
        return <li key={item.id} className={current ? "is-current" : undefined}>
          <Link to={`/chat/${item.id}`} aria-current={current ? "page" : undefined} onClick={() => setDrawer(false)}>
            <span className="assistant-history-title">{item.title}</span>
            <time dateTime={item.updated_at}>{friendlyDate(item.updated_at)}</time>
          </Link>
          <div className="assistant-history-actions">
            <button type="button" className="assistant-icon-button" aria-label="Rename chat" title="Rename" onClick={() => { rename.reset(); setEditing(item); setTitle(item.title); }}><AssistantIcon name="pencil" size={14} /></button>
            <button type="button" className="assistant-icon-button" aria-label="Delete chat" title="Delete" onClick={() => { remove.reset(); setRemoving(item); }}><AssistantIcon name="trash" size={14} /></button>
          </div>
        </li>;
      })}</ul>
    </aside>
    <div className="assistant-page-main"><AssistantConversationView surface="chat_page" /></div>
    {editing && <div className="assistant-modal-backdrop"><form role="dialog" aria-modal="true" aria-label="Rename chat" className="assistant-modal ph-mask"
      onKeyDown={event => { if (event.key === "Escape") setEditing(null); }}
      onSubmit={event => { event.preventDefault(); if (title.trim()) rename.mutate({ id: editing.id, title: title.trim() }); }}>
      <h2 className="assistant-modal-title">Rename chat</h2>
      <label htmlFor="assistant-chat-title">Chat title</label><input id="assistant-chat-title" value={title} onChange={e => setTitle(e.target.value)} maxLength={60} autoFocus />
      {rename.isError && <p role="alert" className="assistant-modal-error">The title could not be saved. Try again.</p>}
      <div className="assistant-modal-actions"><button type="button" onClick={() => setEditing(null)}>Cancel</button>
        <button className="is-primary" disabled={!title.trim() || rename.isPending}>Save title</button></div>
    </form></div>}
    {removing && <div className="assistant-modal-backdrop"><div role="alertdialog" aria-modal="true" aria-label="Delete chat" aria-describedby="assistant-delete-description" className="assistant-modal ph-mask"
      onKeyDown={event => { if (event.key === "Escape") setRemoving(null); }}>
      <h2 className="assistant-modal-title">Delete chat</h2>
      <p id="assistant-delete-description">Delete “{removing.title}” and all its messages? This cannot be undone.</p>
      {remove.isError && <p role="alert" className="assistant-modal-error">The chat could not be deleted. Try again.</p>}
      <div className="assistant-modal-actions"><button type="button" autoFocus onClick={() => setRemoving(null)}>Cancel</button>
        <button type="button" className="is-danger" disabled={remove.isPending} onClick={() => remove.mutate(removing.id)}>Delete chat</button></div>
    </div></div>}
  </section>;
}
