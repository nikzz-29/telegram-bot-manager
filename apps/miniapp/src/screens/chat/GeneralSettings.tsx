/**
 * Chat language and timezone — the two settings that belong to no module.
 *
 * DECISION: both fields save on blur rather than behind a Save button. There are
 * two of them, each independently valid, and a panel that loses an edit because
 * the user swiped away without noticing a button is worse than one extra PATCH.
 */
import React, { useEffect, useState } from "react";
import type { ChatDetail } from "../../api/client";
import { Card, PickerRow, Row, VALUE_INPUT } from "../../components/ui";
import { useT } from "../../i18n/I18nProvider";
import { useUpdateChat } from "../../hooks/queries";
import { hapticResult } from "../../telegram/sdk";

export function GeneralSettings({
  chat,
  locales,
}: {
  chat: ChatDetail;
  locales: readonly string[];
}): React.JSX.Element {
  const t = useT();
  const update = useUpdateChat(chat.id);
  const [timezone, setTimezone] = useState(chat.timezone ?? "UTC");

  // A refetch (or another admin's edit) is the source of truth, not our draft.
  useEffect(() => {
    setTimezone(chat.timezone ?? "UTC");
  }, [chat.timezone]);

  const commitTimezone = (): void => {
    const next = timezone.trim();
    if (next === "" || next === chat.timezone) {
      setTimezone(chat.timezone ?? "UTC");
      return;
    }
    update.mutate(
      { timezone: next },
      {
        onSuccess: () => hapticResult(true),
        onError: () => {
          hapticResult(false);
          // The API rejected the zone name; show what the server still holds.
          setTimezone(chat.timezone ?? "UTC");
        },
      },
    );
  };

  return (
    <Card>
      {/*
       * DECISION: the language row discloses its options in place. It was the
       * last native `<select>` in the panel — the one control that renders in the
       * OS's own chrome instead of Telegram's, and the one that gave no haptic
       * because the press never reached our code. `PickerRow` also states the
       * chosen locale in a full word at rest, where the select's own text was the
       * same word rendered in a different font two pixels to the left.
       */}
      <PickerRow
        title={t("chat-language")}
        value={chat.language ?? "ru"}
        disabled={update.isPending}
        unsetLabel={t("field-unset")}
        options={locales.map((code) => ({ value: code, label: t(`locale-${code}`) }))}
        onPick={(code) => update.mutate({ language: code })}
      />
      <Row
        title={t("chat-timezone")}
        subtitle={t("chat-timezone-hint")}
        right={
          <input
            className={`w-32 ${VALUE_INPUT}`}
            value={timezone}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            disabled={update.isPending}
            onChange={(event) => setTimezone(event.target.value)}
            onBlur={commitTimezone}
          />
        }
      />
    </Card>
  );
}
