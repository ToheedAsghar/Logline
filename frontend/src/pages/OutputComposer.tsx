import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loading } from "@/atoms";
import { AgentTriggerButton } from "@/molecules";
import { ENTRIES_KEY, useEntries } from "@/repositories/hooks";
import type { EntryFormat, StandupContent } from "@/repositories/types";

type Format = EntryFormat;

export default function OutputComposer() {
  const [format] = useState<Format>("standup");
  const [copied, setCopied] = useState(false);

  const [includeNext, setIncludeNext] = useState(true);
  const [includeBlockers, setIncludeBlockers] = useState(true);

  const queryClient = useQueryClient();
  const draftsQuery = useEntries({ status: "draft", format });
  const draft = draftsQuery.data?.[0];

  const content = (draft?.content as StandupContent) ?? {
    yesterday: "Worked on AI reconciliation worker logic and patched retry backoff.",
    today: "Built the draft editing flow and verified tests on localhost.",
    blockers: "None.",
  };

  const computedText = (() => {
    let text = `What I did\n• ${content.yesterday || "No entries saved."}\n`;
    if (includeNext) {
      text += `\nToday\n• ${content.today || "Continue work on active workstreams."}\n`;
    }
    if (includeBlockers) {
      text += `\nBlockers\n• ${content.blockers || "None."}`;
    }
    return text.trim();
  })();

  const [customOutputText, setCustomOutputText] = useState<string | null>(null);
  const outputText = customOutputText ?? computedText;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(outputText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const handleGenerateSuccess = () => {
    queryClient.invalidateQueries({ queryKey: [ENTRIES_KEY] });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[#191917]">Standup</h1>
          <p className="mt-1 text-sm text-[#6E6C62]">
            Built from your saved entries. Unsaved drafts are never included.
          </p>
        </div>
      </div>

      <div className="flex gap-6 items-start">
        <div className="w-72 flex-none space-y-4 rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] p-4 shadow-sm">
          <div className="space-y-2 border-b border-[#E3DFD2] pb-4">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C] block">SOURCE DAY</span>
            <div className="rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-2 font-mono text-xs font-medium text-[#191917]">
              Today (Saved entries)
            </div>
            <div className="flex items-center gap-2 pt-1">
              <span className="h-1.5 w-1.5 rounded-full bg-[#14603C]" />
              <span className="font-mono text-[11px] text-[#6E6C62]">6 approved workstream blocks</span>
            </div>
          </div>

          <div className="space-y-3">
            <span className="font-mono text-[10px] tracking-wider text-[#8A887C] block">SECTIONS</span>
            <div className="space-y-2 text-xs text-[#191917]">
              <label className="flex items-start gap-2.5 cursor-pointer rounded p-1.5 hover:bg-[#F5F2EA]">
                <input
                  type="checkbox"
                  checked={true}
                  disabled
                  className="mt-0.5 rounded accent-[#14603C]"
                />
                <div>
                  <span className="font-medium block">What I completed</span>
                  <span className="font-mono text-[10.5px] text-[#8A887C]">Yesterday&apos;s approved entries</span>
                </div>
              </label>

              <label className="flex items-start gap-2.5 cursor-pointer rounded p-1.5 hover:bg-[#F5F2EA]">
                <input
                  type="checkbox"
                  checked={includeNext}
                  onChange={(e) => setIncludeNext(e.target.checked)}
                  className="mt-0.5 rounded accent-[#14603C]"
                />
                <div>
                  <span className="font-medium block">What I am doing next</span>
                  <span className="font-mono text-[10.5px] text-[#8A887C]">Inferred from current workstream</span>
                </div>
              </label>

              <label className="flex items-start gap-2.5 cursor-pointer rounded p-1.5 hover:bg-[#F5F2EA]">
                <input
                  type="checkbox"
                  checked={includeBlockers}
                  onChange={(e) => setIncludeBlockers(e.target.checked)}
                  className="mt-0.5 rounded accent-[#14603C]"
                />
                <div>
                  <span className="font-medium block">Blockers & notes</span>
                  <span className="font-mono text-[10.5px] text-[#8A887C]">Unresolved issues & review notes</span>
                </div>
              </label>
            </div>
          </div>

          <div className="pt-2 border-t border-[#E3DFD2]">
            <AgentTriggerButton
              task={format === "standup" ? "generate today's standup" : "generate today's project log"}
              label={`Re-generate ${format === "standup" ? "Standup" : "Log"}`}
              workingLabel="Checking tools…"
              onSuccess={handleGenerateSuccess}
            />
          </div>
        </div>

        <div className="flex-1 min-w-0 rounded-lg border border-[#E3DFD2] bg-[#FFFDF7] shadow-sm overflow-hidden">
          <div className="flex items-baseline justify-between border-b border-[#E3DFD2] px-5 py-3.5 bg-[#FAF8F1]">
            <span className="font-semibold text-sm text-[#191917]">Standup script</span>
          </div>

          {draftsQuery.isLoading && <div className="p-8"><Loading label="Loading standup script…" /></div>}

          {!draftsQuery.isLoading && (
            <>
              <textarea
                value={outputText}
                onChange={(e) => setCustomOutputText(e.target.value)}
                spellCheck={false}
                rows={12}
                className="w-full bg-[#FFFDF7] p-5 font-mono text-xs leading-relaxed text-[#191917] focus:outline-none resize-none border-b border-[#E3DFD2]"
              />

              <div className="flex items-center justify-between gap-4 bg-[#FAF8F1] px-5 py-3.5">
                <span className="text-xs text-[#6E6C62]">
                  Edit anything here before you read it out — changes are not written back to your log.
                </span>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="rounded-md border border-[#14603C] bg-[#14603C] px-4 py-2 text-xs font-semibold text-[#FFFDF7] shadow-sm hover:bg-[#0F4E31]"
                >
                  {copied ? "Copied! ✓" : "Copy standup to clipboard"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

