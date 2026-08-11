/**
 * The Telegram client, reduced to the four things the panel needs from it.
 *
 * `initData` (who launched us), the back button (how a Mini App navigates), the
 * main button (how it confirms), and haptics. Everything else the SDK offers is
 * left alone.
 *
 * DECISION: every call is guarded by `isAvailable()` and the module degrades to
 * no-ops outside Telegram. The panel has to run in a plain browser during
 * development — that is the only way to use React devtools against it — and a
 * hard dependency on the bridge would make `pnpm dev` a blank screen.
 */
import {
  backButton,
  hapticFeedback,
  init,
  invoice,
  miniApp,
  openLink,
  popup,
  retrieveRawInitData,
  viewport,
} from "@telegram-apps/sdk-react";

let started = false;

/**
 * Bring the SDK up. Safe to call twice; safe to call outside Telegram.
 *
 * Returns whether we are actually inside a Telegram client, which is what
 * decides between the real launch flow and the dev fallback.
 */
export function initTelegram(): boolean {
  if (started) {
    return isInsideTelegram();
  }
  started = true;
  try {
    init();
  } catch {
    return false;
  }
  if (miniApp.mountSync.isAvailable()) {
    miniApp.mountSync();
    // Tell Telegram the webview has painted, so it can drop its own loader.
    if (miniApp.ready.isAvailable()) {
      miniApp.ready();
    }
  }
  if (viewport.mount.isAvailable()) {
    // Best-effort: the panel is a scrolling list and works at any height, so a
    // viewport that never resolves is not worth blocking the render on.
    void viewport.mount().catch(() => undefined);
  }
  if (viewport.expand.isAvailable()) {
    viewport.expand();
  }
  return isInsideTelegram();
}

export function isInsideTelegram(): boolean {
  return miniApp.isMounted();
}

/**
 * The raw launch string, to be traded for a session token.
 *
 * Returned verbatim — the signature covers these exact bytes in this exact
 * order, so any parsing and re-encoding on the way to the API would break it.
 */
export function launchInitData(): string | null {
  try {
    return retrieveRawInitData() ?? null;
  } catch {
    return null;
  }
}

/**
 * Point Telegram's own back button at `handler`, or hide it when null.
 *
 * DECISION: the panel drives the native back button rather than drawing its own.
 * Telegram users reach for the client's chrome, and on Android the hardware back
 * gesture is wired to this same button — a custom control would close the whole
 * Mini App instead of going up one screen.
 */
export function setBackHandler(handler: (() => void) | null): () => void {
  if (!backButton.mount.isAvailable()) {
    return () => undefined;
  }
  backButton.mount();
  if (handler === null) {
    backButton.hide();
    return () => undefined;
  }
  backButton.show();
  const off = backButton.onClick(handler);
  return () => {
    off();
    backButton.hide();
  };
}

/** A short tap on save, delete and other committed actions. */
export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  if (hapticFeedback.impactOccurred.isAvailable()) {
    hapticFeedback.impactOccurred(style);
  }
}

/** The success/failure buzz, for anything the user is waiting on. */
export function hapticResult(ok: boolean): void {
  if (hapticFeedback.notificationOccurred.isAvailable()) {
    hapticFeedback.notificationOccurred(ok ? "success" : "error");
  }
}

/** What became of a checkout: Telegram's own status, or how we failed to start. */
export type InvoiceOutcome = "paid" | "cancelled" | "failed" | "unsupported";

/**
 * Open a payment link and wait for the client to say how it ended.
 *
 * DECISION: Stars invoices go through `invoice.open`, which keeps the payment
 * sheet inside Telegram and resolves with a status — that is how the panel knows
 * to refetch the plan without polling. A CryptoBot URL is not a Telegram invoice,
 * so it opens as a link and the outcome is unknowable from here; the caller
 * refetches on return instead.
 */
export async function openInvoice(url: string): Promise<InvoiceOutcome> {
  if (!invoice.open.isAvailable()) {
    return "unsupported";
  }
  try {
    const status = await invoice.open(url, "url");
    return status === "paid" ? "paid" : status === "cancelled" ? "cancelled" : "failed";
  } catch {
    return "failed";
  }
}

/** What to put in a confirmation popup. Both labels come from the panel's own
 * catalogue rather than from Telegram's `cancel` button type: the panel has its
 * own locale switcher, and a client set to a different language would otherwise
 * answer an English question with a Russian button. */
export interface ConfirmRequest {
  message: string;
  confirmText: string;
  cancelText: string;
  title?: string;
  /** Paints the confirm button red. On for anything that destroys data. */
  destructive?: boolean;
}

// Telegram's own caps. A longer string is rejected outright, which would turn a
// too-wordy translation into a delete button that silently does nothing.
const POPUP_TITLE_LIMIT = 64;
const POPUP_MESSAGE_LIMIT = 256;
const CONFIRM_BUTTON_ID = "confirm";

/**
 * Ask the user to confirm, and resolve to what they chose.
 *
 * DECISION: a native popup rather than `window.confirm`. A Mini App is a webview
 * whose host owns the modal layer — several clients suppress the browser dialog
 * outright, and `window.confirm` returning `false` unprompted reads as "the user
 * said no" to code that cannot tell the difference. `popup.show` is answered by
 * the user or not at all.
 *
 * Dismissing the popup — tapping outside it or the close chevron — resolves to
 * `null`, which is a no, same as the cancel button.
 */
export async function askConfirmation(request: ConfirmRequest): Promise<boolean> {
  if (!popup.show.isAvailable()) {
    // A plain browser during development, or a client older than Mini Apps 6.2.
    // The browser dialog is the only thing left, and outside Telegram it works.
    return window.confirm(request.message);
  }
  try {
    const pressed = await popup.show({
      title: request.title?.slice(0, POPUP_TITLE_LIMIT),
      message: request.message.slice(0, POPUP_MESSAGE_LIMIT),
      buttons: [
        { id: "cancel", type: "default", text: request.cancelText },
        {
          id: CONFIRM_BUTTON_ID,
          type: request.destructive === true ? "destructive" : "default",
          text: request.confirmText,
        },
      ],
    });
    return pressed === CONFIRM_BUTTON_ID;
  } catch {
    // A popup already on screen, or a client that refused this one. Treating
    // either as a yes would delete something nobody agreed to.
    return false;
  }
}

/** Open an external URL without closing the panel. */
export function openExternal(url: string): boolean {
  if (!openLink.isAvailable()) {
    return false;
  }
  openLink(url);
  return true;
}
