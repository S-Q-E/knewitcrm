import { useState } from "react";
import type { ReactNode } from "react";

import type { Deal } from "@/api/deals";
import {
  useContact,
  useCustomFields,
  useDeal,
  useMoveDeal,
  usePipelines,
  useSetDealTags,
  useTags,
  useUnlockDeal,
  useUpdateDeal,
  useUsersLite,
} from "@/api/deals";
import { useCreateTask } from "@/api/timeline";
import { Timeline } from "@/components/deals/timeline";
import { LostReasonModal, NoteModal, WonConfirmModal } from "@/components/deals/modals";
import { useToast, toastError } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isoToLocalInput, localInputToIso } from "@/lib/datetime";

const BOT_FIELDS: { key: string; label: string }[] = [
  { key: "direction", label: "Направление" },
  { key: "goal", label: "Цель" },
  { key: "experience_level", label: "Опыт" },
  { key: "preferred_format", label: "Формат" },
  { key: "preferred_time", label: "Время" },
  { key: "last_objection", label: "Возражение" },
];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-600 dark:text-slate-300">{label}</span>
      {children}
    </label>
  );
}

function CustomValueInput({
  field,
  value,
  onChange,
}: {
  field: { key: string; label: string; type: string; options: unknown };
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  if (field.type === "bool") {
    return (
      <input
        type="checkbox"
        checked={value === true}
        onChange={(event) => onChange(event.target.checked)}
      />
    );
  }
  if (field.type === "select" && Array.isArray(field.options)) {
    return (
      <select
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value || null)}
        className="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
      >
        <option value="">—</option>
        {field.options.map((option) => (
          <option key={String(option)} value={String(option)}>
            {String(option)}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === "multiselect" && Array.isArray(field.options)) {
    const selected = Array.isArray(value) ? value.map(String) : [];
    return (
      <div className="flex flex-wrap gap-2">
        {field.options.map((option) => {
          const text = String(option);
          const on = selected.includes(text);
          return (
            <button
              key={text}
              type="button"
              onClick={() =>
                onChange(on ? selected.filter((item) => item !== text) : [...selected, text])
              }
              className={
                on
                  ? "rounded-full bg-slate-900 px-2 py-0.5 text-xs text-white dark:bg-slate-100 dark:text-slate-900"
                  : "rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800"
              }
            >
              {text}
            </button>
          );
        })}
      </div>
    );
  }
  if (field.type === "number") {
    return (
      <Input
        type="number"
        value={typeof value === "number" ? value : ""}
        onChange={(event) =>
          onChange(event.target.value === "" ? null : Number(event.target.value))
        }
      />
    );
  }
  if (field.type === "date") {
    return (
      <Input
        type="date"
        value={typeof value === "string" ? value.slice(0, 10) : ""}
        onChange={(event) => onChange(event.target.value || null)}
      />
    );
  }
  return (
    <Input
      value={typeof value === "string" ? value : ""}
      onChange={(event) => onChange(event.target.value || null)}
    />
  );
}

export function DealDetail({ dealId, onClose }: { dealId: string; onClose?: () => void }) {
  const { push } = useToast();
  const dealQuery = useDeal(dealId);
  const deal = dealQuery.data ?? null;
  const contactQuery = useContact(deal?.contact_id ?? null);
  const contact = contactQuery.data ?? null;
  const users = useUsersLite();
  const tags = useTags();
  const dealFields = useCustomFields("deal");
  const pipelines = usePipelines();

  const updateDeal = useUpdateDeal();
  const moveDeal = useMoveDeal();
  const unlockDeal = useUnlockDeal();
  const setTags = useSetDealTags();
  const createTask = useCreateTask();

  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [customDraft, setCustomDraft] = useState<Record<string, unknown> | null>(null);
  const [showLost, setShowLost] = useState(false);
  const [showWon, setShowWon] = useState(false);
  const [showNote, setShowNote] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDue, setTaskDue] = useState("");

  if (dealQuery.isPending) {
    return (
      <div className="flex flex-col gap-2" aria-label="Загрузка сделки">
        {[0, 1, 2, 3].map((index) => (
          <div
            key={index}
            className="h-14 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800"
          />
        ))}
      </div>
    );
  }
  if (dealQuery.isError || !deal) {
    return (
      <p className="text-sm text-red-600">
        Не удалось загрузить сделку.{" "}
        <button type="button" className="underline" onClick={() => dealQuery.refetch()}>
          Повторить
        </button>
      </p>
    );
  }

  const edit = <K extends keyof Deal>(key: K, value: Deal[K]) =>
    setDraft((prev) => ({ ...(prev ?? {}), [key]: value }));

  const saveDraft = async () => {
    if (!draft && !customDraft) {
      return;
    }
    try {
      const patch: Record<string, unknown> = { ...(draft ?? {}) };
      if (customDraft) {
        patch.custom = { ...deal.custom, ...customDraft };
      }
      await updateDeal.mutateAsync({ id: deal.id, patch });
      setDraft(null);
      setCustomDraft(null);
      push({ title: "Сохранено", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  const changeStage = (stageId: string) => {
    moveDeal.mutate(
      { id: deal.id, stage_id: stageId },
      { onError: (error) => toastError(push, error) },
    );
  };

  const closeLost = (reasonId: string) => {
    setShowLost(false);
    const lostStage = pipelines.data
      ?.find((item) => item.id === deal.pipeline_id)
      ?.stages.find((stage) => stage.kind === "lost");
    if (!lostStage) {
      push({ title: "Ошибка", description: "Нет lost-стадии в воронке", variant: "error" });
      return;
    }
    moveDeal.mutate(
      { id: deal.id, stage_id: lostStage.id, lost_reason_id: reasonId },
      { onError: (error) => toastError(push, error) },
    );
  };

  const addTask = async () => {
    if (!taskTitle.trim()) {
      return;
    }
    try {
      await createTask.mutateAsync({
        deal_id: deal.id,
        title: taskTitle.trim(),
        due_at: localInputToIso(taskDue),
      });
      setTaskTitle("");
      setTaskDue("");
      push({ title: "Задача создана", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  const toggleTag = (tagId: string) => {
    const has = deal.tags.some((tag) => tag.id === tagId);
    const next = has
      ? deal.tags.filter((tag) => tag.id !== tagId).map((tag) => tag.id)
      : [...deal.tags.map((tag) => tag.id), tagId];
    setTags.mutate({ id: deal.id, tag_ids: next }, { onError: (error) => toastError(push, error) });
  };

  const dirty = draft !== null || customDraft !== null;

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="flex w-full flex-col gap-3 lg:max-w-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">{contact?.name ?? "Сделка"}</h2>
          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose}>
              Закрыть
            </Button>
          )}
        </div>

        <Field label="Название">
          <Input
            defaultValue={deal.title}
            key={`title-${deal.updated_at}`}
            onChange={(event) => edit("title", event.target.value)}
          />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Сумма, ₸">
            <Input
              type="number"
              min="0"
              defaultValue={deal.amount ?? ""}
              key={`amount-${deal.updated_at}`}
              onChange={(event) =>
                edit("amount", event.target.value === "" ? null : Number(event.target.value))
              }
            />
          </Field>
          <Field label="Пробный урок">
            <Input
              type="datetime-local"
              defaultValue={isoToLocalInput(deal.trial_at)}
              key={`trial-${deal.updated_at}`}
              onChange={(event) => edit("trial_at", localInputToIso(event.target.value))}
            />
          </Field>
        </div>
        <Field label="Ответственный">
          <select
            value={(draft?.owner_id as string) ?? deal.owner_id ?? ""}
            onChange={(event) => edit("owner_id", event.target.value || null)}
            className="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Без ответственного</option>
            {users.data?.items.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Стадия">
          <StageSelect deal={deal} onChange={changeStage} />
        </Field>

        <div>
          <p className="mb-1 text-sm font-medium text-slate-600 dark:text-slate-300">Теги</p>
          <div className="flex flex-wrap gap-1">
            {tags.data?.items.map((tag) => {
              const on = deal.tags.some((item) => item.id === tag.id);
              return (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => toggleTag(tag.id)}
                  className={
                    on
                      ? "rounded-full bg-slate-900 px-2 py-0.5 text-xs text-white dark:bg-slate-100 dark:text-slate-900"
                      : "rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800"
                  }
                >
                  {tag.name}
                </button>
              );
            })}
          </div>
        </div>

        {dealFields.data && dealFields.data.items.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
              Дополнительные поля
            </p>
            {dealFields.data.items.map((field) => (
              <Field key={field.id} label={field.label + (field.required ? " *" : "")}>
                <CustomValueInput
                  field={field}
                  value={
                    customDraft?.[field.key] ?? (deal.custom as Record<string, unknown>)[field.key]
                  }
                  onChange={(value) =>
                    setCustomDraft((prev) => ({ ...(prev ?? {}), [field.key]: value }))
                  }
                />
              </Field>
            ))}
          </div>
        )}

        {dirty && (
          <Button onClick={() => void saveDraft()} disabled={updateDeal.isPending}>
            Сохранить изменения
          </Button>
        )}

        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setShowWon(true)}>
            Выиграно
          </Button>
          <Button size="sm" variant="danger" onClick={() => setShowLost(true)}>
            Проиграно
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setShowNote(true)}>
            Заметка
          </Button>
          {deal.stage_locked && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() =>
                unlockDeal.mutate(deal.id, { onError: (error) => toastError(push, error) })
              }
            >
              Вернуть управление боту
            </Button>
          )}
        </div>

        <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-900">
          <p className="mb-1 font-medium">Данные от бота</p>
          <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
            {BOT_FIELDS.map((field) => (
              <div key={field.key} className="flex flex-col">
                <dt className="text-slate-500">{field.label}</dt>
                <dd>
                  {String(
                    (contact?.custom as Record<string, unknown> | undefined)?.[field.key] ?? "—",
                  )}
                </dd>
              </div>
            ))}
          </dl>
          {contact?.whatsapp_id && (
            <p className="mt-1 text-xs text-slate-500">WhatsApp: {contact.whatsapp_id}</p>
          )}
        </div>
      </div>

      <div className="min-w-0 flex-1">
        <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">Лента</h3>
        <Timeline dealId={deal.id} />
        <div className="mt-3 flex flex-col gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <p className="text-sm font-medium">Быстрая задача</p>
          <div className="flex flex-col gap-2 md:flex-row">
            <Input
              value={taskTitle}
              onChange={(event) => setTaskTitle(event.target.value)}
              placeholder="Позвонить клиенту"
              className="flex-1"
            />
            <Input
              type="datetime-local"
              value={taskDue}
              onChange={(event) => setTaskDue(event.target.value)}
              className="md:w-52"
            />
            <Button
              size="sm"
              onClick={() => void addTask()}
              disabled={createTask.isPending || !taskTitle.trim()}
            >
              Добавить
            </Button>
          </div>
        </div>
      </div>

      {showLost && <LostReasonModal onClose={() => setShowLost(false)} onConfirm={closeLost} />}
      {showWon && (
        <WonConfirmModal
          onClose={() => setShowWon(false)}
          onConfirm={() => {
            setShowWon(false);
            updateDeal.mutate(
              { id: deal.id, patch: { status: "won" } },
              { onError: (error) => toastError(push, error) },
            );
          }}
        />
      )}
      {showNote && <NoteModal deal={deal} onClose={() => setShowNote(false)} />}
    </div>
  );
}

function StageSelect({ deal, onChange }: { deal: Deal; onChange: (stageId: string) => void }) {
  return (
    <select
      value={deal.stage_id}
      onChange={(event) => onChange(event.target.value)}
      className="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
    >
      <StageOptions pipelineId={deal.pipeline_id} />
    </select>
  );
}

function StageOptions({ pipelineId }: { pipelineId: string }) {
  const pipelines = usePipelines();
  const stages = pipelines.data?.find((item) => item.id === pipelineId)?.stages ?? [];
  return (
    <>
      {stages.map((stage) => (
        <option key={stage.id} value={stage.id}>
          {stage.name}
        </option>
      ))}
    </>
  );
}
