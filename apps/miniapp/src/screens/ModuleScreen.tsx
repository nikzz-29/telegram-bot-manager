/**
 * One module's settings, generated from the schema `/api/meta` ships.
 *
 * DECISION: edits collect in a local draft and go out on one Save. Unlike the two
 * general settings, a module screen holds dozens of interdependent fields — a
 * warn limit and its punishment are one thought — and PATCHing on every keypress
 * would both flood the API and let a half-typed number reach the bot.
 */
import React, { useMemo, useState } from "react";
import {
  Button,
  Card,
  ErrorState,
  Row,
  Screen,
  SectionTitle,
  Spinner,
  Toggle,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useMeta, useModules, useResetModule, useSaveModule } from "../hooks/queries";
import { FieldInput, groupFields, groupKey } from "../settings/fields";
import { type Field, fieldsOf, readPath, writePath } from "../settings/schema";
import { hapticResult } from "../telegram/sdk";

/** Nested objects render as part of their parent group, not as a row. */
function flatten(fields: readonly Field[]): Field[] {
  return fields.flatMap((field) =>
    field.kind === "nested" ? flatten(field.children ?? []) : [field],
  );
}

export function ModuleScreen({
  chatId,
  module,
}: {
  chatId: number;
  module: string;
}): React.JSX.Element {
  const t = useT();
  const meta = useMeta();
  const modules = useModules(chatId);
  const save = useSaveModule(chatId);
  const reset = useResetModule(chatId);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);

  const spec = meta.data?.modules?.find((entry) => entry.name === module);
  const state = modules.data?.find((entry) => entry.module === module);

  const groups = useMemo(
    () => groupFields(flatten(fieldsOf(spec?.config_schema ?? {}))),
    [spec?.config_schema],
  );

  if (meta.isPending || modules.isPending) {
    return (
      <Screen>
        <Spinner />
      </Screen>
    );
  }
  if (spec === undefined || state === undefined) {
    return (
      <Screen>
        <ErrorState message={t("error-not-found")} />
      </Screen>
    );
  }

  const config = draft ?? state.config;
  const dirty = draft !== null;
  const locked = !state.available;

  return (
    <Screen>
      <SectionTitle>{t(spec.title_key)}</SectionTitle>
      <Card>
        <Row title={t(spec.description_key)} />
        <Row
          title={t("module-enabled")}
          right={
            <Toggle
              checked={state.enabled}
              disabled={locked || spec.mandatory || save.isPending}
              onChange={(enabled) =>
                save.mutate(
                  { module, enabled },
                  { onSuccess: () => hapticResult(true), onError: () => hapticResult(false) },
                )
              }
            />
          }
        />
      </Card>

      {locked ? (
        <Card className="mt-4">
          <Row
            title={t("module-locked", { plan: t(`plan-${spec.required_plan}`) })}
            subtitle={t("module-locked-cta", { plan: t(`plan-${spec.required_plan}`) })}
          />
        </Card>
      ) : (
        <>
          {groups.map(([group, fields]) => (
            <React.Fragment key={group}>
              <SectionTitle>{t(groupKey(group))}</SectionTitle>
              <Card>
                {fields.map((field) => (
                  <FieldInput
                    key={field.path}
                    field={field}
                    value={readPath(config, field.path)}
                    disabled={save.isPending}
                    onChange={(value) => setDraft(writePath(config, field.path, value))}
                  />
                ))}
              </Card>
            </React.Fragment>
          ))}

          <div className="mt-6 space-y-3">
            <Button
              disabled={!dirty || save.isPending}
              onClick={() =>
                save.mutate(
                  { module, config },
                  {
                    onSuccess: () => {
                      // Drop the draft so the refetched config becomes the truth.
                      setDraft(null);
                      hapticResult(true);
                    },
                    onError: () => hapticResult(false),
                  },
                )
              }
            >
              {save.isPending ? t("panel-saving") : t("panel-save")}
            </Button>
            {save.isError && (
              <p className="text-center text-[13px] text-destructive">
                {save.error.message}
              </p>
            )}
            <Button
              variant="destructive"
              disabled={reset.isPending}
              onClick={() => {
                if (!window.confirm(t("module-reset-confirm"))) {
                  return;
                }
                reset.mutate(module, {
                  onSuccess: () => {
                    setDraft(null);
                    hapticResult(true);
                  },
                  onError: () => hapticResult(false),
                });
              }}
            >
              {t("module-reset")}
            </Button>
          </div>
        </>
      )}
    </Screen>
  );
}
