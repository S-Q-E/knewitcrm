import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";

export interface CurrentUser {
  id: string;
  email: string;
  name: string;
  role: "admin" | "manager";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<CurrentUser>("/api/auth/me", { noAuthRedirect: true }),
    retry: false,
    staleTime: 60_000,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; password: string }) =>
      api.post<CurrentUser>("/api/auth/login", input, { noAuthRedirect: true }),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/api/auth/logout"),
    onSettled: () => {
      queryClient.setQueryData(["me"], null);
      queryClient.clear();
    },
  });
}
