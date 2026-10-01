import { DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMemo, useState } from "react";

import { usePipelines, useTags } from "@/api/deals";
import type { CustomField, Pipeline, QuickReply, Stage } from "@/api/settings";
import {
  useAllLostReasons,
  useBotStages,
  useCreateCustomField,
  useCreateLostReason,
  useCreatePipeline,
  useCreateQuickReply,
  useCreateStage,
  useCreateTag,
  useCustomFieldsAdmin,
  useDeleteCustomField,
  useDeleteLostReason,
  useDeletePipeline,
  useDeleteQuickReply,
  useDeleteStage,
  useDeleteTag,
  useReorderStages,
  useUpdateCustomField,
  useUpdateLostReason,
  useUpdatePipeline,
  useUpdateQuickReply,
  useUpdateStage,
  useUpdateTag,
} from "@/api/settings";
import { useQuickReplies } from "@/api/timeline";
import { toastError, useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FieldLabel, ModalShell, inputClass } from "@/pages/settings";
import { cn } from "@/lib/utils";

const KIND_LABELS: Record<Stage["kind"], string> = {
  open: "Открытая",
  won: "Выиграно",
  lost: "Проиграно",
};

function Card({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

// Pipelines + stages

function SortableStageRow({
  stage,
  onEdit,
  onDelete,
}: {
  stage: Stage;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: stage.id,
  });
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex items-center gap-2 rounded-md border border-slate-100 bg-white px-2 py-1.5 text-sm dark:border-slate-800 dark:bg-slate-900",
        isDragging && "opacity-60",
      )}
    >
      <button
        type="button"
        aria-label={`Перетащить стадию ${stage.name}`}
        className="cursor-grab touch-none px-1 text-slate-400"
        {...attributes}
        {...listeners}
      >
        ⋮⋮
      </button>
      <span
        className="h-3 w-3 shrink-0 rounded-full"
        style={{ backgroundColor: stage.color }}
        title={stage.color}
      />
      <span className="min-w-0 flex-1 truncate font-medium">{stage.name}</span>
      <span className="hidden text-xs text-slate-500 md:inline">{KIND_LABELS[stage.kind]}</span>
      {stage.bot_stage_key && (
        <span className="hidden rounded bg-sky-100 px-1.5 text-xs text-sky-800 lg:inline">
          {stage.bot_stage_key}
        </span>
      )}
      {stage.bot_status_key && (
        <span className="hidden rounded bg-emerald-100 px-1.5 text-xs text-emerald-800 lg:inline">
          {stage.bot_status_key}
        </span>
      )}
      <Button size="sm" variant="secondary" onClick={onEdit}>
        Изменить
      </Button>
      <Button size="sm" variant="ghost" onClick={onDelete}>
        Удалить
      </Button>
    </div>
  );
}

function StageModal({
  pipeline,
  stage,
  onClose,
}: {
  pipeline: Pipeline;
  stage: Stage | null;
  onClose: () => void;
}) {
  const { push } = useToast();
  const botStages = useBotStages();
  const createStage = useCreateStage();
  const updateStage = useUpdateStage();
  const [name, setName] = useState(stage?.name ?? "");
  const [color, setColor] = useState(stage?.color ?? "#94A3B8");
  const [kind, setKind] = useState<Stage["kind"]>(stage?.kind ?? "open");
  const [botKey, setBotKey] = useState(stage?.bot_stage_key ?? "");
  const [statusKey, setStatusKey] = useState(stage?.bot_status_key ?? "");

  const save = async () => {
    const payload: Record<string, unknown> = { name: name.trim(), color, kind };
    if (!stage) {
      if (botKey) payload.bot_stage_key = botKey;
      if (statusKey) payload.bot_status_key = statusKey;
    } else {
      payload.bot_stage_key = botKey;
      payload.bot_status_key = statusKey;
    }
    try {
      if (stage) {
        await updateStage.mutateAsync({ id: stage.id, patch: payload });
      } else {
        await createStage.mutateAsync({ pipeline_id: pipeline.id, stage: payload });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={stage ? "Стадия" : "Новая стадия"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <FieldLabel>
          Название
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </FieldLabel>
        <div className="flex gap-3">
          <FieldLabel>
            Цвет
            <input
              type="color"
              aria-label="Цвет стадии"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="h-9 w-16 cursor-pointer rounded-md border border-slate-200 dark:border-slate-700"
            />
          </FieldLabel>
          <FieldLabel>
            Тип
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as Stage["kind"])}
              className={inputClass}
            >
              <option value="open">Открытая</option>
              <option value="won">Выиграно</option>
              <option value="lost">Проиграно</option>
            </select>
          </FieldLabel>
        </div>
        <FieldLabel>
          Этап бота (current_stage)
          <select value={botKey} onChange={(e) => setBotKey(e.target.value)} className={inputClass}>
            <option value="">— не привязано —</option>
            {(botStages.data?.stages ?? []).map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </FieldLabel>
        <FieldLabel>
          Статус бота (для финальных стадий)
          <select
            value={statusKey}
            onChange={(e) => setStatusKey(e.target.value)}
            className={inputClass}
          >
            <option value="">— не привязано —</option>
            {(botStages.data?.statuses ?? []).map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </FieldLabel>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            disabled={!name.trim() || createStage.isPending || updateStage.isPending}
            onClick={() => void save()}
          >
            Сохранить
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function DeleteStageModal({
  pipeline,
  stage,
  onClose,
}: {
  pipeline: Pipeline;
  stage: Stage;
  onClose: () => void;
}) {
  const { push } = useToast();
  const deleteStage = useDeleteStage();
  const [recipient, setRecipient] = useState("");
  const others = pipeline.stages.filter((item) => item.id !== stage.id);

  const confirm = async () => {
    try {
      await deleteStage.mutateAsync(
        recipient ? { id: stage.id, to_stage_id: recipient } : { id: stage.id },
      );
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={`Удалить стадию «${stage.name}»?`} onClose={onClose}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-slate-600 dark:text-slate-300">
          Если на стадии есть сделки, выберите, куда их перенести. Без выбора удаление будет
          отклонено.
        </p>
        <FieldLabel>
          Перенести сделки в
          <select
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
            className={inputClass}
          >
            <option value="">— не переносить —</option>
            {others.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </FieldLabel>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button variant="danger" disabled={deleteStage.isPending} onClick={() => void confirm()}>
            Удалить
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function PipelineModal({ pipeline, onClose }: { pipeline: Pipeline | null; onClose: () => void }) {
  const { push } = useToast();
  const createPipeline = useCreatePipeline();
  const updatePipeline = useUpdatePipeline();
  const [name, setName] = useState(pipeline?.name ?? "");
  const [isDefault, setIsDefault] = useState(pipeline?.is_default ?? false);

  const save = async () => {
    try {
      if (pipeline) {
        await updatePipeline.mutateAsync({
          id: pipeline.id,
          patch: { name: name.trim(), is_default: isDefault },
        });
      } else {
        await createPipeline.mutateAsync({ name: name.trim(), is_default: isDefault });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={pipeline ? "Воронка" : "Новая воронка"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <FieldLabel>
          Название
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </FieldLabel>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isDefault}
            onChange={(e) => setIsDefault(e.target.checked)}
          />
          Воронка по умолчанию
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button disabled={!name.trim()} onClick={() => void save()}>
            Сохранить
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

export function FunnelsTab() {
  const { push } = useToast();
  const pipelinesQuery = usePipelines();
  const reorder = useReorderStages();
  const deletePipeline = useDeletePipeline();
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [pipelineModal, setPipelineModal] = useState<"create" | "edit" | null>(null);
  const [stageModal, setStageModal] = useState<Stage | "create" | null>(null);
  const [deleteStage, setDeleteStage] = useState<Stage | null>(null);

  // Generated OpenAPI types keep kind as string; narrow it once at the boundary.
  const pipelines: Pipeline[] = useMemo(
    () =>
      (pipelinesQuery.data ?? []).map((item) => ({
        ...item,
        stages: item.stages.map((stage) => ({
          ...stage,
          kind: stage.kind as Stage["kind"],
        })),
      })),
    [pipelinesQuery.data],
  );
  const pipeline =
    pipelines.find((item) => item.id === pipelineId) ??
    pipelines.find((item) => item.is_default) ??
    pipelines[0] ??
    null;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const onDragEnd = (event: DragEndEvent) => {
    if (!pipeline) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const ids = pipeline.stages.map((stage) => stage.id);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    const ordered = arrayMove(ids, from, to);
    reorder.mutate(
      { pipeline_id: pipeline.id, ordered_ids: ordered },
      { onError: (error) => toastError(push, error) },
    );
  };

  const removePipeline = async () => {
    if (!pipeline) return;
    if (!window.confirm(`Удалить воронку «${pipeline.name}»?`)) return;
    try {
      await deletePipeline.mutateAsync(pipeline.id);
      setPipelineId(null);
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <div className="grid gap-4">
      <Card
        title="Воронки"
        actions={
          <Button size="sm" onClick={() => setPipelineModal("create")}>
            Новая воронка
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Воронка"
            value={pipeline?.id ?? ""}
            onChange={(e) => setPipelineId(e.target.value)}
            className={cn(inputClass, "w-auto min-w-52")}
          >
            {pipelines.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
                {item.is_default ? " (по умолчанию)" : ""}
              </option>
            ))}
          </select>
          {pipeline && (
            <>
              <Button size="sm" variant="secondary" onClick={() => setPipelineModal("edit")}>
                Переименовать
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void removePipeline()}>
                Удалить
              </Button>
            </>
          )}
        </div>
      </Card>

      {pipeline && (
        <Card
          title={`Стадии · ${pipeline.name}`}
          actions={
            <Button size="sm" onClick={() => setStageModal("create")}>
              Новая стадия
            </Button>
          }
        >
          <p className="mb-2 text-xs text-slate-500">
            Порядок меняется перетаскиванием за ⋮⋮. Привязки к боту влияют на двустороннюю
            синхронизацию (см. docs/DECISIONS.md, D3).
          </p>
          <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            <SortableContext
              items={pipeline.stages.map((stage) => stage.id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="flex flex-col gap-1.5">
                {pipeline.stages.map((stage) => (
                  <SortableStageRow
                    key={stage.id}
                    stage={stage}
                    onEdit={() => setStageModal(stage)}
                    onDelete={() => setDeleteStage(stage)}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        </Card>
      )}

      <LostReasonsCard />

      {pipelineModal && (
        <PipelineModal
          pipeline={pipelineModal === "edit" ? pipeline : null}
          onClose={() => setPipelineModal(null)}
        />
      )}
      {stageModal && pipeline && (
        <StageModal
          pipeline={pipeline}
          stage={stageModal === "create" ? null : stageModal}
          onClose={() => setStageModal(null)}
        />
      )}
      {deleteStage && pipeline && (
        <DeleteStageModal
          pipeline={pipeline}
          stage={deleteStage}
          onClose={() => setDeleteStage(null)}
        />
      )}
    </div>
  );
}

function LostReasonsCard() {
  const { push } = useToast();
  const reasons = useAllLostReasons();
  const createReason = useCreateLostReason();
  const updateReason = useUpdateLostReason();
  const deleteReason = useDeleteLostReason();
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);

  const create = async () => {
    try {
      await createReason.mutateAsync({ name: name.trim() });
      setName("");
    } catch (error) {
      toastError(push, error);
    }
  };

  const saveEdit = async () => {
    if (!editing) return;
    try {
      await updateReason.mutateAsync({ id: editing.id, patch: { name: editing.name.trim() } });
      setEditing(null);
    } catch (error) {
      toastError(push, error);
    }
  };

  const remove = async (id: string, reasonName: string) => {
    if (!window.confirm(`Удалить причину «${reasonName}»?`)) return;
    try {
      await deleteReason.mutateAsync(id);
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <Card title="Причины отказа">
      <div className="mb-2 flex gap-2">
        <Input
          placeholder="Новая причина…"
          aria-label="Новая причина отказа"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button size="sm" disabled={!name.trim()} onClick={() => void create()}>
          Добавить
        </Button>
      </div>
      {editing && (
        <div className="mb-2 flex gap-2">
          <Input
            aria-label="Название причины"
            value={editing.name}
            onChange={(e) => setEditing({ ...editing, name: e.target.value })}
          />
          <Button size="sm" disabled={!editing.name.trim()} onClick={() => void saveEdit()}>
            Сохранить
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
            Отмена
          </Button>
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        {(reasons.data?.items ?? []).map((reason) => (
          <div
            key={reason.id}
            className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
          >
            <span className="flex-1">{reason.name}</span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setEditing({ id: reason.id, name: reason.name })}
            >
              Изменить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void remove(reason.id, reason.name)}>
              Удалить
            </Button>
          </div>
        ))}
      </div>
    </Card>
  );
}

// Custom fields

const FIELD_TYPES = [
  { value: "text", label: "Текст" },
  { value: "number", label: "Число" },
  { value: "date", label: "Дата" },
  { value: "select", label: "Выбор" },
  { value: "multiselect", label: "Множественный выбор" },
  { value: "bool", label: "Да/нет" },
];

function FieldModal({
  entity,
  field,
  onClose,
}: {
  entity: "contact" | "deal";
  field: CustomField | null;
  onClose: () => void;
}) {
  const { push } = useToast();
  const createField = useCreateCustomField();
  const updateField = useUpdateCustomField();
  const [key, setKey] = useState(field?.key ?? "");
  const [label, setLabel] = useState(field?.label ?? "");
  const [type, setType] = useState<CustomField["type"]>(field?.type ?? "text");
  const [required, setRequired] = useState(field?.required ?? false);
  const [sort, setSort] = useState(String(field?.sort ?? 0));
  const [optionsText, setOptionsText] = useState(
    Array.isArray(field?.options) ? (field.options as unknown[]).map(String).join("\n") : "",
  );
  const needsOptions = type === "select" || type === "multiselect";

  const save = async () => {
    const options = needsOptions
      ? optionsText
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean)
      : null;
    try {
      if (field) {
        await updateField.mutateAsync({
          id: field.id,
          patch: {
            label: label.trim(),
            required,
            sort: Number(sort) || 0,
            ...(needsOptions ? { options } : {}),
          },
        });
      } else {
        await createField.mutateAsync({
          entity,
          key: key.trim(),
          label: label.trim(),
          type,
          required,
          sort: Number(sort) || 0,
          ...(needsOptions ? { options } : {}),
        });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={field ? "Поле" : "Новое поле"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        {!field && (
          <FieldLabel>
            Ключ (латиница, без пробелов)
            <Input value={key} onChange={(e) => setKey(e.target.value)} />
          </FieldLabel>
        )}
        <FieldLabel>
          Подпись
          <Input value={label} onChange={(e) => setLabel(e.target.value)} />
        </FieldLabel>
        {!field && (
          <FieldLabel>
            Тип
            <select
              value={type}
              onChange={(e) => setType(e.target.value as CustomField["type"])}
              className={inputClass}
            >
              {FIELD_TYPES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </FieldLabel>
        )}
        {needsOptions && (
          <FieldLabel>
            Опции (по одной на строку)
            <textarea
              value={optionsText}
              onChange={(e) => setOptionsText(e.target.value)}
              rows={4}
              className={cn(inputClass, "h-auto py-2")}
            />
          </FieldLabel>
        )}
        <div className="flex gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
            />
            Обязательное
          </label>
          <FieldLabel>
            Порядок
            <Input value={sort} inputMode="numeric" onChange={(e) => setSort(e.target.value)} />
          </FieldLabel>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button disabled={!label.trim() || (!field && !key.trim())} onClick={() => void save()}>
            Сохранить
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

export function FieldsTab() {
  const { push } = useToast();
  const [entity, setEntity] = useState<"contact" | "deal">("deal");
  const [modal, setModal] = useState<CustomField | "create" | null>(null);
  const fields = useCustomFieldsAdmin(entity);
  const deleteField = useDeleteCustomField();

  const remove = async (field: CustomField) => {
    if (
      !window.confirm(
        `Удалить поле «${field.label}»? Значения в сделках/контактах останутся, но поле пропадёт из форм.`,
      )
    )
      return;
    try {
      await deleteField.mutateAsync(field.id);
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <Card
      title="Произвольные поля"
      actions={
        <div className="flex gap-1">
          {(["deal", "contact"] as const).map((value) => (
            <Button
              key={value}
              size="sm"
              variant={entity === value ? "default" : "secondary"}
              onClick={() => setEntity(value)}
            >
              {value === "deal" ? "Сделки" : "Контакты"}
            </Button>
          ))}
          <Button size="sm" onClick={() => setModal("create")}>
            Новое поле
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-1.5">
        {(fields.data?.items ?? []).map((field) => (
          <div
            key={field.id}
            className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
          >
            <span className="flex-1">
              <span className="font-medium">{field.label}</span>{" "}
              <span className="text-xs text-slate-500">
                {field.key} · {FIELD_TYPES.find((t) => t.value === field.type)?.label}
                {field.required ? " · обязательное" : ""}
              </span>
            </span>
            <Button size="sm" variant="secondary" onClick={() => setModal(field)}>
              Изменить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void remove(field)}>
              Удалить
            </Button>
          </div>
        ))}
        {fields.data?.items.length === 0 && (
          <p className="text-sm text-slate-500">Полей пока нет</p>
        )}
      </div>
      {modal && (
        <FieldModal
          entity={entity}
          field={modal === "create" ? null : modal}
          onClose={() => setModal(null)}
        />
      )}
    </Card>
  );
}

// Tags

function TagModal({
  tag,
  onClose,
}: {
  tag: { id: string; name: string; color: string | null } | null;
  onClose: () => void;
}) {
  const { push } = useToast();
  const createTag = useCreateTag();
  const updateTag = useUpdateTag();
  const [name, setName] = useState(tag?.name ?? "");
  const [color, setColor] = useState(tag?.color ?? "#94A3B8");

  const save = async () => {
    try {
      if (tag) {
        await updateTag.mutateAsync({ id: tag.id, patch: { name: name.trim(), color } });
      } else {
        await createTag.mutateAsync({ name: name.trim(), color });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={tag ? "Тег" : "Новый тег"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <FieldLabel>
          Название
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </FieldLabel>
        <FieldLabel>
          Цвет
          <input
            type="color"
            aria-label="Цвет тега"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="h-9 w-16 cursor-pointer rounded-md border border-slate-200 dark:border-slate-700"
          />
        </FieldLabel>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button disabled={!name.trim()} onClick={() => void save()}>
            Сохранить
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

export function TagsTab() {
  const { push } = useToast();
  const tags = useTags();
  const deleteTag = useDeleteTag();
  const [modal, setModal] = useState<
    { id: string; name: string; color: string | null } | "create" | null
  >(null);

  const remove = async (id: string, name: string) => {
    if (!window.confirm(`Удалить тег «${name}»? Он будет снят со всех сущностей.`)) return;
    try {
      const result = await deleteTag.mutateAsync(id);
      push({ title: `Тег удалён (снято: ${result.detached_from ?? "—"})`, variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <Card
      title="Теги"
      actions={
        <Button size="sm" onClick={() => setModal("create")}>
          Новый тег
        </Button>
      }
    >
      <div className="flex flex-col gap-1.5">
        {(tags.data?.items ?? []).map((tag) => (
          <div
            key={tag.id}
            className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
          >
            <span
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: tag.color ?? "#94A3B8" }}
            />
            <span className="flex-1 font-medium">{tag.name}</span>
            <Button size="sm" variant="secondary" onClick={() => setModal(tag)}>
              Изменить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void remove(tag.id, tag.name)}>
              Удалить
            </Button>
          </div>
        ))}
      </div>
      {modal && <TagModal tag={modal === "create" ? null : modal} onClose={() => setModal(null)} />}
    </Card>
  );
}

// Quick replies

function ReplyModal({ reply, onClose }: { reply: QuickReply | null; onClose: () => void }) {
  const { push } = useToast();
  const createReply = useCreateQuickReply();
  const updateReply = useUpdateQuickReply();
  const [title, setTitle] = useState(reply?.title ?? "");
  const [body, setBody] = useState(reply?.body ?? "");
  const [sort, setSort] = useState(String(reply?.sort ?? 0));

  const save = async () => {
    try {
      if (reply) {
        await updateReply.mutateAsync({
          id: reply.id,
          patch: { title: title.trim(), body: body.trim(), sort: Number(sort) || 0 },
        });
      } else {
        await createReply.mutateAsync({
          title: title.trim(),
          body: body.trim(),
          sort: Number(sort) || 0,
        });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={reply ? "Шаблон" : "Новый шаблон"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <FieldLabel>
          Название
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </FieldLabel>
        <FieldLabel>
          Текст (поддерживается {"{name}"})
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={4}
            className={cn(inputClass, "h-auto py-2")}
          />
        </FieldLabel>
        <FieldLabel>
          Порядок
          <Input value={sort} inputMode="numeric" onChange={(e) => setSort(e.target.value)} />
        </FieldLabel>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button disabled={!title.trim() || !body.trim()} onClick={() => void save()}>
            Сохранить
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

export function RepliesTab() {
  const { push } = useToast();
  const replies = useQuickReplies();
  const deleteReply = useDeleteQuickReply();
  const [modal, setModal] = useState<QuickReply | "create" | null>(null);

  const remove = async (reply: QuickReply) => {
    if (!window.confirm(`Удалить шаблон «${reply.title}»?`)) return;
    try {
      await deleteReply.mutateAsync(reply.id);
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <Card
      title="Шаблоны быстрых ответов"
      actions={
        <Button size="sm" onClick={() => setModal("create")}>
          Новый шаблон
        </Button>
      }
    >
      <div className="flex flex-col gap-1.5">
        {(replies.data?.items ?? []).map((reply) => (
          <div
            key={reply.id}
            className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
          >
            <div className="min-w-0 flex-1">
              <p className="font-medium">{reply.title}</p>
              <p className="truncate text-xs text-slate-500">{reply.body}</p>
            </div>
            <Button size="sm" variant="secondary" onClick={() => setModal(reply)}>
              Изменить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void remove(reply)}>
              Удалить
            </Button>
          </div>
        ))}
        {replies.data?.items.length === 0 && (
          <p className="text-sm text-slate-500">Шаблонов пока нет</p>
        )}
      </div>
      {modal && (
        <ReplyModal reply={modal === "create" ? null : modal} onClose={() => setModal(null)} />
      )}
    </Card>
  );
}
