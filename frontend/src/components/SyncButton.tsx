import { Icon } from "./icons";

/** Explicit sync-flow state: Sync -> Syncing… -> Refresh (or back to Sync on
 * error). Owned by App so it survives route changes and layout-mode switches;
 * a page reload (the Refresh action itself) resets it to idle by design. */
export type SyncState = "idle" | "syncing" | "complete" | "error";

export function SyncButton({
  state,
  onSync,
  fullWidth = false,
}: {
  state: SyncState;
  onSync: () => void;
  fullWidth?: boolean;
}) {
  const syncing = state === "syncing";
  const label = syncing ? "Syncing…" : state === "complete" ? "Refresh" : "Sync now";
  return (
    <button
      className={`btn primary ${fullWidth ? "m-btn-full" : ""}`}
      onClick={() => (state === "complete" ? window.location.reload() : onSync())}
      disabled={syncing}
      aria-busy={syncing}
    >
      {syncing ? (
        <span className="spinner-sm" aria-hidden="true" />
      ) : (
        <Icon name="sync" size={15} />
      )}
      {label}
    </button>
  );
}

/** Live status line under the button. aria-live so screen readers hear the
 * completion/error without focus moving. */
export function SyncStatusLine({ state, message }: { state: SyncState; message: string | null }) {
  if (!message) return null;
  return (
    <div role="status" aria-live="polite" className={`sync-status ${state === "error" ? "err" : ""}`}>
      {message}
    </div>
  );
}
