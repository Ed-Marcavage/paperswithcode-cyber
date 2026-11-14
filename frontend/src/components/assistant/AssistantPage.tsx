import { assistantEvent } from "@/lib/catalogAnalytics";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { assistantApi, assistantKeys, type AssistantSummary } from "@/lib/api/assistant";
import { AssistantConversationView } from "./AssistantConversation";
import { useAssistant } from "./context";

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
    onSuccess: () => { setEditing(null); void queryClient.invalidateQueries({ queryKey: assistantKeys.list }); } });
  const remove = useMutation({ mutationFn: assistantApi.delete, onSuccess: (_result, id) => {
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
  return <section className="assistant-page" aria-label="Your chats">
    <button className="assistant-history-toggle" type="button" aria-expanded={drawer} onClick={() => setDrawer(!drawer)}>Your chats</button>
    {drawer && <button className="assistant-drawer-backdrop" aria-label="Close chat list" onClick={() => setDrawer(false)} />}
    <aside className={`assistant-history ${drawer ? "is-open" : ""}`} aria-label="Chat history">
      <div className="assistant-history-heading"><h1>Your chats</h1><button type="button" onClick={start}>New chat</button></div>
      {list.isPending && <p>Loading chats…</p>}
      {list.isError && <p role="alert">Your chats could not be loaded. <button onClick={() => void list.refetch()}>Try again</button></p>}
      <ul className="ph-mask">{list.data?.map(item => <li key={item.id}>
        <Link to={`/chat/${item.id}`} aria-current={chat.currentId === item.id ? "page" : undefined} onClick={() => setDrawer(false)}>{item.title}</Link>
        <time dateTime={item.updated_at}>{new Date(item.updated_at).toLocaleDateString()}</time>
        <div><button type="button" aria-label="Rename chat" onClick={() => { rename.reset(); setEditing(item); setTitle(item.title); }}>Rename</button>
          <button type="button" aria-label="Delete chat" onClick={() => { remove.reset(); setRemoving(item); }}>Delete</button></div>
      </li>)}</ul>
    </aside>
    <div className="assistant-page-main"><AssistantConversationView surface="chat_page" /></div>
    {editing && <div className="assistant-modal-backdrop"><form role="dialog" aria-modal="true" aria-label="Rename chat" className="assistant-modal ph-mask"
      onKeyDown={event => { if (event.key === "Escape") setEditing(null); }}
      onSubmit={event => { event.preventDefault(); if (title.trim()) rename.mutate({ id: editing.id, title: title.trim() }); }}>
      <label htmlFor="assistant-chat-title">Chat title</label><input id="assistant-chat-title" value={title} onChange={e => setTitle(e.target.value)} maxLength={60} autoFocus />
      {rename.isError && <p role="alert">The title could not be saved. Try again.</p>}
      <button type="button" onClick={() => setEditing(null)}>Cancel</button><button disabled={!title.trim() || rename.isPending}>Save title</button>
    </form></div>}
    {removing && <div className="assistant-modal-backdrop"><div role="alertdialog" aria-modal="true" aria-label="Delete chat" aria-describedby="assistant-delete-description" className="assistant-modal ph-mask">
      <p id="assistant-delete-description">Delete “{removing.title}” and all its messages? This cannot be undone.</p>
      {remove.isError && <p role="alert">The chat could not be deleted. Try again.</p>}
      <button type="button" autoFocus onClick={() => setRemoving(null)}>Cancel</button>
      <button type="button" disabled={remove.isPending} onClick={() => remove.mutate(removing.id)}>Delete chat</button>
    </div></div>}
  </section>;
}
