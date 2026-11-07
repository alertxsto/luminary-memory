export type RememberSource = { kind: "operator" } | { kind: "native_user"; quote: string };

/** A model-proposed quote is evidence only when present in real native user input. */
export function nativeUserSource(quote: unknown, user: string): RememberSource | undefined {
  if (typeof quote !== "string") return;
  const bounded = quote.trim();
  if (!bounded || Buffer.byteLength(bounded, "utf8") > 4096 || !user.includes(bounded)) return;
  return { kind: "native_user", quote: bounded };
}

/** Never inherit provenance from a previous call or accept it from tool JSON. */
export function bridgeEnvironment(agent: string, workspace: string, session_id: string, source?: RememberSource): NodeJS.ProcessEnv {
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => key.toUpperCase() !== "LUMINARY_BRIDGE_SOURCE"));
  env.LUMINARY_BRIDGE_SOURCE = source ? JSON.stringify({ ...source, agent, workspace, session_id }) : "";
  return { ...env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" };
}
