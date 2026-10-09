import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useContact,
  useContactDeals,
  useContactTimeline,
  useDeleteContact,
  useUpdateContact,
} from "@/api/contacts";
import { useCreateNote, useCustomFields, useTags, useUsersLite } from "@/api/deals";
import { api } from "@/api/client";
import { toastError, useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";

export function ContactPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { push } = useToast();
  const queryClient = useQueryClient();
  const contact = useContact(id ?? null);
  const deals = useContactDeals(id ?? null);
  const timeline = useContactTimeline(id ?? null);
  const update = useUpdateContact();
  const remove = useDeleteContact();
  const users = useUsersLite();
  const tags = useTags();
  const customDefs = useCustomFields("contact");
  const createNote = useCreateNote();
  const [noteBody, setNoteBody] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [customForm, setCustomForm] = useState<Record<string, string>>({});

  if (contact.isPending) return <p className="text-sm text-slate-500">Загрузка контакта…</p>;
  if (contact.isError || !contact.data) {
    return <p className="text-sm text-red-600">Контакт не найден.</p>;
  }
  const c = contact.data;

  const save = async () => {
    const patch: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(form)) {
      if (v !== "") patch[k] = v;
    }
    if (Object.keys(customForm).length > 0) {
      patch.custom = { ...c.custom, ...customForm };
    }
    if (Object.keys(patch).length === 0) return;
    try {
      await update.mutateAsync({ id: c.id, patch });
      setForm({});
      setCustomForm({});
      push({ title: "Контакт обновлён", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  const setTags = async (tagIds: string[]) => {
    try {
      await api.put(`/api/contacts/${c.id}/tags`, { tag_ids: tagIds });
      push({ title: "Теги обновлены", variant: "default" });
    } catch (error) {
      toastError(push, error);
    } finally {
      void queryClient.invalidateQueries({ queryKey: ["contact", c.id] });
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Link className="text-sm text-blue-600 hover:underline" to="/contacts">
        ← К контактам
      </Link>
      <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-xl font-bold">{c.name ?? "Без имени"}</h1>
        <p className="mt-1 text-sm text-slate-500">
          {c.phone ?? "—"} · {c.email ?? "—"} · {c.whatsapp_id ?? "—"} · источник: {c.source ?? "—"}
        </p>
        <div className="mt-3 grid max-w-2xl grid-cols-2 gap-2 text-sm">
          {(["name", "phone", "email", "source"] as const).map((field) => (
            <label key={field} className="flex flex-col gap-1">
              <span className="text-xs text-slate-500">{field}</span>
              <input
                defaultValue={String(c[field] ?? "")}
                onChange={(e) => setForm((prev) => ({ ...prev, [field]: e.target.value }))}
                className="h-9 rounded-md border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-900"
              />
            </label>
          ))}
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Ответственный</span>
            <select
              defaultValue={c.owner_id ?? ""}
              onChange={(e) => setForm((prev) => ({ ...prev, owner_id: e.target.value }))}
              className="h-9 rounded-md border border-slate-200 bg-white px-1 dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="">—</option>
              {users.data?.items.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {customDefs.data && customDefs.data.items.length > 0 && (
          <div className="mt-3 grid max-w-2xl grid-cols-2 gap-2 text-sm">
            {customDefs.data.items.map((def) => (
              <label key={def.id} className="flex flex-col gap-1">
                <span className="text-xs text-slate-500">{def.label}</span>
                <input
                  defaultValue={String(c.custom[def.key] ?? "")}
                  onChange={(e) =>
                    setCustomForm((prev) => ({ ...prev, [def.key]: e.target.value }))
                  }
                  className="h-9 rounded-md border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-900"
                />
              </label>
            ))}
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void save()} disabled={update.isPending}>
            Сохранить
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              if (window.confirm("Удалить контакт в корзину?")) {
                void remove
                  .mutateAsync(c.id)
                  .then(() => navigate("/contacts"))
                  .catch((e: unknown) => toastError(push, e));
              }
            }}
          >
            В корзину
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap gap-1 text-xs">
          {tags.data?.items.map((t) => {
            const active = c.tags.some((ct) => ct.id === t.id);
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => {
                  const next = active
                    ? c.tags.filter((ct) => ct.id !== t.id).map((ct) => ct.id)
                    : [...c.tags.map((ct) => ct.id), t.id];
                  void setTags(next);
                }}
                className={
                  active
                    ? "rounded-md bg-slate-900 px-2 py-0.5 text-white dark:bg-slate-100 dark:text-slate-900"
                    : "rounded-md border border-slate-200 px-2 py-0.5 dark:border-slate-700"
                }
              >
                {t.name}
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="font-medium">Сделки контакта ({deals.data?.total ?? 0})</h2>
        <ul className="mt-2 flex flex-col gap-1 text-sm">
          {(deals.data?.items ?? []).map((d) => (
            <li key={d.id}>
              <Link className="text-blue-600 hover:underline" to={`/deals/${d.id}`}>
                {d.title}
              </Link>
              <span className="ml-2 text-slate-500">
                {d.status} · {d.amount ?? "—"} {d.currency}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="font-medium">Заметка</h2>
        <div className="mt-2 flex gap-2">
          <input
            aria-label="Текст заметки"
            value={noteBody}
            onChange={(e) => setNoteBody(e.target.value)}
            placeholder="Новая заметка…"
            className="h-9 flex-1 rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          />
          <Button
            size="sm"
            disabled={!noteBody.trim()}
            onClick={() => {
              void createNote
                .mutateAsync({ contact_id: c.id, body: noteBody.trim() })
                .then(() => {
                  setNoteBody("");
                  push({ title: "Заметка добавлена", variant: "default" });
                })
                .catch((e: unknown) => toastError(push, e));
            }}
          >
            Добавить
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="font-medium">Общая лента</h2>
        {timeline.isPending && <p className="mt-2 text-sm text-slate-500">Загрузка ленты…</p>}
        {timeline.data && (
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {timeline.data.items.map((item) => (
              <li
                key={item.key}
                className="rounded border border-slate-100 p-2 dark:border-slate-800"
              >
                <span className="mr-2 rounded bg-slate-100 px-1 text-xs dark:bg-slate-800">
                  {item.kind}
                </span>
                <span className="text-slate-500">{new Date(item.at).toLocaleString("ru-RU")}</span>
                <pre className="mt-1 max-h-24 overflow-auto text-xs">
                  {JSON.stringify(item.data, null, 1)}
                </pre>
              </li>
            ))}
            {timeline.data.items.length === 0 && <li className="text-slate-500">Пока пусто.</li>}
          </ul>
        )}
      </div>
    </div>
  );
}
