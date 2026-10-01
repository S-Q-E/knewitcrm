import { useState } from "react";

import { useMe } from "@/api/auth";
import { ForbiddenPage } from "@/pages/stubs";
import { ActivityTab } from "@/pages/settings_system";
import { FieldsTab, FunnelsTab, RepliesTab, TagsTab } from "@/pages/settings_catalog";
import { AutomationTab, IntegrationsTab, UsersTab } from "@/pages/settings_system";
import { ProfileTab } from "@/pages/settings_profile";
import { cn } from "@/lib/utils";

export const inputClass =
  "h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900";

export function ModalShell({
  title,
  children,
  onClose,
  wide,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
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
        className={cn(
          "max-h-[90vh] w-full overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-slate-900",
          wide ? "max-w-2xl" : "max-w-md",
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-lg font-bold">{title}</h2>
        <div className="mt-3">{children}</div>
      </div>
    </div>
  );
}

export function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-600 dark:text-slate-300">{children}</span>
    </label>
  );
}

type AdminTabId =
  "funnels" | "fields" | "tags" | "users" | "replies" | "automation" | "integrations" | "activity";

const ADMIN_TABS: { id: AdminTabId; label: string }[] = [
  { id: "funnels", label: "Воронки" },
  { id: "fields", label: "Поля" },
  { id: "tags", label: "Теги" },
  { id: "users", label: "Пользователи" },
  { id: "replies", label: "Шаблоны" },
  { id: "automation", label: "Автоматизация" },
  { id: "integrations", label: "Интеграции" },
  { id: "activity", label: "Журнал" },
];

export function SettingsPage() {
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const [tab, setTab] = useState<AdminTabId | "profile">("profile");

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold">Настройки</h1>
      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          onClick={() => setTab("profile")}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm",
            tab === "profile"
              ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
              : "bg-white text-slate-600 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300",
          )}
        >
          Профиль
        </button>
        {isAdmin &&
          ADMIN_TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm",
                tab === item.id
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-white text-slate-600 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300",
              )}
            >
              {item.label}
            </button>
          ))}
      </div>

      {tab === "profile" && <ProfileTab />}
      {tab !== "profile" && !isAdmin && <ForbiddenPage />}
      {tab !== "profile" && isAdmin && (
        <div className="flex flex-col gap-4">
          {tab === "funnels" && <FunnelsTab />}
          {tab === "fields" && <FieldsTab />}
          {tab === "tags" && <TagsTab />}
          {tab === "users" && <UsersTab />}
          {tab === "replies" && <RepliesTab />}
          {tab === "automation" && <AutomationTab />}
          {tab === "integrations" && <IntegrationsTab />}
          {tab === "activity" && <ActivityTab />}
        </div>
      )}
    </div>
  );
}
