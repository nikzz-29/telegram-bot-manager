import React from "react";

/**
 * The first paint while Telegram's launch data is exchanged for a session.
 * This is intentionally self-contained: it has no timers and disappears as
 * soon as the session state changes, so it never delays authentication.
 */
export function LaunchScreen({ label }: { label: string }): React.JSX.Element {
  return (
    <main className="launch-screen" aria-label={label}>
      <div className="launch-lockup" aria-hidden="true">
        <div className="launch-logo-stage">
          <div className="launch-logo-frame">
            <span className="launch-grid" aria-hidden="true">
              <i /><i /><i /><i /><i /><i /><i /><i /><i />
            </span>
          </div>
        </div>
        <div className="launch-wordmark">BOT MANAGER</div>
        <div className="launch-progress" aria-hidden="true">
          <span />
        </div>
      </div>
      <span className="sr-only">{label}</span>
    </main>
  );
}
