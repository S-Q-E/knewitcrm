import { useState } from "react";

import type { Deal } from "@/api/deals";
import { useCreateDeal, useContactSearch, useCreateNote, useLostReasons } from "@/api/deals";
import { useToast, toastError } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function ModalShell({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl dark:bg-slate-900"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-lg font-bold">{title}</h2>
        <div className="mt-3">{children}</div>
      </div>
    </div>
  );
}

export function LostReasonModal({
  onConfirm,
  onClose,
}: {
  onConfirm: (reasonId: string) => void;
  onClose: () => void;
}) {
  const reasons = useLostReasons();
  const [reasonId, setReasonId] = useState("");
  return (
    <ModalShell title="Причина отказа" onClose={onClose}>
      <select
        aria-label="Причина отказа"
        value={reasonId}
        onChange={(event) => setReasonId(event.target.value)}
        className="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
      >
        <option value="">Выберите причину…</option>
        {reasons.data?.items.map((reason) => (
          <option key={reason.id} value={reason.id}>
            {reason.name}
          </option>
        ))}
      </select>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button variant="danger" disabled={!reasonId} onClick={() => onConfirm(reasonId)}>
          Закрыть как отказ
        </Button>
      </div>
    </ModalShell>
  );
}

export function WonConfirmModal({
  onConfirm,
  onClose,
}: {
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <ModalShell title="Подтверждение продажи" onClose={onClose}>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Перенести сделку в «Клиент»? Сделка будет закрыта как выигранная.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button onClick={onConfirm}>Подтвердить</Button>
      </div>
    </ModalShell>
  );
}

export function NoteModal({ deal, onClose }: { deal: Deal; onClose: () => void }) {
  const { push } = useToast();
  const createNote = useCreateNote();
  const [body, setBody] = useState("");
  const save = async () => {
    if (!body.trim()) {
      return;
    }
    try {
      await createNote.mutateAsync({ deal_id: deal.id, body: body.trim() });
      onClose();
      push({ title: "Заметка сохранена", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };
  return (
    <ModalShell title="Новая заметка" onClose={onClose}>
      <textarea
        aria-label="Текст заметки"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        rows={4}
        className="w-full rounded-md border border-slate-200 bg-white p-2 text-sm dark:border-slate-700 dark:bg-slate-900"
      />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button onClick={() => void save()} disabled={createNote.isPending || !body.trim()}>
          Сохранить
        </Button>
      </div>
    </ModalShell>
  );
}

export function CreateDealModal({
  stageId,
  pipelineId,
  onClose,
}: {
  stageId: string;
  pipelineId: string;
  onClose: () => void;
}) {
  const { push } = useToast();
  const createDeal = useCreateDeal();
  const [term, setTerm] = useState("");
  const [contactId, setContactId] = useState("");
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const search = useContactSearch(term);

  const save = async () => {
    if (!contactId || !title.trim()) {
      return;
    }
    try {
      await createDeal.mutateAsync({
        contact_id: contactId,
        pipeline_id: pipelineId,
        stage_id: stageId,
        title: title.trim(),
        amount: amount ? Number(amount) : null,
      });
      onClose();
      push({ title: "Сделка создана", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title="Быстрая сделка" onClose={onClose}>
      <label className="block text-sm font-medium">
        Контакт (поиск от 2 букв)
        <Input
          className="mt-1"
          value={term}
          onChange={(event) => {
            setTerm(event.target.value);
            setContactId("");
          }}
          placeholder="Имя, телефон, whatsapp"
        />
      </label>
      {search.data && search.data.items.length > 0 && !contactId && (
        <ul className="mt-1 max-h-32 overflow-y-auto rounded-md border border-slate-200 dark:border-slate-700">
          {search.data.items.map((contact) => (
            <li key={contact.id}>
              <button
                type="button"
                className="w-full px-2 py-1 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
                onClick={() => {
                  setContactId(contact.id);
                  setTerm(contact.name ?? contact.phone ?? contact.id);
                }}
              >
                {contact.name ?? contact.phone ?? contact.id}
              </button>
            </li>
          ))}
        </ul>
      )}
      <label className="mt-3 block text-sm font-medium">
        Название
        <Input className="mt-1" value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label className="mt-3 block text-sm font-medium">
        Сумма, ₸
        <Input
          className="mt-1"
          type="number"
          min="0"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button
          onClick={() => void save()}
          disabled={createDeal.isPending || !contactId || !title.trim()}
        >
          Создать
        </Button>
      </div>
    </ModalShell>
  );
}
