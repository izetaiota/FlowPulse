<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 模块标题 */
    title: string;
    /** 模块定位描述（来自 plan.md 功能需求清单） */
    description: string;
    /** 模块功能点列表 */
    features?: string[];
    /** 开发状态标签 */
    status?: string;
  }>(),
  {
    features: () => [],
    status: "开发中",
  },
);
</script>

<template>
  <div>
    <el-card shadow="never" class="fp-module-card">
      <template #header>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="fp-bar" aria-hidden="true"></span>
            <h3 class="m-0 text-base font-bold">{{ title }}</h3>
          </div>
          <el-tag type="warning" effect="light" round>{{ status }}</el-tag>
        </div>
      </template>

      <p class="fp-desc">{{ description }}</p>

      <div v-if="features.length" class="fp-features">
        <el-tag
          v-for="feature in features"
          :key="feature"
          type="info"
          effect="plain"
          class="fp-feature-tag"
        >
          {{ feature }}
        </el-tag>
      </div>

      <el-empty description="该模块按 V1.0 规划推进中，敬请期待" :image-size="110" />
    </el-card>
  </div>
</template>

<style scoped>
.fp-module-card {
  border-radius: 12px;
}

.fp-bar {
  display: inline-block;
  width: 4px;
  height: 16px;
  border-radius: 2px;
  background: linear-gradient(180deg, #6366f1, #a855f7);
}

.fp-desc {
  margin: 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.8;
}

.fp-features {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 8px;
}

.fp-feature-tag {
  border-radius: 999px;
}
</style>
