import client from "./client";

export interface PlatformInfo {
  id: string;
  label: string;
  builtin: boolean;
  managed: boolean;
}

export interface AccountItem {
  id: number;
  platform: string;
  account_key: string;
  kind: "builtin" | "managed";
  name: string;
  status: "active" | "expired" | "unknown" | "disabled";
  last_check_at: string | null;
  last_check_ok: boolean | null;
  last_check_message: string;
  extra: Record<string, unknown>;
}

export interface CheckResult {
  account: AccountItem;
  ok: boolean | null;
  message: string;
}

export const accountApi = {
  platforms: () =>
    client.get("/v1/accounts/platforms") as unknown as Promise<{ platforms: PlatformInfo[] }>,
  list: (platform?: string) =>
    client.get("/v1/accounts", { params: platform ? { platform } : {} }) as unknown as Promise<
      { accounts: AccountItem[] }
    >,
  create: (payload: {
    platform: string;
    account_key: string;
    name: string;
    credential?: string;
  }) => client.post("/v1/accounts", payload) as unknown as Promise<AccountItem>,
  update: (id: number, payload: { name?: string; status?: string }) =>
    client.patch(`/v1/accounts/${id}`, payload) as unknown as Promise<AccountItem>,
  check: (id: number) =>
    client.post(`/v1/accounts/${id}/check`) as unknown as Promise<CheckResult>,
  remove: (id: number) =>
    client.delete(`/v1/accounts/${id}`) as unknown as Promise<{
      deleted: boolean;
      module_credential_cleared: boolean;
    }>,
};
