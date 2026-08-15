// litkit dsh adapter — academic literature tools for DeepSeek Harness.
//
// Registers litkit_* tools that shell out to the `litkit` CLI (JSON output).
// The CLI must be installed and on PATH: `pip install litkit-search`
// (`litkit doctor` reports the environment; missing tools produce a readable
// error instead of a silent failure).
//
// Imports of @deepseek-ai/* resolve against the dsh host installation, the
// same way other out-of-tree bundles (dsh-bash-terminal, dsh-genui) load.

import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileP = promisify(execFile);
const TOOL_TIMEOUT_MS = 120_000;
const MAX_BUFFER = 32 * 1024 * 1024;

export const name = "litkit";
export const inject = ["tools", "systemPrompt"];

async function litkitJson(args) {
  const { stdout } = await execFileP("litkit", args, {
    timeout: TOOL_TIMEOUT_MS,
    maxBuffer: MAX_BUFFER,
    windowsHide: true,
  });
  return JSON.parse(stdout.trim());
}

function friendlyError(err) {
  const stderr = err?.stderr?.toString?.()?.trim?.() ?? "";
  const detail = stderr || err?.message || String(err);
  return new Error(
    `litkit CLI error: ${String(detail).slice(0, 2000)}\n` +
      "Ensure the litkit CLI is installed and on PATH " +
      "(pip install litkit-search), then run `litkit doctor` for diagnostics.",
  );
}

function jsonTool(name, description, parameters, buildArgs) {
  return {
    name,
    description,
    parameters,
    output: {
      schema: { type: "string", description: "JSON result from the litkit CLI." },
      render: (_args, value) => [{ type: "text", text: value }],
    },
    async execute(args) {
      let data;
      try {
        data = await litkitJson(buildArgs(args));
      } catch (err) {
        throw friendlyError(err);
      }
      return JSON.stringify(data, null, 2);
    },
  };
}

export function apply(ctx) {
  ctx.tools.register(
    jsonTool(
      "litkit_search",
      "Search academic literature across 25+ sources (arXiv, PubMed, Crossref, Semantic Scholar, OpenAlex, DBLP, IEEE Xplore, Scopus, WoS, SSRN, bioRxiv, ...). Use for scholarly literature search, literature review, and citation hunting — prefer this over generic web search for academic queries.",
      {
        query: { type: "string", required: true, description: "The search query." },
        limit: { type: "integer", description: "Results per source (default 20)." },
        sources: { type: "string", description: 'Comma-separated source names, or "all".' },
        year_from: { type: "integer", description: "Optional start year filter." },
        year_to: { type: "integer", description: "Optional end year filter." },
      },
      (a) => {
        const argv = ["--json", "search", a.query];
        if (a.limit) argv.push("--limit", String(a.limit));
        if (a.sources && a.sources !== "all") argv.push("--sources", a.sources);
        if (a.year_from) argv.push("--year-from", String(a.year_from));
        if (a.year_to) argv.push("--year-to", String(a.year_to));
        return argv;
      },
    ),
  );

  ctx.tools.register(
    jsonTool(
      "litkit_sources",
      "List all registered academic literature sources and whether each requires an API key.",
      {},
      () => ["--json", "sources"],
    ),
  );

  ctx.tools.register(
    jsonTool(
      "litkit_download",
      "Search papers and attempt PDF downloads. Returns per-paper records with the local download path (null when a download failed).",
      {
        query: { type: "string", required: true, description: "Search query or DOI." },
        limit: { type: "integer", description: "Number of papers to attempt (default 10)." },
        sources: { type: "string", description: 'Comma-separated source names, or "all".' },
      },
      (a) => {
        const argv = ["--json", "download", a.query];
        if (a.limit) argv.push("--limit", String(a.limit));
        if (a.sources && a.sources !== "all") argv.push("--sources", a.sources);
        return argv;
      },
    ),
  );

  ctx.tools.register(
    jsonTool(
      "litkit_doctor",
      "Run litkit environment self-checks (Python version, core dependencies, sources registry, network reachability, optional tools).",
      {},
      () => ["--json", "doctor"],
    ),
  );

  ctx.tools.register({
    name: "litkit_verify",
    description:
      "Verify references in a manuscript (.docx/.pdf). Requires anystyle (gem install anystyle) for .docx, or GROBID for .pdf — missing tools return a readable error, never a silent empty result.",
    parameters: {
      manuscript: { type: "string", required: true, description: "Path to the .docx or .pdf manuscript." },
      output: { type: "string", description: "Output directory for the audit report." },
    },
    output: {
      schema: { type: "string", description: "CLI output of the verify command." },
      render: (_args, value) => [{ type: "text", text: value }],
    },
    async execute(args) {
      const argv = ["verify", args.manuscript];
      if (args.output) argv.push("-o", args.output);
      try {
        const { stdout } = await execFileP("litkit", argv, {
          timeout: TOOL_TIMEOUT_MS,
          maxBuffer: MAX_BUFFER,
          windowsHide: true,
        });
        return stdout.trim();
      } catch (err) {
        throw friendlyError(err);
      }
    },
  });

  ctx.systemPrompt.section({
    name: "tool:litkit",
    order: 106,
    text: "Use the litkit_* tools (litkit_search, litkit_verify, litkit_sources) for academic literature search, literature review, and citation verification — they query 25+ scholarly sources directly. Prefer litkit over generic web search for scholarly queries. If litkit tools report a CLI error, run litkit_doctor for diagnostics.",
  });
}
