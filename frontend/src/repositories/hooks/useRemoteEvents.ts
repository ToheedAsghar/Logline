import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listRemoteEvents, triggerRemoteFetch } from "../api/remoteEvents";
import type { RemoteEventList, RemoteEventListParams } from "../types";

export const REMOTE_EVENTS_KEY = "remote-events";

export function useRemoteEvents(params: Omit<RemoteEventListParams, "cursor">) {
  return useInfiniteQuery<RemoteEventList, Error, { pages: RemoteEventList[]; pageParams: (string | null)[] }, ReturnType<typeof buildQueryKey>, string | null>({
    queryKey: buildQueryKey(params),
    queryFn: ({ pageParam }) => listRemoteEvents({ ...params, cursor: pageParam }),
    initialPageParam: null,
    getNextPageParam: (lastPage) => (lastPage.has_more && lastPage.next_cursor ? lastPage.next_cursor : undefined),
  });
}

export function useTriggerRemoteFetch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerRemoteFetch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [REMOTE_EVENTS_KEY] });
    },
  });
}

function buildQueryKey(params: Omit<RemoteEventListParams, "cursor">) {
  return [REMOTE_EVENTS_KEY, params.source ?? null, params.date_range_start ?? null, params.date_range_end ?? null] as const;
}
