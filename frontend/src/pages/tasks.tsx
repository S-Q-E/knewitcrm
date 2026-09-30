import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import type { Task } from "@/api/tasks";
import {
  useCompleteTask,
  useCreateTaskFull,
  useDeleteTask,
  useTasks,
  useUpdateTask,
} from "@/api/tasks";
import { useUsersLite } from "@/api/deals";
import { useToast, toastError } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const taskSchema = z.object({
  title: z.string().min(1, "Введите название").max(255),
  type: z.enum(["call", "meeting", "message", "other"]),
  assignee_id: z.string().optional(),
  due_at: z.string().optional(),
});

type TaskForm = z.infer<typeof taskSchema>;

const TYPE_LABEL: Record<string, string> = {
  call: "Звонок",
  meeting: "Встреча",
  message: "Написать",
  other: "Другое",
};

function dayKey(iso: string | null | undefined): string | null {
  if (!iso) {
    return null;
  }
  return iso.slice(0, 10);
}

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

function addDaysKey(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

function TaskModal({ task, onClose }: { task?: Task; onClose: () => void }) {
  const { push } = useToast();
  const users = useUsersLite();
  const createTask = useCreateTaskFull();
  const updateTask = useUpdateTask();
  const form = useForm<TaskForm>({
    resolver: zodResolver(taskSchema),
    defaultValues: {
      title: task?.title ?? "",
      type: (task?.type as TaskForm["type"]) ?? "other",
      assignee_id: task?.assignee_id ?? "",
      due_at: task?.due_at ? task.due_at.slice(0, 16) : "",
    },
  });

  const save = async (values: TaskForm) => {
    try {
      if (task) {
        await updateTask.mutateAsync({
          id: task.id,
          patch: {
            title: values.title,
            type: values.type,
            assignee_id: values.assignee_id || null,
            due_at: values.due_at || null,
          },
        });
      } else {
        await createTask.mutateAsync({
          title: values.title,
          type: values.type,
          assignee_id: values.assignee_id || null,
          due_at: values.due_at || null,
        });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={task ? "Редактировать задачу" : "Новая задача"}
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <form
        onSubmit={form.handleSubmit((values) => void save(values))}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-md rounded-lg bg-white p-5 dark:bg-slate-900"
      >
        <h2 className="text-lg font-bold">{task ? "Редактировать задачу" : "Новая задача"}</h2>
        <label className="mt-3 block text-sm font-medium">
          Название
          <Input className="mt-1" {...form.register("title")} />
          {form.formState.errors.title && (
            <span className="text-xs text-red-600">{form.formState.errors.title.message}</span>
          )}
        </label>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <label className="block text-sm font-medium">
            Тип
            <select
              {...form.register("type")}
              className="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              {Object.entries(TYPE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium">
            Срок
            <Input className="mt-1" type="datetime-local" {...form.register("due_at")} />
          </label>
        </div>
        <label className="mt-3 block text-sm font-medium">
          Исполнитель
          <select
            {...form.register("assignee_id")}
            className="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Без исполнителя</option>
            {users.data?.items.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </select>
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" type="button" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" disabled={createTask.isPending || updateTask.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </div>
  );
}

function TaskRow({ task, onEdit }: { task: Task; onEdit: (task: Task) => void }) {
  const navigate = useNavigate();
  const complete = useCompleteTask();
  const remove = useDeleteTask();
  const { push } = useToast();
  const done = task.done_at !== null;
  const overdue = !done && task.due_at !== null && new Date(task.due_at) < new Date();

  return (
    <div
      data-task-row={task.id}
      className={cn(
        "flex items-center gap-2 rounded-lg border p-2 text-sm",
        overdue
          ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
      )}
    >
      <input
        type="checkbox"
        aria-label={done ? `Вернуть ${task.title}` : `Выполнить ${task.title}`}
        checked={done}
        onChange={() =>
          complete.mutate(
            { id: task.id, done: !done },
            { onError: (error) => toastError(push, error) },
          )
        }
      />
      <div className="min-w-0 flex-1">
        <p className={cn("truncate font-medium", done && "line-through")}>{task.title}</p>
        <p className="text-xs text-slate-500">
          {TYPE_LABEL[task.type] ?? task.type}
          {task.due_at ? ` · до ${formatDate(task.due_at)}` : ""}
          {overdue ? " · просрочена" : ""}
        </p>
      </div>
      {task.deal_id && (
        <button
          type="button"
          className="shrink-0 text-xs text-slate-500 underline"
          onClick={() => navigate(`/deals/${task.deal_id}`)}
        >
          Сделка
        </button>
      )}
      <button
        type="button"
        className="shrink-0 text-xs text-slate-500 underline"
        onClick={() => onEdit(task)}
      >
        Изменить
      </button>
      <button
        type="button"
        aria-label={`Удалить ${task.title}`}
        className="shrink-0 text-xs text-slate-400 hover:text-red-600"
        onClick={() => remove.mutate(task.id, { onError: (error) => toastError(push, error) })}
      >
        ×
      </button>
    </div>
  );
}

export function TasksPage() {
  const [view, setView] = useState<"groups" | "week">("groups");
  const [editing, setEditing] = useState<Task | undefined>(undefined);
  const [creating, setCreating] = useState(false);
  const openTasks = useTasks({ open_only: true });
  const doneTasks = useTasks({});

  const open = (openTasks.data?.items ?? []).filter((task) => task.done_at === null);
  const done = (doneTasks.data?.items ?? []).filter((task) => task.done_at !== null).slice(0, 50);
  const today = todayKey();
  const tomorrow = addDaysKey(1);
  const isOverdue = (task: Task) => task.due_at !== null && new Date(task.due_at) < new Date();
  const overdue = open.filter((task) => isOverdue(task));
  const dueToday = open.filter((task) => !isOverdue(task) && dayKey(task.due_at) === today);
  const dueTomorrow = open.filter((task) => !isOverdue(task) && dayKey(task.due_at) === tomorrow);
  const later = open.filter(
    (task) => !isOverdue(task) && (!task.due_at || (dayKey(task.due_at) as string) > tomorrow),
  );

  const weekDays = Array.from({ length: 7 }, (_, index) => {
    const key = addDaysKey(index - 1);
    return {
      key,
      label: new Date(`${key}T00:00:00`).toLocaleDateString("ru-RU", {
        weekday: "short",
        day: "numeric",
        month: "short",
      }),
      tasks: open.filter((task) => dayKey(task.due_at) === key),
    };
  });

  const group = (title: string, tasks: Task[]) => (
    <section aria-label={title} role="region">
      <h2 className="mb-1 text-sm font-bold uppercase tracking-wide text-slate-500">
        {title} ({tasks.length})
      </h2>
      <div className="flex flex-col gap-1.5">
        {tasks.map((task) => (
          <TaskRow key={task.id} task={task} onEdit={setEditing} />
        ))}
        {tasks.length === 0 && <p className="text-xs text-slate-400">Пусто.</p>}
      </div>
    </section>
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-slate-200 dark:border-slate-700">
          {(["groups", "week"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setView(mode)}
              className={cn(
                "px-3 py-1.5 text-sm",
                view === mode
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "text-slate-600 dark:text-slate-300",
              )}
            >
              {mode === "groups" ? "Списки" : "Неделя"}
            </button>
          ))}
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          Новая задача
        </Button>
      </div>

      {view === "groups" ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {group("Просрочено", overdue)}
          {group("Сегодня", dueToday)}
          {group("Завтра", dueTomorrow)}
          {group("Позже", later)}
          {group("Выполнено", done)}
        </div>
      ) : (
        <div className="grid gap-2 md:grid-cols-7">
          {weekDays.map((day) => (
            <section
              key={day.key}
              aria-label={day.label}
              className="rounded-lg border border-slate-200 bg-white p-2 dark:border-slate-800 dark:bg-slate-900"
            >
              <h2 className="mb-1 text-xs font-bold">{day.label}</h2>
              <div className="flex flex-col gap-1">
                {day.tasks.map((task) => (
                  <TaskRow key={task.id} task={task} onEdit={setEditing} />
                ))}
                {day.tasks.length === 0 && <p className="text-[11px] text-slate-400">—</p>}
              </div>
            </section>
          ))}
        </div>
      )}

      {(creating || editing !== undefined) && (
        <TaskModal
          task={editing}
          onClose={() => {
            setCreating(false);
            setEditing(undefined);
          }}
        />
      )}
    </div>
  );
}
