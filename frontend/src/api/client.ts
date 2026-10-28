import axios from "axios";

/** 后端 API 客户端：开发环境经 vite 代理，生产环境同源 /api */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 15000,
});

const TOKEN_KEY = "flowpulse_token";

client.interceptors.request.use((config) => {
  // 登录态：统一注入 Bearer Token（后端未启用鉴权时服务端忽略）
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let redirectingToLogin = false;

client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 登录过期/未登录：清理本地 token 并跳登录页（登录接口自身的 401 不跳转）
    const status = error?.response?.status;
    const url: string = error?.config?.url || "";
    if (status === 401 && !url.includes("/auth/login") && !redirectingToLogin) {
      localStorage.removeItem(TOKEN_KEY);
      redirectingToLogin = true;
      const redirect = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?redirect=${redirect}`;
    }
    console.error("[FlowPulse API]", error?.response?.data ?? error.message);
    return Promise.reject(error);
  },
);

export default client;
