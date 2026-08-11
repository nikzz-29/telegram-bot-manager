/**
 * "You have unsaved changes" for Telegram's back button.
 *
 * DECISION: one hook rather than the check inlined at each editor. Four editors
 * ask this question, and the failure it prevents is silent — a tap on a button
 * the panel does not own, and the draft is gone with no undo. Spelled once, the
 * four cannot drift into three that ask and one that does not.
 *
 * DECISION: only a *dirty* editor asks. A popup on the way out of an untouched
 * form trains people to dismiss popups, which is exactly the reflex that loses
 * the draft in the editor next door.
 */
import { useCallback } from "react";
import { useT } from "../i18n/I18nProvider";
import { useBackIntercept } from "../navigation";
import { askConfirmation } from "../telegram/sdk";

export interface DiscardGuard {
  /** Whether the editor holds changes that leaving would lose. */
  dirty: boolean;
  /**
   * Close the editor. Called once the user has agreed to lose the draft.
   *
   * Omit for an editor that *is* the screen: with nothing to close, the back
   * button pops the route instead, which is that editor's way out.
   */
  onClose?: () => void;
}

/** Ask before the back button discards a draft. Also returns the same check for
 * an in-screen Cancel button, so both exits behave alike. */
export function useDiscardGuard({ dirty, onClose }: DiscardGuard): () => Promise<boolean> {
  const t = useT();

  const confirmDiscard = useCallback(async (): Promise<boolean> => {
    if (!dirty) {
      return true;
    }
    return askConfirmation({
      message: t("panel-discard"),
      confirmText: t("panel-discard-leave"),
      cancelText: t("panel-discard-stay"),
      // Destructive: what is being confirmed is the loss of the draft, not the
      // navigation. Telegram paints that button red, which is the honest colour.
      destructive: true,
    });
  }, [dirty, t]);

  useBackIntercept(
    useCallback(async () => {
      if (!(await confirmDiscard())) {
        return false;
      }
      if (onClose === undefined) {
        // Nothing to close: let the pop take the whole screen.
        return true;
      }
      onClose();
      // Handled here — the list this editor replaced is one level shallower than
      // the route, so popping as well would leave the screen entirely.
      return false;
    }, [confirmDiscard, onClose]),
  );

  return confirmDiscard;
}
