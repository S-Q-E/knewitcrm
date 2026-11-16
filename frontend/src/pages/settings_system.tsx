import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useUsersLite } from "@/api/deals";
import type { AdminUser, Automation } from "@/api/settings";
import {
  formatInTimezone,
  loadProfilePrefs,
  useActivity,
  useActivityMeta,
  useAdminUsers,
  useAutomations,
  useCreateAutomation,
  useCreateUser,
  useDeleteAutomation,
  useInstanceSettings,
  useIntegrations,
  useOutboxJournal,
  useUpdateAutomation,
  useUpdateSettings,
  useUpdateUser,
} from "@/api/settings";
import { useRetryOutbox } from "@/api/timeline";
import { toastError, useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FieldLabel, ModalShell, inputClass } from "@/pages/settings";
import { cn } from "@/lib/utils";

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

// Users

function UserModal({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const { push } = useToast();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const [email, setEmail] = useState("");
  const [name, setName] = useState(user?.name ?? "");
  const [role, setRole] = useState<"admin" | "manager">(user?.role ?? "manager");
  const [password, setPassword] = useState("");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);

  const save = async () => {
    try {
      if (user) {
        const patch: Record<string, unknown> = { name: name.trim(), role, is_active: isActive };
        if (password) patch.password = password;
        await updateUser.mutateAsync({ id: user.id, patch });
      } else {
        await createUser.mutateAsync({ email: email.trim(), name: name.trim(), password, role });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={user ? "User" : "New user"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        {!user && (
          <FieldLabel>
            Email
            <Input value={email} onChange={(e) => setEmail(e.target.value)} />
          </FieldLabel>
        )}
        <FieldLabel>
          Name
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </FieldLabel>
        <div className="flex gap-3">
          <FieldLabel>
            Role
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "manager")}
              className={inputClass}
            >
              <option value="manager">Manager</option>
              <option value="admin">Administrator</option>
            </select>
          </FieldLabel>
          <label className="flex items-end gap-2 pb-2 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            Active
          </label>
        </div>
        <FieldLabel>
          {user ? "New password (reset, at least 10 characters)" : "Password (at least 10 characters)"}
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={user ? "Leave blank to keep unchanged" : ""}
          />
        </FieldLabel>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={
              !name.trim() ||
              (!user && (!email.trim() || password.length < 10)) ||
              (password.length > 0 && password.length < 10)
            }
            onClick={() => void save()}
          >
            Save
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

const PAGE_SIZE = 50;

export function UsersTab() {
  const [offset, setOffset] = useState(0);
  const [modal, setModal] = useState<AdminUser | "create" | null>(null);
  const users = useAdminUsers(offset, PAGE_SIZE);
  const total = users.data?.total ?? 0;

  return (
    <Card
      title="Users"
      actions={
        <Button size="sm" onClick={() => setModal("create")}>
          New user
        </Button>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500 dark:border-slate-700">
              <th className="px-2 py-1.5 font-medium">Name</th>
              <th className="px-2 py-1.5 font-medium">Email</th>
              <th className="px-2 py-1.5 font-medium">Role</th>
              <th className="px-2 py-1.5 font-medium">Status</th>
              <th className="px-2 py-1.5 font-medium">Last sign-in</th>
              <th className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {(users.data?.items ?? []).map((user) => (
              <tr key={user.id} className="border-b border-slate-100 dark:border-slate-800">
                <td className="px-2 py-1.5 font-medium">{user.name}</td>
                <td className="px-2 py-1.5">{user.email}</td>
                <td className="px-2 py-1.5">
                  {user.role === "admin" ? "Administrator" : "Manager"}
                </td>
                <td className="px-2 py-1.5">{user.is_active ? "Active" : "Disabled"}</td>
                <td className="px-2 py-1.5 text-slate-500">
                  {user.last_login_at
                    ? formatInTimezone(user.last_login_at, loadProfilePrefs().timezone)
                    : "—"}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <Button size="sm" variant="secondary" onClick={() => setModal(user)}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between">
        <Button
          size="sm"
          variant="secondary"
          disabled={offset === 0}
          onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
        >
          Back
        </Button>
        <span className="text-xs text-slate-500">
          {offset + 1}–{offset + (users.data?.items.length ?? 0)} of {total}
        </span>
        <Button
          size="sm"
          variant="secondary"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
        >
          Next
        </Button>
      </div>
      {modal && (
        <UserModal user={modal === "create" ? null : modal} onClose={() => setModal(null)} />
      )}
    </Card>
  );
}

// Automation + distribution

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-md border border-slate-100 px-3 py-2 text-sm dark:border-slate-800">
      <input
        type="checkbox"
        className="mt-1"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="font-medium">{label}</span>
        <br />
        <span className="text-xs text-slate-500">{hint}</span>
      </span>
    </label>
  );
}

function AutomationModal({
  automation,
  onClose,
}: {
  automation: Automation | null;
  onClose: () => void;
}) {
  const { push } = useToast();
  const createAutomation = useCreateAutomation();
  const updateAutomation = useUpdateAutomation();
  const [name, setName] = useState(automation?.name ?? "");
  const [trigger, setTrigger] = useState(automation?.trigger_type ?? "deal_entered_stage");
  const config = (automation?.trigger_config ?? {}) as Record<string, string | number>;
  const [stageId, setStageId] = useState(String(config.stage_id ?? ""));
  const [hours, setHours] = useState(String(config.hours ?? 24));
  const [pipelineId, setPipelineId] = useState(String(config.pipeline_id ?? ""));
  const [isActive, setIsActive] = useState(automation?.is_active ?? true);
  const [actionsText, setActionsText] = useState(
    automation
      ? JSON.stringify(automation.actions, null, 2)
      : '[\n  {"type": "notify", "text": "..."}\n]',
  );

  const save = async () => {
    let actions: unknown;
    try {
      actions = JSON.parse(actionsText) as unknown;
    } catch {
      push({ title: "Actions: invalid JSON", variant: "error" });
      return;
    }
    if (!Array.isArray(actions)) {
      push({ title: "Actions must be a JSON array", variant: "error" });
      return;
    }
    const trigger_config: Record<string, unknown> =
      trigger === "deal_entered_stage"
        ? {
            ...(pipelineId ? { pipeline_id: pipelineId } : {}),
            ...(stageId ? { stage_id: stageId } : {}),
          }
        : { hours: Number(hours) || 24 };
    try {
      if (automation) {
        await updateAutomation.mutateAsync({
          id: automation.id,
          patch: {
            name: name.trim(),
            trigger_type: trigger,
            trigger_config,
            actions,
            is_active: isActive,
          },
        });
      } else {
        await createAutomation.mutateAsync({
          name: name.trim(),
          trigger_type: trigger,
          trigger_config,
          actions,
          is_active: isActive,
        });
      }
      onClose();
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <ModalShell title={automation ? "Rule" : "New rule"} onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        <FieldLabel>
          Title
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </FieldLabel>
        <div className="flex gap-3">
          <FieldLabel>
            Trigger
            <select
              value={trigger}
              onChange={(e) => setTrigger(e.target.value as Automation["trigger_type"])}
              className={inputClass}
            >
              <option value="deal_entered_stage">Deal entered a stage</option>
              <option value="no_activity_hours">No activity for N hours</option>
            </select>
          </FieldLabel>
          {trigger === "deal_entered_stage" ? (
            <>
              <FieldLabel>
                Pipeline ID (optional)
                <Input
                  value={pipelineId}
                  onChange={(e) => setPipelineId(e.target.value)}
                  placeholder="uuid"
                />
              </FieldLabel>
              <FieldLabel>
                Stage ID (optional)
                <Input
                  value={stageId}
                  onChange={(e) => setStageId(e.target.value)}
                  placeholder="uuid"
                />
              </FieldLabel>
            </>
          ) : (
            <FieldLabel>
              Hours without activity
              <Input value={hours} inputMode="numeric" onChange={(e) => setHours(e.target.value)} />
            </FieldLabel>
          )}
        </div>
        <FieldLabel>
          Actions (JSON array: create_task, assign_owner, add_tag, notify)
          <textarea
            value={actionsText}
            onChange={(e) => setActionsText(e.target.value)}
            rows={6}
            spellCheck={false}
            className={cn(inputClass, "h-auto py-2 font-mono text-xs")}
          />
        </FieldLabel>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
          />
          Rule enabled
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!name.trim()} onClick={() => void save()}>
            Save
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

export function AutomationTab() {
  const { push } = useToast();
  const settings = useInstanceSettings();
  const updateSettings = useUpdateSettings();
  const automations = useAutomations();
  const deleteAutomation = useDeleteAutomation();
  const [modal, setModal] = useState<Automation | "create" | null>(null);

  const data = settings.data;
  const set = (patch: Record<string, unknown>) => {
    updateSettings.mutate(patch, { onError: (error) => toastError(push, error) });
  };

  const remove = async (automation: Automation) => {
    if (!window.confirm(`Delete rule “${automation.name}”?`)) return;
    try {
      await deleteAutomation.mutateAsync(automation.id);
    } catch (error) {
      toastError(push, error);
    }
  };

  return (
    <div className="grid gap-4">
      <Card title="Assignment and bot">
        {!data ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">New deals</p>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="assignment"
                  checked={data.deal_assignment_mode === "unassigned"}
                  onChange={() => set({ deal_assignment_mode: "unassigned" })}
                />
                Unassigned
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="assignment"
                  checked={data.deal_assignment_mode === "round_robin"}
                  onChange={() => set({ deal_assignment_mode: "round_robin" })}
                />
                Round-robin between managers
              </label>
            </div>
            <Toggle
              label="Auto-pause bot on manager handover"
              hint="The MANAGER status pauses the dialog and creates an urgent task"
              checked={data.auto_pause_on_manager}
              onChange={(value) => set({ auto_pause_on_manager: value })}
            />
            <Toggle
              label="Auto-pause on manual reply"
              hint="A manager message pauses the bot so it does not interfere with the dialog"
              checked={data.auto_pause_on_manual_reply}
              onChange={(value) => set({ auto_pause_on_manual_reply: value })}
            />
            <Toggle
              label="Managers see only their own records"
              hint="Restrict access to other users' deals, contacts and dialogs"
              checked={data.restrict_managers_to_own}
              onChange={(value) => set({ restrict_managers_to_own: value })}
            />
            <Toggle
              label="Analytics visible to managers"
              hint="Turn off to make Analytics available to administrators only"
              checked={data.analytics_managers_visible}
              onChange={(value) => set({ analytics_managers_visible: value })}
            />
          </div>
        )}
      </Card>

      <Card
        title="Automation rules"
        actions={
          <Button size="sm" onClick={() => setModal("create")}>
            New rule
          </Button>
        }
      >
        <div className="flex flex-col gap-1.5">
          {(automations.data ?? []).map((automation) => (
            <div
              key={automation.id}
              className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
            >
              <span
                className={cn(
                  "rounded px-1.5 text-xs",
                  automation.is_active
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-slate-100 text-slate-500",
                )}
              >
                {automation.is_active ? "on" : "off"}
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{automation.name}</p>
                <p className="truncate text-xs text-slate-500">
                  {automation.trigger_type === "deal_entered_stage"
                    ? "Stage entered"
                    : "No activity"}{" "}
                  · actions: {automation.actions.length}
                </p>
              </div>
              <Button size="sm" variant="secondary" onClick={() => setModal(automation)}>
                Edit
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void remove(automation)}>
                Delete
              </Button>
            </div>
          ))}
          {automations.data?.length === 0 && (
            <p className="text-sm text-slate-500">No rules yet</p>
          )}
        </div>
      </Card>

      {modal && (
        <AutomationModal
          automation={modal === "create" ? null : modal}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}

// Integrations

export function IntegrationsTab() {
  const { push } = useToast();
  const queryClient = useQueryClient();
  const integrations = useIntegrations();
  const retry = useRetryOutbox();
  const [outboxStatus, setOutboxStatus] = useState("failed");
  const [outboxOffset, setOutboxOffset] = useState(0);
  const journal = useOutboxJournal(outboxStatus, outboxOffset, 20);
  const data = integrations.data;

  return (
    <div className="grid gap-4">
      <Card
        title="Connections"
        actions={
          <Button size="sm" variant="secondary" onClick={() => void integrations.refetch()}>
            Check
          </Button>
        }
      >
        {integrations.isPending && <p className="text-sm text-slate-500">Checking…</p>}
        {data && (
          <div className="grid gap-2 md:grid-cols-2">
            <div className="rounded-md border border-slate-100 p-3 text-sm dark:border-slate-800">
              <p className="font-medium">
                Bot database{" "}
                <span className={cn(data.bot_db_ok ? "text-emerald-600" : "text-red-600")}>
                  {data.bot_db_ok ? "● connected" : "● unavailable"}
                </span>
              </p>
              {data.bot_db_ok ? (
                <p className="mt-1 text-xs text-slate-500">
                  Latency {data.bot_db_latency_ms} ms · leads {data.leads_count} · messages{" "}
                  {data.messages_count} · events {data.events_count}
                </p>
              ) : (
                <p className="mt-1 text-xs text-red-600">Error: {data.bot_db_error}</p>
              )}
            </div>
            <div className="rounded-md border border-slate-100 p-3 text-sm dark:border-slate-800">
              <p className="font-medium">
                n8n (chat delivery){" "}
                <span className={cn(data.n8n_configured ? "text-emerald-600" : "text-amber-600")}>
                  {data.n8n_configured ? "● configured" : "● not configured"}
                </span>
              </p>
              <p className="mt-1 break-all font-mono text-xs text-slate-500">
                {data.n8n_webhook_url ?? "Webhook URL is not set (N8N_SEND_WEBHOOK_URL)"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Queue: {data.outbox_queued} · sending {data.outbox_sending} · sent{" "}
                {data.outbox_sent} · errors {data.outbox_failed}
              </p>
            </div>
          </div>
        )}
      </Card>

      <Card title="Delivery journal">
        <div className="mb-2 flex gap-1">
          {["failed", "queued", "sending", "sent"].map((status) => (
            <Button
              key={status}
              size="sm"
              variant={outboxStatus === status ? "default" : "secondary"}
              onClick={() => {
                setOutboxStatus(status);
                setOutboxOffset(0);
              }}
            >
              {status === "failed"
                ? "Errors"
                : status === "queued"
                  ? "Queued"
                  : status === "sending"
                    ? "Sending"
                    : "Sent"}
            </Button>
          ))}
        </div>
        <div className="flex flex-col gap-1.5">
          {(journal.data?.items ?? []).map((item) => (
            <div
              key={item.id}
              className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate">
                  <span className="font-mono text-xs">{item.whatsapp_id}</span> · {item.body}
                </p>
                <p className="text-xs text-slate-500">
                  {item.sent_by_name ?? "—"} ·{" "}
                  {formatInTimezone(item.created_at, loadProfilePrefs().timezone)}
                  {item.error && <span className="text-red-600"> · {item.error}</span>}
                </p>
              </div>
              {item.status === "failed" && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={retry.isPending}
                  onClick={() =>
                    retry.mutate(
                      { outbox_id: item.id, whatsapp_id: item.whatsapp_id },
                      {
                        onSuccess: () => {
                          void queryClient.invalidateQueries({ queryKey: ["outbox-journal"] });
                          void queryClient.invalidateQueries({
                            queryKey: ["settings", "integrations"],
                          });
                        },
                        onError: (error) => toastError(push, error),
                      },
                    )
                  }
                >
                  Retry
                </Button>
              )}
            </div>
          ))}
          {journal.data?.items.length === 0 && (
            <p className="text-sm text-slate-500">No records</p>
          )}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <Button
            size="sm"
            variant="secondary"
            disabled={outboxOffset === 0}
            onClick={() => setOutboxOffset((o) => Math.max(0, o - 20))}
          >
            Back
          </Button>
          <span className="text-xs text-slate-500">Total: {journal.data?.total ?? 0}</span>
          <Button
            size="sm"
            variant="secondary"
            disabled={outboxOffset + 20 >= (journal.data?.total ?? 0)}
            onClick={() => setOutboxOffset((o) => o + 20)}
          >
            Next
          </Button>
        </div>
      </Card>
    </div>
  );
}

// Activity journal

export function ActivityTab() {
  const users = useUsersLite();
  const meta = useActivityMeta();
  const [filters, setFilters] = useState({
    actor_id: "",
    entity: "",
    action: "",
    date_from: "",
    date_to: "",
  });
  const [offset, setOffset] = useState(0);
  const activity = useActivity(
    useMemo(
      () => ({
        ...(filters.actor_id ? { actor_id: filters.actor_id } : {}),
        ...(filters.entity ? { entity: filters.entity } : {}),
        ...(filters.action ? { action: filters.action } : {}),
        ...(filters.date_from ? { date_from: `${filters.date_from}T00:00:00` } : {}),
        ...(filters.date_to ? { date_to: `${filters.date_to}T23:59:59` } : {}),
      }),
      [filters],
    ),
    offset,
    50,
  );
  const timezone = loadProfilePrefs().timezone;

  const apply = (patch: Partial<typeof filters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setOffset(0);
  };

  return (
    <Card title="Activity log">
      <div className="mb-3 grid gap-2 md:grid-cols-5">
        <select
          aria-label="User"
          value={filters.actor_id}
          onChange={(e) => apply({ actor_id: e.target.value })}
          className={inputClass}
        >
          <option value="">All users</option>
          {(users.data?.items ?? []).map((user) => (
            <option key={user.id} value={user.id}>
              {user.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Entity"
          value={filters.entity}
          onChange={(e) => apply({ entity: e.target.value })}
          className={inputClass}
        >
          <option value="">All entities</option>
          {(meta.data?.entities ?? []).map((entity) => (
            <option key={entity} value={entity}>
              {entity}
            </option>
          ))}
        </select>
        <Input
          placeholder="Action contains…"
          aria-label="Action"
          value={filters.action}
          onChange={(e) => apply({ action: e.target.value })}
        />
        <Input
          type="date"
          aria-label="Date from"
          value={filters.date_from}
          onChange={(e) => apply({ date_from: e.target.value })}
        />
        <Input
          type="date"
          aria-label="Date to"
          value={filters.date_to}
          onChange={(e) => apply({ date_to: e.target.value })}
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500 dark:border-slate-700">
              <th className="px-2 py-1.5 font-medium">Time</th>
              <th className="px-2 py-1.5 font-medium">Who</th>
              <th className="px-2 py-1.5 font-medium">Entity</th>
              <th className="px-2 py-1.5 font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {(activity.data?.items ?? []).map((item) => (
              <tr key={item.id} className="border-b border-slate-100 dark:border-slate-800">
                <td className="whitespace-nowrap px-2 py-1.5 text-xs text-slate-500">
                  {formatInTimezone(item.created_at, timezone)}
                </td>
                <td className="px-2 py-1.5">{item.actor_name ?? "System"}</td>
                <td className="px-2 py-1.5 font-mono text-xs">{item.entity}</td>
                <td className="px-2 py-1.5 font-mono text-xs">{item.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(activity.data?.items.length ?? 0) === 0 && (
          <p className="py-4 text-center text-sm text-slate-500">No records</p>
        )}
      </div>
      <div className="mt-3 flex items-center justify-between">
        <Button
          size="sm"
          variant="secondary"
          disabled={offset === 0}
          onClick={() => setOffset((o) => Math.max(0, o - 50))}
        >
          Back
        </Button>
        <span className="text-xs text-slate-500">Total: {activity.data?.total ?? 0}</span>
        <Button
          size="sm"
          variant="secondary"
          disabled={offset + 50 >= (activity.data?.total ?? 0)}
          onClick={() => setOffset((o) => o + 50)}
        >
          Next
        </Button>
      </div>
    </Card>
  );
}
