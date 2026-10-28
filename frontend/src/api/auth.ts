import client from "./client";

export interface AuthSession {
  enabled: boolean;
  username: string;
}

export interface LoginResult {
  token: string;
  username: string;
  expires_at: number;
  message?: string;
}

export const authApi = {
  getSession: () => client.get<AuthSession>("/auth/session") as unknown as Promise<AuthSession>,
  login: (username: string, password: string) =>
    client.post<LoginResult>("/auth/login", { username, password }) as unknown as Promise<LoginResult>,
};
