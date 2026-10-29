<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import AppLogoMark from "@/components/AppLogoMark.vue";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const username = ref("admin");
const password = ref("");
const loading = ref(false);

async function submit() {
  if (!username.value.trim() || !password.value) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  loading.value = true;
  try {
    await auth.login(username.value.trim(), password.value);
    ElMessage.success("登录成功");
    router.replace((route.query.redirect as string) || "/");
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "登录失败，请检查用户名和密码");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <!-- 品牌区 -->
    <aside class="login-brand-panel">
      <div class="brand-glow brand-glow-1" />
      <div class="brand-glow brand-glow-2" />
      <div class="brand-grid" />

      <div class="brand-body">
        <div class="brand-logo-row">
          <AppLogoMark class="brand-logo" />
          <div class="brand-name">心流 FlowPulse</div>
        </div>

        <h1 class="brand-slogan">
          繁杂交给系统<br />创作进入<span class="brand-accent">心流</span>
        </h1>
        <p class="brand-sub">自媒体全域运营工作台 · 私有化部署 · 数据自留</p>

        <ul class="brand-features">
          <li>
            <span class="feature-icon"><el-icon><Reading /></el-icon></span>
            <div>
              <div class="feature-title">公众号订阅 RSS</div>
              <div class="feature-desc">微信读书通道 · 定时增量同步 · 站内阅读</div>
            </div>
          </li>
          <li>
            <span class="feature-icon"><el-icon><VideoPlay /></el-icon></span>
            <div>
              <div class="feature-title">抖音转写</div>
              <div class="feature-desc">解析短视频 · 字幕与语音转写 · 结构化语料</div>
            </div>
          </li>
          <li>
            <span class="feature-icon"><el-icon><PictureFilled /></el-icon></span>
            <div>
              <div class="feature-title">小红书抓取</div>
              <div class="feature-desc">笔记 / 用户 / 搜索 · 媒体下载 · Excel 导出</div>
            </div>
          </li>
        </ul>
      </div>

      <div class="brand-footer">© 2026 心流 FlowPulse · MIT Open Source</div>
    </aside>

    <!-- 表单区 -->
    <main class="login-form-panel">
      <div class="login-form-box">
        <div class="form-mobile-brand">
          <AppLogoMark class="brand-logo brand-logo-sm" />
          <span>心流 FlowPulse</span>
        </div>

        <h2 class="form-title">欢迎回来 👋</h2>
        <p class="form-sub">登录你的工作台，继续今天的创作</p>

        <el-form size="large" @submit.prevent="submit">
          <el-form-item>
            <el-input
              v-model="username"
              placeholder="用户名"
              :prefix-icon="'User'"
              autocomplete="username"
              class="form-input"
            />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="password"
              type="password"
              placeholder="密码"
              :prefix-icon="'Lock'"
              show-password
              autocomplete="current-password"
              class="form-input"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="form-submit"
            :loading="loading"
            @click="submit"
          >
            {{ loading ? "登录中…" : "登 录" }}
          </el-button>
        </el-form>

        <div class="form-tip">
          账号由部署方在服务端环境变量中配置<br />
          <code>ADMIN_USERNAME</code> / <code>ADMIN_PASSWORD</code>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
}

/* ---------- 品牌区 ---------- */
.login-brand-panel {
  position: relative;
  flex: 1.35;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 56px 64px;
  color: #fff;
  background: linear-gradient(150deg, #312e81 0%, #4338ca 42%, #6d28d9 100%);
  overflow: hidden;
}

.brand-glow {
  position: absolute;
  border-radius: 9999px;
  filter: blur(90px);
  opacity: 0.5;
  pointer-events: none;
}

.brand-glow-1 {
  width: 420px;
  height: 420px;
  right: -140px;
  top: -120px;
  background: #818cf8;
}

.brand-glow-2 {
  width: 360px;
  height: 360px;
  left: -120px;
  bottom: -100px;
  background: #a78bfa;
  opacity: 0.35;
}

.brand-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at 30% 20%, #000 30%, transparent 75%);
  pointer-events: none;
}

.brand-body {
  position: relative;
}

.brand-logo-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 72px;
}

.brand-logo {
  width: 46px;
  height: 46px;
}

.brand-logo-sm {
  width: 32px;
  height: 32px;
}

.brand-name {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 1px;
}

.brand-slogan {
  margin: 0 0 14px;
  font-size: 40px;
  line-height: 1.35;
  font-weight: 700;
  letter-spacing: 1px;
}

.brand-accent {
  background: linear-gradient(90deg, #fbbf24, #f472b6);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.brand-sub {
  margin: 0 0 48px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.72);
  letter-spacing: 0.5px;
}

.brand-features {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.brand-features li {
  display: flex;
  align-items: center;
  gap: 14px;
}

.feature-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.feature-title {
  font-size: 14.5px;
  font-weight: 600;
}

.feature-desc {
  font-size: 12.5px;
  color: rgba(255, 255, 255, 0.62);
  margin-top: 2px;
}

.brand-footer {
  position: relative;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}

/* ---------- 表单区 ---------- */
.login-form-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
  padding: 40px 24px;
}

.login-form-box {
  width: 100%;
  max-width: 360px;
}

.form-mobile-brand {
  display: none;
  align-items: center;
  gap: 10px;
  margin-bottom: 36px;
  color: #1e293b;
  font-weight: 600;
}

.form-title {
  margin: 0 0 6px;
  font-size: 26px;
  font-weight: 700;
  color: #0f172a;
}

.form-sub {
  margin: 0 0 32px;
  font-size: 14px;
  color: #64748b;
}

.form-input :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 14px;
  box-shadow: 0 0 0 1px #e2e8f0;
  transition: box-shadow 0.2s;
}

.form-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px #6366f1;
}

.form-submit {
  width: 100%;
  margin-top: 6px;
  height: 46px;
  border-radius: 10px;
  font-size: 15px;
  letter-spacing: 4px;
  background: linear-gradient(90deg, #4f46e5, #6d28d9);
  border: none;
}

.form-submit:hover {
  opacity: 0.92;
}

.form-tip {
  margin-top: 28px;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.8;
}

.form-tip code {
  background: #eef2ff;
  color: #4f46e5;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}

/* ---------- 响应式 ---------- */
@media (max-width: 860px) {
  .login-brand-panel {
    display: none;
  }

  .form-mobile-brand {
    display: flex;
  }
}
</style>
