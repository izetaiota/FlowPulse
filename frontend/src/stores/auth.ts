import { defineStore } from "pinia";
import { authApi } from "@/api/auth";

const TOKEN_KEY = "flowpulse_token";

/** 登录态：token 本地持久化（7 天有效期由后端签发控制） */
export const useAuthStore = defineStore("auth", {
  state: () => ({
    /** 鉴权是否启用（后端未配置 ADMIN_PASSWORD 时为 false，前端不拦截） */
    enabled: false,
    username: "",
    token: localStorage.getItem(TOKEN_KEY) || "",
    /** session 是否已探测（路由守卫等待它） */
    loaded: false,
  }),

  getters: {
    isLoggedIn: (state) => !state.enabled || !!state.token,
  },

  actions: {
    async loadSession() {
      const session = await authApi.getSession();
      this.enabled = session.enabled;
      if (!session.enabled) {
        this.token = "";
        localStorage.removeItem(TOKEN_KEY);
      }
      // 鉴权关闭时后端也返回部署配置的真实账号名，顶栏按真实账号展示
      this.username = session.username;
      this.loaded = true;
    },

    async login(username: string, password: string) {
      const result = await authApi.login(username, password);
      if (result.token) {
        this.token = result.token;
        this.username = result.username;
        localStorage.setItem(TOKEN_KEY, result.token);
      }
    },

    logout() {
      this.token = "";
      this.username = "";
      localStorage.removeItem(TOKEN_KEY);
    },
  },
});
