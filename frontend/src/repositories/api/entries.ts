import type { Entry, EntryFormat, EntryStatus, EntryUpdate } from "../types";
import { apiRequest } from "./client";

export interface ListEntriesParams {
  status?: EntryStatus;
  format?: EntryFormat;
}

export function listEntries(params: ListEntriesParams = {}): Promise<Entry[]> {
  return apiRequest<Entry[]>("/entries", { query: { status: params.status, format: params.format } });
}

export function getEntry(id: number): Promise<Entry> {
  return apiRequest<Entry>(`/entries/${id}`);
}

export function updateEntry(id: number, patch: EntryUpdate): Promise<Entry> {
  return apiRequest<Entry>(`/entries/${id}`, { method: "PATCH", body: patch });
}

export function approveEntry(id: number): Promise<Entry> {
  return apiRequest<Entry>(`/entries/${id}/approve`, { method: "POST" });
}
