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
  EmptyState,
  ErrorState,
  Header,
  Icon,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
  Toggle,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useMeta, useModules, useResetModule, useSaveModule } from "../hooks/queries";
import { useDiscardGuard } from "../hooks/useDiscardGuard";
import { useNavigation } from "../navigation";
import { FieldInput, fieldInvalid, groupFields, groupKey } from "../settings/fields";
import { type Field, fieldsOf, readPath, writePath } from "../settings/schema";
import { askConfirmation, hapticResult } from "../telegram/sdk";

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
  const navigation = useNavigation();
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

  /*
   * Above the early returns: hooks cannot be called after one. `draft` is null
   * until the first edit, which makes it the dirty flag as well as the value.
   *
   * No `onClose` — this editor is the whole screen rather than a panel inside a
   * list, so agreeing to lose the draft means leaving the route.
   */
  useDiscardGuard({ dirty: draft !== null });

  if (meta.isPending || modules.isPending) {
    return (
      <Screen>
        {/*
         * DECISION: a row skeleton rather than the spinner, even though this
         * screen is a form. What arrives is a stack of grouped cells — the form
         * is spelled as a settings list, not as labelled inputs — so rows are an
         * honest description of the shape, and the page does not jump when the
         * schema resolves.
         */}
        <SkeletonRows count={5} />
      </Screen>
    );
  }
  // A failed query also has undefined `data`, so this has to come before the
  // not-found check below — otherwise a dropped connection is reported as a
  // module that does not exist, and the retry the user needs is never offered.
  const failure = meta.isError ? meta.error : modules.isError ? modules.error : null;
  if (failure !== null) {
    return (
      <Screen>
        <ErrorState
          message={failure.message}
          onRetry={() => {
            void meta.refetch();
            void modules.refetch();
          }}
        />
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
  const plan = t(`plan-${spec.required_plan}`);
  // Save refuses a draft the schema's own constraints reject — a number outside
  // its bounds, a string against its pattern, an entry of a repeating group with
  // a required field left blank. Without this the field states what is wrong and
  // the button ships the value anyway: the API answers 422 and the panel reports
  // it as a bare message, one round trip away from the row that caused it.
  const invalid = groups.some(([, fields]) =>
    fields.some((field) => fieldInvalid(field, readPath(config, field.path))),
  );

  return (
    <Screen>
      {/* The registry names the glyph server-side, so a module added after this
          build ships still opens under its own icon. */}
      <Header
        title={t(spec.title_key)}
        subtitle={t(spec.description_key)}
        icon={spec.icon}
      />

      {/*
       * DECISION: the master switch gets a card to itself, above every group. It
       * used to be the second row of a two-row list, spelled identically to the
       * settings it governs — but turning the module off makes the whole rest of
       * the screen moot, so it has to read as the decision the others hang from
       * rather than as one more of them.
       */}
      <Card>
        <Row
          title={t("module-enabled")}
          right={
            <Toggle
              checked={state.enabled}
              label={t("module-enabled")}
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
          {/*
           * DECISION: a locked module is drawn as a state, not as a grey row of
           * text. Nothing has failed here — the module exists and this chat's
           * plan does not reach it — so it takes the shield and a centred
           * sentence, the shape of a door, rather than the shape of an error.
           *
           * DECISION: the upsell is a button that opens billing. It was left as a
           * plain sentence on the grounds that this screen could not navigate —
           * which was never true: the `billing` route takes the `chatId` already
           * in props. So the one screen that states a plan is too low was also
           * the one screen offering no way to raise it, and "Upgrade to Pro" sat
           * there as an instruction with nothing behind it.
           */}
          <EmptyState icon="shield" text={t("module-locked", { plan })} />
          <div className="px-6 pb-8">
            <Button onClick={() => navigation.push({ name: "billing", chatId })}>
              {t("module-locked-cta", { plan })}
            </Button>
          </div>
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
              disabled={!dirty || invalid || save.isPending}
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
              <p className="text-center text-label text-destructive">{save.error.message}</p>
            )}
          </div>

          {/*
           * DECISION: reset sits in its own block below the save stack instead of
           * directly under it. It discards every field on the screen at once, and
           * a destructive control one thumb-width from the primary one is exactly
           * how that gets tapped by mistake.
           */}
          <div className="mt-8">
            <Button
              variant="destructive"
              disabled={reset.isPending}
              onClick={async () => {
                const confirmed = await askConfirmation({
                  message: t("module-reset-confirm"),
                  confirmText: t("module-reset"),
                  cancelText: t("panel-cancel"),
                  destructive: true,
                });
                if (!confirmed) {
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
              <span className="inline-flex items-center justify-center gap-2">
                <Icon name="trash" size={18} />
                {t("module-reset")}
              </span>
            </Button>
          </div>
        </>
      )}
    </Screen>
  );
}
