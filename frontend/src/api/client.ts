import axios from "axios";

/** 后端 API 客户端：开发环境经 vite 代理，生产环境同源 /api */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 15000,
});

client.interceptors.request.use((config) => {
  // TODO: 后端接入登录态后，在此统一注入 token
  return config;
});

client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 统一错误出口：后续接入 ElMessage / 日志上报
    console.error("[FlowPulse API]", error?.response?.data ?? error.message);
    return Promise.reject(error);
  },
);

export default client;
