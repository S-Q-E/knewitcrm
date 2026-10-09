import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  contactQueryString,
  exportUrl,
  toContactParams,
  useBulkContacts,
  useContactSavedViews,
  useContactsList,
  useCreateContactSavedView,
  useDeleteContactSavedView,
  useDeleteContact,
  useDuplicates,
  useImportJob,
  useMergeContacts,
  useRestoreContact,
  useTrash,
  type ContactFilters,
  type ImportPreview,
} from "@/api/contacts";
import { useTags, useUsersLite } from "@/api/deals";
import { useMe } from "@/api/auth";
import { api } from "@/api/client";
import { toastError, useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ALL_COLUMNS = [
  { id: "name", label: "Имя" },
  { id: "phone", label: "Телефон" },
  { id: "email", label: "Email" },
  { id: "whatsapp", label: "WhatsApp" },
  { id: "owner", label: "Ответственный" },
  { id: "tags", label: "Теги" },
] as const;

type ColumnId = (typeof ALL_COLUMNS)[number]["id"];
const STORAGE_KEY = "knewitcrm-contact-columns";

function loadColumns(): ColumnId[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as string[];
      const valid = parsed.filter((id): id is ColumnId => ALL_COLUMNS.some((c) => c.id === id));
      if (valid.length > 0) return valid;
    }
  } catch {
    // defaults
  }
  return ALL_COLUMNS.map((c) => c.id);
}

const IMPORT_FIELDS = ["ignore", "name", "phone", "email", "whatsapp_id", "source"];

export function autoMapping(header: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const col of header) {
    const low = col.trim().toLowerCase();
    if (["name", "имя", "фио", "full_name"].includes(low)) out[col] = "name";
    else if (["phone", "телефон", "phone_number", "tel"].includes(low)) out[col] = "phone";
    else if (["email", "почта", "e-mail"].includes(low)) out[col] = "email";
    else if (["whatsapp", "whatsapp_id", "wa"].includes(low)) out[col] = "whatsapp_id";
    else if (["source", "источник"].includes(low)) out[col] = "source";
    else out[col] = "ignore";
  }
  return out;
}

export function ContactsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "list";
  const setTab = (value: string) => {
    const next = new URLSearchParams(params);
    next.set("tab", value);
    setParams(next);
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-bold">Контакты</h1>
        <nav className="ml-4 flex gap-1 text-sm">
          {[
            ["list", "Список"],
            ["duplicates", "Дубликаты"],
            ["import", "Импорт"],
            ["trash", "Корзина"],
          ].map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={cn(
                "rounded-md px-2 py-1",
                tab === id
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "hover:bg-slate-100 dark:hover:bg-slate-800",
              )}
            >
              {label}
            </button>
          ))}
        </nav>
      </div>
      {tab === "list" && <ContactsList />}
      {tab === "duplicates" && <DuplicatesView />}
      {tab === "import" && <ImportView />}
      {tab === "trash" && <TrashView />}
    </div>
  );
}

function ContactsList() {
  const { push } = useToast();
  const [params, setParams] = useSearchParams();
  const search = params.get("q") ?? "";
  const [sort, setSort] = useState("-created_at");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [columns, setColumns] = useState<ColumnId[]>(loadColumns);
  const [ownerId, setOwnerId] = useState("");
  const [source, setSource] = useState("");
  const [viewName, setViewName] = useState("");
  const [bulkOwner, setBulkOwner] = useState("");
  const [bulkTag, setBulkTag] = useState("");
  const limit = 50;

  const filters: ContactFilters = useMemo(
    () => ({
      search: search || undefined,
      owner_id: ownerId || undefined,
      source: source || undefined,
    }),
    [search, ownerId, source],
  );
  const list = useContactsList({ ...filters, sort, limit, offset });
  const bulk = useBulkContacts();
  const remove = useDeleteContact();
  const users = useUsersLite();
  const tags = useTags();
  const savedViews = useContactSavedViews();
  const createView = useCreateContactSavedView();
  const deleteView = useDeleteContactSavedView();

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const qs = contactQueryString({ ...toContactParams(filters), sort });

  const toggleSort = (field: string) => setSort((prev) => (prev === field ? `-${field}` : field));

  const toggleColumn = (id: ColumnId) => {
    setColumns((prev) => {
      const next = prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id];
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };

  const runBulk = async (del = false) => {
    if (selected.size === 0) return;
    try {
      await bulk.mutateAsync({
        ids: [...selected],
        set_owner_id: bulkOwner || undefined,
        add_tag_id: bulkTag || undefined,
        delete: del,
      });
      setSelected(new Set());
      push({
        title: del ? `В корзину: ${selected.size}` : `Обновлено: ${selected.size}`,
        variant: "default",
      });
    } catch (error) {
      toastError(push, error);
    }
  };

  const saveView = async () => {
    if (!viewName.trim()) return;
    try {
      await createView.mutateAsync({ name: viewName.trim(), filters });
      setViewName("");
      push({ title: "Вид сохранён", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label="Быстрый поиск"
          placeholder="Быстрый поиск: имя, телефон, email…"
          value={search}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            if (e.target.value) next.set("q", e.target.value);
            else next.delete("q");
            setParams(next);
            setOffset(0);
          }}
          className="h-9 w-72 rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
        />
        <select
          aria-label="Ответственный"
          value={ownerId}
          onChange={(e) => setOwnerId(e.target.value)}
          className="h-9 rounded-md border border-slate-200 bg-white px-1 text-sm dark:border-slate-700 dark:bg-slate-900"
        >
          <option value="">Все ответственные</option>
          {users.data?.items.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Источник"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="h-9 rounded-md border border-slate-200 bg-white px-1 text-sm dark:border-slate-700 dark:bg-slate-900"
        >
          <option value="">Все источники</option>
          <option value="bot">Бот</option>
          <option value="manual">Вручную</option>
          <option value="import">Импорт</option>
        </select>
        <a
          className="text-sm text-blue-600 hover:underline"
          href={exportUrl("contacts", "csv", qs)}
        >
          CSV
        </a>
        <a
          className="text-sm text-blue-600 hover:underline"
          href={exportUrl("contacts", "xlsx", qs)}
        >
          XLSX
        </a>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Виды:</span>
        {savedViews.data?.items.map((v) => (
          <span
            key={v.id}
            className="flex items-center gap-1 rounded-md border border-slate-200 px-2 py-0.5 dark:border-slate-700"
          >
            <button
              type="button"
              className="hover:underline"
              onClick={() => {
                setOwnerId(v.filters.owner_id ?? "");
                setSource(v.filters.source ?? "");
                const next = new URLSearchParams(params);
                if (v.filters.search) next.set("q", v.filters.search);
                else next.delete("q");
                setParams(next);
                setOffset(0);
              }}
            >
              {v.name}
            </button>
            <button
              type="button"
              aria-label={`Удалить вид ${v.name}`}
              onClick={() => void deleteView.mutateAsync(v.id)}
              className="text-slate-400 hover:text-red-600"
            >
              ×
            </button>
          </span>
        ))}
        <input
          aria-label="Название вида"
          placeholder="Название вида…"
          value={viewName}
          onChange={(e) => setViewName(e.target.value)}
          className="h-8 w-40 rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
        />
        <Button size="sm" variant="secondary" onClick={() => void saveView()}>
          Сохранить вид
        </Button>
      </div>

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
            aria-label="Массово: ответственный"
            value={bulkOwner}
            onChange={(e) => setBulkOwner(e.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Ответственный…</option>
            {users.data?.items.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Массово: тег"
            value={bulkTag}
            onChange={(e) => setBulkTag(e.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Тег…</option>
            {tags.data?.items.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <Button size="sm" onClick={() => void runBulk(false)} disabled={bulk.isPending}>
            Применить
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void runBulk(true)}
            disabled={bulk.isPending}
          >
            В корзину
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
                  checked={items.length > 0 && items.every((i) => selected.has(i.id))}
                  onChange={() =>
                    setSelected((prev) =>
                      prev.size === items.length ? new Set() : new Set(items.map((i) => i.id)),
                    )
                  }
                />
              </th>
              {columns.map((col) => (
                <th key={col} className="p-2">
                  <button
                    type="button"
                    onClick={() =>
                      toggleSort(
                        col === "whatsapp"
                          ? "created_at"
                          : col === "tags"
                            ? "created_at"
                            : col === "owner"
                              ? "created_at"
                              : col === "phone"
                                ? "created_at"
                                : col === "email"
                                  ? "created_at"
                                  : col,
                      )
                    }
                    className="font-medium hover:underline"
                  >
                    {ALL_COLUMNS.find((c) => c.id === col)?.label}
                    {sort.replace("-", "") === col && (sort.startsWith("-") ? " ↓" : " ↑")}
                  </button>
                </th>
              ))}
              <th className="p-2 font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr
                key={c.id}
                className="border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
              >
                <td className="p-2">
                  <input
                    type="checkbox"
                    aria-label={`Выбрать ${c.name ?? c.phone ?? c.id}`}
                    checked={selected.has(c.id)}
                    onChange={() =>
                      setSelected((prev) => {
                        const next = new Set(prev);
                        if (next.has(c.id)) next.delete(c.id);
                        else next.add(c.id);
                        return next;
                      })
                    }
                  />
                </td>
                {columns.map((col) => (
                  <td key={col} className="max-w-60 truncate p-2">
                    {col === "name" ? (
                      <Link
                        className="font-medium text-blue-600 hover:underline"
                        to={`/contacts/${c.id}`}
                      >
                        {c.name ?? "—"}
                      </Link>
                    ) : col === "phone" ? (
                      (c.phone ?? "—")
                    ) : col === "email" ? (
                      (c.email ?? "—")
                    ) : col === "whatsapp" ? (
                      (c.whatsapp_id ?? "—")
                    ) : col === "owner" ? (
                      (users.data?.items.find((u) => u.id === c.owner_id)?.name ?? "—")
                    ) : (
                      c.tags.map((t) => t.name).join(", ") || "—"
                    )}
                  </td>
                ))}
                <td className="p-2">
                  <button
                    type="button"
                    className="text-red-600 hover:underline"
                    onClick={() => {
                      if (window.confirm("Удалить контакт в корзину?")) {
                        void remove.mutateAsync(c.id).catch((e: unknown) => toastError(push, e));
                      }
                    }}
                  >
                    В корзину
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.isPending && <p className="p-4 text-sm text-slate-500">Загрузка…</p>}
        {list.isError && <p className="p-4 text-sm text-red-600">Не удалось загрузить контакты.</p>}
        {!list.isPending && items.length === 0 && (
          <p className="p-4 text-sm text-slate-500">Контактов нет. Измените фильтры.</p>
        )}
      </div>

      <div className="flex items-center gap-2 text-sm">
        <Button
          variant="secondary"
          size="sm"
          disabled={offset === 0}
          onClick={() => setOffset((v) => Math.max(0, v - limit))}
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
          onClick={() => setOffset((v) => v + limit)}
        >
          Далее
        </Button>
      </div>
    </div>
  );
}

function DuplicatesView() {
  const { push } = useToast();
  const dup = useDuplicates();
  const merge = useMergeContacts();
  const [winners, setWinners] = useState<Record<string, string>>({});
  const groups = dup.data?.groups ?? [];
  if (dup.isPending) return <p className="text-sm text-slate-500">Ищем дубликаты…</p>;
  if (dup.isError) return <p className="text-sm text-red-600">Не удалось загрузить дубликаты.</p>;
  if (groups.length === 0) return <p className="text-sm text-slate-500">Дубликатов не найдено.</p>;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-slate-500">
        Групп: {groups.length}. Объединение переносит сделки, заметки, задачи и теги; источник
        остаётся в корзине.
      </p>
      {groups.map((g) => (
        <div
          key={g.key}
          className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900"
        >
          <p className="text-sm font-medium">
            {g.kind === "phone" ? "Телефон" : "Email"}: {g.value}
          </p>
          <div className="mt-2 flex flex-col gap-1">
            {g.contact_ids.map((id) => (
              <label key={id} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name={`winner-${g.key}`}
                  checked={winners[g.key] === id}
                  onChange={() => setWinners((prev) => ({ ...prev, [g.key]: id }))}
                />
                <Link className="text-blue-600 hover:underline" to={`/contacts/${id}`}>
                  {id.slice(0, 8)}
                </Link>
                <span className="text-slate-500">оставить как основной</span>
              </label>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            {g.contact_ids
              .filter((id) => id !== winners[g.key])
              .map((loser) => (
                <Button
                  key={loser}
                  size="sm"
                  disabled={!winners[g.key] || merge.isPending}
                  onClick={() => {
                    const winner = winners[g.key];
                    if (!winner) return;
                    if (!window.confirm("Объединить контакты? Действие необратимо.")) return;
                    void merge
                      .mutateAsync({ winner_id: winner, loser_id: loser })
                      .then(() => push({ title: "Контакты объединены", variant: "default" }))
                      .catch((e: unknown) => toastError(push, e));
                  }}
                >
                  Влить {loser.slice(0, 8)} в основной
                </Button>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ImportView() {
  const { push } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [header, setHeader] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const job = useImportJob(jobId, running);

  const readHeader = async (f: File) => {
    const text = await f.text();
    const first = text.split(/\r?\n/)[0] ?? "";
    const cols = first
      .split(/[,;]/)
      .map((c) => c.trim())
      .filter(Boolean);
    setHeader(cols);
    setMapping(autoMapping(cols));
  };

  const doPreviewFetch = async () => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("mapping", JSON.stringify(mapping));
    const token = document.cookie.match(/crm_csrf=([^;]+)/)?.[1] ?? "";
    const resp = await fetch("/api/contacts/import/preview", {
      method: "POST",
      body: form,
      credentials: "include",
      headers: token ? { "X-CSRF-Token": decodeURIComponent(token) } : {},
    });
    if (!resp.ok) {
      const body = (await resp.json().catch(() => null)) as { error?: { message?: string } } | null;
      push({ title: body?.error?.message ?? "Ошибка предпросмотра", variant: "error" });
      return;
    }
    const data = (await resp.json()) as ImportPreview;
    setPreview(data);
  };

  const doImport = async () => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("mapping", JSON.stringify(mapping));
    const token = document.cookie.match(/crm_csrf=([^;]+)/)?.[1] ?? "";
    const resp = await fetch("/api/contacts/import", {
      method: "POST",
      body: form,
      credentials: "include",
      headers: token ? { "X-CSRF-Token": decodeURIComponent(token) } : {},
    });
    if (!resp.ok) {
      push({ title: "Ошибка импорта", variant: "error" });
      return;
    }
    const data = (await resp.json()) as { id: string };
    setJobId(data.id);
    setRunning(true);
  };

  const finished =
    job.data?.status === "done" || job.data?.status === "failed" || job.isError;
  useEffect(() => {
    // Intentional sync: stop polling once the polled import reaches a terminal state or errors.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (finished && running) setRunning(false);
  }, [finished, running]);

  return (
    <div className="flex max-w-2xl flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="font-medium">Импорт CSV</h2>
      <input
        aria-label="CSV файл"
        type="file"
        accept=".csv,text/csv"
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          setFile(f);
          setPreview(null);
          if (f) void readHeader(f);
        }}
      />
      {header.length > 0 && (
        <div className="flex flex-col gap-1 text-sm">
          <p className="font-medium">Маппинг колонок:</p>
          {header.map((col) => (
            <label key={col} className="flex items-center gap-2">
              <span className="w-40 truncate font-mono text-xs">{col}</span>
              <select
                value={mapping[col] ?? "ignore"}
                onChange={(e) => setMapping((prev) => ({ ...prev, [col]: e.target.value }))}
                className="h-8 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
              >
                {IMPORT_FIELDS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={!file}
          onClick={() => void doPreviewFetch()}
        >
          Предпросмотр
        </Button>
        <Button size="sm" disabled={!file} onClick={() => void doImport()}>
          Импортировать в фоне
        </Button>
      </div>
      {preview && (
        <div className="text-sm">
          <p>
            Всего строк: {preview.total}, валидных: {preview.valid}, с ошибками: {preview.invalid}
          </p>
          {preview.errors.length > 0 && (
            <ul className="mt-1 max-h-32 overflow-auto text-red-600">
              {preview.errors.map((e, i) => (
                <li key={i}>
                  Строка {e.row}: {e.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {job.data && (
        <div className="text-sm">
          <p>
            Задача {job.data.id}: {job.data.status}, ок: {job.data.ok_count}, ошибок:{" "}
            {job.data.error_count}
          </p>
          {job.data.errors.length > 0 && (
            <ul className="mt-1 max-h-32 overflow-auto text-red-600">
              {job.data.errors.map((e, i) => (
                <li key={i}>
                  Строка {e.row}: {e.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function TrashView() {
  const { push } = useToast();
  const me = useMe();
  const trash = useTrash("all");
  const restoreContact = useRestoreContact();
  if (me.data && me.data.role !== "admin") {
    return <p className="text-sm text-slate-500">Корзина доступна только администраторам.</p>;
  }
  if (trash.isPending) return <p className="text-sm text-slate-500">Загрузка корзины…</p>;
  if (trash.isError)
    return <p className="text-sm text-red-600">Нет доступа или ошибка загрузки.</p>;
  const items = trash.data?.items ?? [];
  if (items.length === 0) return <p className="text-sm text-slate-500">Корзина пуста.</p>;
  return (
    <div className="flex flex-col gap-2">
      {items.map((item) => (
        <div
          key={`${item.kind}-${item.id}`}
          className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-2 text-sm dark:border-slate-800 dark:bg-slate-900"
        >
          <span className="rounded bg-slate-100 px-1 text-xs dark:bg-slate-800">{item.kind}</span>
          <span className="font-medium">{item.name ?? item.id.slice(0, 8)}</span>
          <button
            type="button"
            className="ml-auto text-blue-600 hover:underline"
            onClick={() => {
              const doRestore =
                item.kind === "contact"
                  ? restoreContact.mutateAsync(item.id)
                  : api.post(`/api/deals/${item.id}/restore`).then(() => undefined);
              void doRestore
                .then(() => push({ title: "Восстановлено", variant: "default" }))
                .catch((e: unknown) => toastError(push, e));
            }}
          >
            Восстановить
          </button>
        </div>
      ))}
    </div>
  );
}
