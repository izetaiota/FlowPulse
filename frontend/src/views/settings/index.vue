<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="系统设置"
    description="私有化部署配置中心：安全设置、存储与定时同步周期、Webhook 通知与日志管理。"
    :features="[
      '用户密码与安全设置',
      '私有化部署配置：存储路径、定时任务周期',
      '消息 / 作品数据 / 投流数据同步周期',
      'Webhook 通知：告警、日报、新消息推送到飞书 / 钉钉',
      '日志中心：操作日志、发布日志、同步失败日志',
    ]"
  />
</template>
