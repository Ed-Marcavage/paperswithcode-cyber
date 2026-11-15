import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { assistantApi, assistantKeys, type AssistantMessage, type AssistantSurface } from "@/lib/api/assistant";
import { assistantEvent } from "@/lib/catalogAnalytics";
import { AssistantIcon } from "./icons";

type Rating = "good" | "bad";

export function AssistantFeedback({ message, surface = "panel" }: { message: AssistantMessage; surface?: AssistantSurface }) {
  const [rating, setRating] = useState<Rating | null>(message.feedback?.rating ?? null);
  const [note, setNote] = useState(message.feedback?.note ?? "");
  const [noteOpen, setNoteOpen] = useState(false);
  const noteId = useId();
  const client = useQueryClient();
  // thumb: a thumb press, counted once with its rating; saving the optional note afterwards is not another rating.
  const mutation = useMutation({ mutationFn: (value: { rating: Rating; note: string; thumb?: boolean }) => assistantApi.feedback(message.run_id!, value.rating, value.note),
    onSuccess: (_saved, value) => {
      if (value.thumb) assistantEvent("feedback_given", surface, { rating: value.rating });
      void client.invalidateQueries({ queryKey: ["assistant", "conversation"] }); void client.invalidateQueries({ queryKey: assistantKeys.list });
    } });
  if (!message.run_id || message.status === "running") return null;
  // A thumb saves at once; the note is an optional follow-up on the same rating.
  const rate = (value: Rating) => { setRating(value); setNoteOpen(true); mutation.reset(); mutation.mutate({ rating: value, note, thumb: true }); };
  return <div className="assistant-feedback ph-mask">
    <div className="assistant-feedback-row" role="group" aria-label="Rate this answer">
      <button type="button" className="assistant-icon-button" aria-pressed={rating === "good"} aria-label="Good answer" title="Good answer"
        disabled={mutation.isPending} onClick={() => rate("good")}><AssistantIcon name="thumbUp" size={15} /></button>
      <button type="button" className="assistant-icon-button" aria-pressed={rating === "bad"} aria-label="Bad answer" title="Bad answer"
        disabled={mutation.isPending} onClick={() => rate("bad")}><AssistantIcon name="thumbDown" size={15} /></button>
      {mutation.isSuccess && <span role="status" className="assistant-feedback-thanks">Thanks for the feedback.</span>}
      {mutation.isError && <span role="alert" className="assistant-feedback-error">Feedback could not be saved. Try again.</span>}
    </div>
    {rating && noteOpen && !(mutation.isSuccess && mutation.variables?.note) && <form className="assistant-feedback-note" onSubmit={event => { event.preventDefault(); mutation.mutate({ rating, note }); }}>
      <label htmlFor={noteId} className="sr-only">Optional note</label>
      <input id={noteId} value={note} maxLength={500} placeholder={rating === "good" ? "What was useful? (optional)" : "What was missing or wrong? (optional)"}
        onChange={event => { setNote(event.target.value); mutation.reset(); }} />
      <button type="submit" disabled={mutation.isPending || !note.trim()}>Send note</button>
    </form>}
  </div>;
}
