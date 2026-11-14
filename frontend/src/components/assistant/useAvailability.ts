import { useQuery } from "@tanstack/react-query";
import { assistantApi, assistantKeys, type AssistantStatus } from "@/lib/api/assistant";

export function useAvailability(): AssistantStatus {
  const query = useQuery({ queryKey: assistantKeys.status, queryFn: assistantApi.status, retry: false,
    refetchInterval: query => {
      const reset = query.state.data?.retry_at;
      return reset ? Math.max(250, Math.min(30_000, Date.parse(reset) - Date.now() + 100)) : 30_000;
    },
  });
  return query.data ?? { available: false, code: query.isError ? "unavailable" : "checking",
    reason: query.isError ? "The assistant is unavailable. Please try again shortly." : "Checking assistant availability…", retry_at: null };
}
