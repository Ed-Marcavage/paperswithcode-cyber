import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { assistantApi, assistantKeys, type AssistantMessage, type AssistantSurface } from "@/lib/api/assistant";
import { assistantEvent } from "@/lib/catalogAnalytics";

export function AssistantFeedback({ message, surface = "panel" }: { message: AssistantMessage; surface?: AssistantSurface }) {
  const [rating, setRating] = useState<"good" | "bad" | null>(message.feedback?.rating ?? null);
  const [note, setNote] = useState(message.feedback?.note ?? "");
  const noteId = useId();
  const client = useQueryClient();
  const mutation = useMutation({ mutationFn: () => assistantApi.feedback(message.run_id!, rating!, note),
    onSuccess: () => { assistantEvent("feedback_given", surface); void client.invalidateQueries({ queryKey: ["assistant", "conversation"] }); void client.invalidateQueries({ queryKey: assistantKeys.list }); } });
  if (!message.run_id || message.status === "running") return null;
  return <details className="assistant-feedback ph-mask"><summary>Give feedback</summary>
    <form onSubmit={event => { event.preventDefault(); if (rating) mutation.mutate(); }}>
      <div role="group" aria-label="Rate this answer">
        <button type="button" aria-pressed={rating === "good"} onClick={() => { setRating("good"); mutation.reset(); }}>Good answer</button>
        <button type="button" aria-pressed={rating === "bad"} onClick={() => { setRating("bad"); mutation.reset(); }}>Bad answer</button>
      </div>
      <label htmlFor={noteId}>Optional note</label><textarea id={noteId} value={note} maxLength={500} rows={2} onChange={event => { setNote(event.target.value); mutation.reset(); }} />
      <button type="submit" disabled={!rating || mutation.isPending}>Save feedback</button>
      {mutation.isSuccess && <span role="status">Feedback saved.</span>}
      {mutation.isError && <span role="alert">Feedback could not be saved. Please try again.</span>}
    </form>
  </details>;
}
