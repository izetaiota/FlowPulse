<template>
  <span class="app-logo-mark" aria-hidden="true">
    <svg viewBox="0 0 32 32" fill="none">
      <path
        d="M6 16h5l3-7 4 14 3-7h5"
        stroke="#fff"
        stroke-width="2.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  </span>
</template>

<style scoped>
/* 全站统一品牌标：紫渐变圆角方块 + 白色心电波，尺寸由使用方通过 class 指定 */
.app-logo-mark {
  display: grid;
  place-items: center;
  flex: none;
  border-radius: 27%;
  background: linear-gradient(135deg, #6366f1, #a855f7);
}

.app-logo-mark svg {
  width: 66%;
  height: 66%;
}
</style>
