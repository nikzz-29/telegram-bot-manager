/**
 * Chat language and timezone — the two settings that belong to no module.
 *
 * DECISION: both fields save on blur rather than behind a Save button. There are
 * two of them, each independently valid, and a panel that loses an edit because
 * the user swiped away without noticing a button is worse than one extra PATCH.
 */
import React, { useEffect, useState } from "react";
import type { ChatDetail } from "../../api/client";
import { Card, Row } from "../../components/ui";
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
      <Row
        title={t("chat-language")}
        right={
          <select
            className="bg-transparent text-row text-link outline-none disabled:opacity-50"
            value={chat.language ?? "ru"}
            disabled={update.isPending}
            onChange={(event) => update.mutate({ language: event.target.value })}
          >
            {locales.map((code) => (
              <option key={code} value={code}>
                {t(`locale-${code}`)}
              </option>
            ))}
          </select>
        }
      />
      <Row
        title={t("chat-timezone")}
        subtitle={t("chat-timezone-hint")}
        right={
          <input
            className="w-32 bg-transparent text-right text-row text-link outline-none disabled:opacity-50"
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
