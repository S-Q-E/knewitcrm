import { useMemo, useState } from "react";

import type { Deal, DealFilters, Stage } from "@/api/deals";
import { useBulkDeals, useDealsList, useLostReasons, useTags, useUsersLite } from "@/api/deals";
import { useToast, toastError } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { formatMoney, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

const ALL_COLUMNS = [
  { id: "title", label: "Название" },
  { id: "contact", label: "Контакт" },
  { id: "amount", label: "Сумма" },
  { id: "owner", label: "Ответственный" },
  { id: "tags", label: "Теги" },
  { id: "updated", label: "Активность" },
] as const;

type ColumnId = (typeof ALL_COLUMNS)[number]["id"];

const STORAGE_KEY = "knewitcrm-deal-columns";

function loadColumns(): ColumnId[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as string[];
      const valid = parsed.filter((id): id is ColumnId => ALL_COLUMNS.some((col) => col.id === id));
      if (valid.length > 0) {
        return valid;
      }
    }
  } catch {
    // Fall through to defaults.
  }
  return ALL_COLUMNS.map((col) => col.id);
}

interface ListViewProps {
  filters: DealFilters;
  stagesById: Map<string, Stage>;
  contactsById: Map<string, { name: string | null; phone: string | null }>;
  onOpen: (id: string) => void;
}

export function DealsListView({ filters, stagesById, contactsById, onOpen }: ListViewProps) {
  const { push } = useToast();
  const [sort, setSort] = useState("-created_at");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [columns, setColumns] = useState<ColumnId[]>(loadColumns);
  const [bulkStage, setBulkStage] = useState("");
  const [bulkOwner, setBulkOwner] = useState("");
  const [bulkTag, setBulkTag] = useState("");
  const [bulkReason, setBulkReason] = useState("");
  const limit = 50;

  const list = useDealsList({ ...filters, sort, limit, offset });
  const bulk = useBulkDeals();
  const users = useUsersLite();
  const tags = useTags();
  const reasons = useLostReasons();

  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;

  const toggleSort = (field: string) => {
    setSort((prev) => (prev === field ? `-${field}` : field));
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const runBulk = async () => {
    if (selected.size === 0) {
      return;
    }
    try {
      await bulk.mutateAsync({
        ids: [...selected],
        set_stage_id: bulkStage || undefined,
        set_owner_id: bulkOwner || undefined,
        add_tag_id: bulkTag || undefined,
        close_lost_reason_id: bulkReason || undefined,
      });
      setSelected(new Set());
      push({ title: `Обновлено сделок: ${selected.size}`, variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  const toggleColumn = (id: ColumnId) => {
    setColumns((prev) => {
      const next = prev.includes(id) ? prev.filter((col) => col !== id) : [...prev, id];
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };

  const cell = (deal: Deal, column: ColumnId): React.ReactNode => {
    const contact = contactsById.get(deal.contact_id);
    switch (column) {
      case "title":
        return <span className="font-medium">{deal.title}</span>;
      case "contact":
        return contact?.name ?? contact?.phone ?? "—";
      case "amount":
        return formatMoney(deal.amount, deal.currency);
      case "owner":
        return users.data?.items.find((user) => user.id === deal.owner_id)?.name ?? "—";
      case "tags":
        return deal.tags.map((tag) => tag.name).join(", ") || "—";
      case "updated":
        return formatRelative(deal.updated_at);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="font-medium">Колонки:</span>
        {ALL_COLUMNS.map((col) => (
          <label key={col.id} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={columns.includes(col.id)}
              onChange={() => toggleColumn(col.id)}
            />
            {col.label}
          </label>
        ))}
      </div>

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-sm dark:border-slate-700 dark:bg-slate-900">
          <span className="font-medium">Выбрано: {selected.size}</span>
          <select
            aria-label="Массово: стадия"
            value={bulkStage}
            onChange={(event) => setBulkStage(event.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Стадия…</option>
            {[...stagesById.values()].map((stage) => (
              <option key={stage.id} value={stage.id}>
                {stage.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Массово: ответственный"
            value={bulkOwner}
            onChange={(event) => setBulkOwner(event.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Ответственный…</option>
            {users.data?.items.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Массово: тег"
            value={bulkTag}
            onChange={(event) => setBulkTag(event.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Тег…</option>
            {tags.data?.items.map((tag) => (
              <option key={tag.id} value={tag.id}>
                {tag.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Массово: закрыть как отказ"
            value={bulkReason}
            onChange={(event) => setBulkReason(event.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Закрыть как отказ…</option>
            {reasons.data?.items.map((reason) => (
              <option key={reason.id} value={reason.id}>
                {reason.name}
              </option>
            ))}
          </select>
          <Button size="sm" onClick={() => void runBulk()} disabled={bulk.isPending}>
            Применить
          </Button>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full min-w-160 text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800">
              <th className="w-8 p-2">
                <input
                  type="checkbox"
                  aria-label="Выбрать всё"
                  checked={items.length > 0 && items.every((item) => selected.has(item.id))}
                  onChange={() =>
                    setSelected((prev) =>
                      prev.size === items.length
                        ? new Set()
                        : new Set(items.map((item) => item.id)),
                    )
                  }
                />
              </th>
              {columns.map((col) => (
                <th key={col} className="p-2">
                  <button
                    type="button"
                    onClick={() => toggleSort(col === "updated" ? "updated_at" : col)}
                    className={cn("font-medium hover:underline")}
                  >
                    {ALL_COLUMNS.find((candidate) => candidate.id === col)?.label}
                    {sort.replace("-", "") === (col === "updated" ? "updated_at" : col) &&
                      (sort.startsWith("-") ? " ↓" : " ↑")}
                  </button>
                </th>
              ))}
              <th className="p-2 font-medium">Стадия</th>
            </tr>
          </thead>
          <tbody>
            {items.map((deal) => (
              <tr
                key={deal.id}
                data-deal-id={deal.id}
                onClick={() => onOpen(deal.id)}
                className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
              >
                <td className="p-2" onClick={(event) => event.stopPropagation()}>
                  <input
                    type="checkbox"
                    aria-label={`Выбрать ${deal.title}`}
                    checked={selected.has(deal.id)}
                    onChange={() => toggleSelect(deal.id)}
                  />
                </td>
                {columns.map((col) => (
                  <td key={col} className="max-w-60 truncate p-2">
                    {cell(deal, col)}
                  </td>
                ))}
                <td className="p-2">{stagesById.get(deal.stage_id)?.name ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.isPending && <p className="p-4 text-sm text-slate-500">Загрузка…</p>}
        {list.isError && <p className="p-4 text-sm text-red-600">Не удалось загрузить сделки.</p>}
        {!list.isPending && items.length === 0 && (
          <p className="p-4 text-sm text-slate-500">Сделок нет. Измените фильтры.</p>
        )}
      </div>

      <div className="flex items-center gap-2 text-sm">
        <Button
          variant="secondary"
          size="sm"
          disabled={offset === 0}
          onClick={() => setOffset((value) => Math.max(0, value - limit))}
        >
          Назад
        </Button>
        <span>
          {offset + 1}–{Math.min(offset + limit, total)} из {total}
        </span>
        <Button
          variant="secondary"
          size="sm"
          disabled={offset + limit >= total}
          onClick={() => setOffset((value) => value + limit)}
        >
          Далее
        </Button>
      </div>
    </div>
  );
}
