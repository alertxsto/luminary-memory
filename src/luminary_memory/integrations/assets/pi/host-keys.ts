// Map the host's injected keybindings onto the inspector's small key set.
//
// Pi's own documentation uses `keybindings.matches(data, "tui.select.down")`
// inside custom components; `matchesKey` from the TUI package uses different
// names across releases. The host manager therefore decides first.
export type HostKeybindings = { matches(data: string, action: string): boolean };

const BINDINGS: Record<string, string[]> = {
  up: ["tui.select.up"],
  down: ["tui.select.down"],
  pageUp: ["tui.select.pageUp", "tui.select.page-up"],
  pageDown: ["tui.select.pageDown", "tui.select.page-down"],
  enter: ["tui.select.confirm"],
  escape: ["tui.select.cancel"],
  "ctrl+c": ["tui.select.cancel"],
  tab: ["tui.select.next", "tui.tab.next"],
  "shift+tab": ["tui.select.previous", "tui.tab.previous"],
  right: ["tui.select.next"],
  left: ["tui.select.previous"],
};

/** True when this input matches one of the host actions bound to `key`. */
export function createHostKeyMatcher(
  keybindings: HostKeybindings,
  fallback?: (data: string, key: string) => boolean,
): (data: string, key: string) => boolean {
  return (data, key) => {
    for (const action of BINDINGS[key] ?? []) {
      try {
        if (keybindings.matches(data, action)) return true;
      } catch {
        // An unknown action on an older host must not break navigation.
      }
    }
    return fallback ? fallback(data, key) : false;
  };
}
