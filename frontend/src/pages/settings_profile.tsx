import { useState } from "react";

import { useMe } from "@/api/auth";
import {
  DEFAULT_PREFS,
  formatInTimezone,
  loadProfilePrefs,
  saveProfilePrefs,
  useChangePassword,
  useRevokeOtherSessions,
  useRevokeSession,
  useSessions,
  useUpdateProfile,
} from "@/api/settings";
import { toastError, useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { inputClass } from "@/pages/settings";

const TIMEZONES = ["Asia/Almaty", "Asia/Aqtobe", "Asia/Aqtau", "Europe/Moscow", "UTC"];

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="mb-3 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export function ProfileTab() {
  const me = useMe();
  const { push } = useToast();
  const [name, setName] = useState<string | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [prefs, setPrefs] = useState(loadProfilePrefs);
  const updateProfile = useUpdateProfile();
  const changePassword = useChangePassword();
  const sessions = useSessions();
  const revokeOne = useRevokeSession();
  const revokeOthers = useRevokeOtherSessions();

  const nameValue = name ?? me.data?.name ?? "";

  const saveName = async () => {
    try {
      await updateProfile.mutateAsync({ name: nameValue.trim() });
      setName(null);
      push({ title: "Имя обновлено", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  const savePassword = async () => {
    try {
      await changePassword.mutateAsync({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      push({ title: "Пароль изменён. Другие устройства вышли.", variant: "default" });
    } catch (error) {
      toastError(push, error);
    }
  };

  const savePrefs = (next: typeof prefs) => {
    setPrefs(next);
    saveProfilePrefs(next);
  };

  return (
    <div className="grid max-w-3xl gap-4">
      <Card title="Личные данные">
        <div className="flex flex-col gap-2">
          <p className="text-sm text-slate-500">
            {me.data?.email} · роль {me.data?.role === "admin" ? "администратор" : "менеджер"}
          </p>
          <div className="flex gap-2">
            <Input value={nameValue} onChange={(e) => setName(e.target.value)} aria-label="Имя" />
            <Button
              size="sm"
              disabled={updateProfile.isPending || !nameValue.trim() || nameValue === me.data?.name}
              onClick={() => void saveName()}
            >
              Сохранить
            </Button>
          </div>
        </div>
      </Card>

      <Card title="Смена пароля">
        <div className="flex flex-col gap-2">
          <Input
            type="password"
            placeholder="Текущий пароль"
            aria-label="Текущий пароль"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
          <Input
            type="password"
            placeholder="Новый пароль (минимум 10 символов)"
            aria-label="Новый пароль"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <div>
            <Button
              size="sm"
              disabled={changePassword.isPending || newPassword.length < 10 || !currentPassword}
              onClick={() => void savePassword()}
            >
              Сменить пароль
            </Button>
          </div>
        </div>
      </Card>

      <Card title="Отображение">
        <div className="flex flex-col gap-3">
          <label className="flex items-center gap-2 text-sm">
            Часовой пояс
            <select
              value={prefs.timezone}
              onChange={(e) => savePrefs({ ...prefs, timezone: e.target.value })}
              className={inputClass}
            >
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={prefs.sound}
              onChange={(e) => savePrefs({ ...prefs, sound: e.target.checked })}
            />
            Звук уведомлений
          </label>
          <button
            type="button"
            className="self-start text-xs text-slate-500 underline"
            onClick={() => savePrefs(DEFAULT_PREFS)}
          >
            Сбросить к значениям по умолчанию
          </button>
        </div>
      </Card>

      <Card title="Активные сессии">
        {sessions.isPending && <p className="text-sm text-slate-500">Загрузка…</p>}
        {sessions.data && (
          <div className="flex flex-col gap-2">
            {sessions.data.items.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate">
                    {item.user_agent || "Неизвестное устройство"}
                    {item.is_current && (
                      <span className="ml-2 rounded bg-emerald-100 px-1.5 text-xs text-emerald-800">
                        это устройство
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500">
                    {item.ip || "—"} · вход {formatInTimezone(item.created_at, prefs.timezone)}
                  </p>
                </div>
                {!item.is_current && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={revokeOne.isPending}
                    onClick={() =>
                      revokeOne.mutate(item.id, { onError: (e) => toastError(push, e) })
                    }
                  >
                    Выйти
                  </Button>
                )}
              </div>
            ))}
            {sessions.data.items.length > 1 && (
              <div>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={revokeOthers.isPending}
                  onClick={() =>
                    revokeOthers.mutate(undefined, {
                      onSuccess: (data) =>
                        push({ title: `Закрыто сессий: ${data.revoked}`, variant: "default" }),
                      onError: (e) => toastError(push, e),
                    })
                  }
                >
                  Выйти на других устройствах
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
