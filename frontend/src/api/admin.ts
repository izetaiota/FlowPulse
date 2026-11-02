import client from "./client";

export interface AdminUser {
  id: number;
  username: string;
  status: "active" | "disabled";
  roles: string[];
  created_at: string;
}

export interface AdminRole {
  id: number;
  code: string;
  name: string;
  remark: string;
  status: "active" | "disabled";
  perms: string[];
  users: string[];
}

export const adminApi = {
  listUsers: () => client.get("/admin/users") as unknown as Promise<{ users: AdminUser[] }>,
  createUser: (payload: { username: string; password: string; roles?: string[] }) =>
    client.post("/admin/users", payload) as unknown as Promise<{ username: string; created: boolean }>,
  updateUser: (username: string, payload: { password?: string; roles?: string[]; status?: string }) =>
    client.put(`/admin/users/${username}`, payload) as unknown as Promise<{ username: string; updated: boolean }>,
  deleteUser: (username: string) =>
    client.delete(`/admin/users/${username}`) as unknown as Promise<{ deleted: boolean }>,

  listRoles: () => client.get("/admin/roles") as unknown as Promise<{ roles: AdminRole[] }>,
  createRole: (payload: { code: string; name?: string; remark?: string; perms?: string[] }) =>
    client.post("/admin/roles", payload) as unknown as Promise<{ code: string; created: boolean }>,
  updateRole: (code: string, payload: { name?: string; remark?: string; perms?: string[]; status?: string }) =>
    client.put(`/admin/roles/${code}`, payload) as unknown as Promise<{ code: string; updated: boolean }>,
  deleteRole: (code: string) =>
    client.delete(`/admin/roles/${code}`) as unknown as Promise<{ deleted: boolean }>,

  listPermCodes: () =>
    client.get("/admin/perm-codes") as unknown as Promise<{ codes: string[] }>,
};
